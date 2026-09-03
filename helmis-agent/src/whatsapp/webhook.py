"""
webhook.py — Starlette HTTP Webhook Controller for WAHA and Scheduler events.
"""

import asyncio
import contextlib
import hmac
import logging
import os
import time

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from ..agent.delivery import outbox_drain_lifespan
from ..memory import get_vault_file_by_id, get_vault_file_by_name
from .client import WahaClient
from .history import is_duplicate_message
from .parser import (
    BOT_PHONE,
    BUNGA_PHONE,
    GILANG_PHONE,
    TRIO_GROUP_JID,
    extract_media_filename,
    extract_quoted_info,
    resolve_sender_identity,
)
from .policy import (
    decide_group_admission,
    is_group_chat,
)
from .processor import process_batched_turn
from .queue import ChatQueueManager, IncomingMessageEvent

log = logging.getLogger("helmis-whatsapp-webhook")

# Durable replay window (seconds). Rows older than this are pruned on access.
_REPLAY_DEDUP_WINDOW_SECONDS = 3600.0


def _is_replayed_message(message_id: str) -> bool:
    """Check the durable processed-messages table; ignores store failures."""
    try:
        from ..memory.store import get_repository

        return get_repository().register_seen_message(
            message_id, window_seconds=_REPLAY_DEDUP_WINDOW_SECONDS
        )
    except Exception as e:  # pragma: no cover - degraded mode must not drop messages
        log.warning("Durable dedup unavailable, allowing message %s: %s", message_id, e)
        return False


def create_webhook_app(client: WahaClient) -> Starlette:
    """Create Starlette app for webhooks and health checks with Per-Chat Debounce Queue."""

    async def turn_runner(batch: list[IncomingMessageEvent], mailbox: asyncio.Queue[IncomingMessageEvent] | None = None) -> None:
        await process_batched_turn(client=client, batch=batch, mailbox=mailbox)

    queue_manager = ChatQueueManager(turn_handler=turn_runner, debounce_seconds=0.4)

    async def handle_health(request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    async def handle_ready(request: Request) -> JSONResponse:
        waha_ok = await client.is_reachable()
        return JSONResponse(
            {"status": "ok", "waha_reachable": waha_ok}, status_code=200 if waha_ok else 503
        )

    async def handle_waha_webhook(request: Request) -> JSONResponse:
        expected_secret = (
            os.environ.get("SCHEDULER_WEBHOOK_SECRET", "").strip()
            if request.url.path.endswith("/scheduler")
            else os.environ.get("WAHA_WEBHOOK_SECRET", "").strip()
        )
        if expected_secret:
            supplied_secret = request.headers.get(
                "x-scheduler-webhook-secret"
                if request.url.path.endswith("/scheduler")
                else "x-waha-webhook-secret",
                "",
            )
            if not hmac.compare_digest(supplied_secret, expected_secret):
                return JSONResponse({"status": "unauthorized"}, status_code=401)
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"status": "invalid_json"}, status_code=400)

        event = body.get("event")
        payload = body.get("payload", {})

        # Handle incoming message events
        if event in ("message", "message.any"):
            from_user = str(payload.get("from", "")).strip()
            if from_user == "status@broadcast" or str(payload.get("to", "")).strip() == "status@broadcast":
                return JSONResponse({"status": "ignored_status_event"})
            from_me = payload.get("fromMe", False)
            text = str(payload.get("body") or payload.get("caption") or "").strip()
            has_media = bool(payload.get("hasMedia") or payload.get("media"))
            media_info = payload.get("media") if isinstance(payload.get("media"), dict) else {}
            media_url = str(media_info.get("url", "")) if media_info else ""
            media_type = str(media_info.get("mimetype", "")) if media_info else None
            media_filename = extract_media_filename(payload)

            # Ignore self-messages or completely empty messages without media
            if from_me or (not text and not has_media):
                return JSONResponse({"status": "ignored_self_or_empty"})

            raw_id = payload.get("id")
            reply_id: str | None = None
            if isinstance(raw_id, dict):
                reply_id = raw_id.get("_serialized") or raw_id.get("id")
            elif isinstance(raw_id, str):
                reply_id = raw_id

            # Check duplicate event (in-memory short window + durable replay window)
            if is_duplicate_message(reply_id):
                log.debug("Ignoring duplicate message event: %s", reply_id)
                return JSONResponse({"status": "ignored_duplicate"})
            if reply_id and _is_replayed_message(reply_id):
                log.info("Ignoring replayed message (durable dedup): %s", reply_id)
                return JSONResponse({"status": "ignored_replayed_message"})

            # Resolve sender identity
            author = str(
                payload.get("author")
                or payload.get("participant")
                or payload.get("_data", {}).get("author")
                or ""
            )
            notify_name = str(
                payload.get("_data", {}).get("notifyName") or payload.get("notifyName") or ""
            )
            sender_name = resolve_sender_identity(from_user=from_user, author=author, notify_name=notify_name)

            log.info("Webhook message from=%s author=%s resolved_sender=%s text=%r media_filename=%s", from_user, author, sender_name, text[:40], media_filename)

            # Silently drop messages from anyone else
            if not sender_name:
                log.warning(
                    "Dropping message from unauthorized sender: from=%s author=%s (%s)",
                    from_user,
                    author,
                    notify_name,
                )
                return JSONResponse({"status": "ignored_unauthorized_sender"})

            is_group = is_group_chat(from_user)
            if is_group and TRIO_GROUP_JID and from_user != TRIO_GROUP_JID:
                log.debug("Silently ignoring message from unauthorized group: %s", from_user)
                return JSONResponse({"status": "ignored_non_whitelisted_group"})

            # Extract quoted / reply message if present
            (
                quoted_text,
                quoted_sender,
                quoted_type,
                quoted_media_url,
                quoted_media_type,
                quoted_stanza_id,
                quoted_media_filename,
            ) = extract_quoted_info(payload)
            if quoted_text or quoted_type:
                log.info(
                    "Detected quoted message in [%s] from [%s] (type: %s fn: %s): %s",
                    from_user,
                    quoted_sender,
                    quoted_type,
                    quoted_media_filename,
                    quoted_text[:50] if quoted_text else "(media)",
                )

            # STRICT FILTER 3: Group chat discretion — do NOT interrupt human banter
            if is_group:
                decision = decide_group_admission(
                    text,
                    payload,
                    bot_phone=BOT_PHONE,
                    owner_phone=GILANG_PHONE,
                    partner_phone=BUNGA_PHONE,
                    quoted_sender=quoted_sender,
                )
                if decision == "ignored_directed_to_other":
                    log.info("Group message addressed to other person (@mention), ignoring: %s", text[:40])
                    return JSONResponse({"status": "ignored_directed_to_other"})

            log.debug(
                "Incoming WhatsApp message from [%s] in (%s) (media: %s fn: %s): %s",
                sender_name,
                from_user,
                has_media,
                media_filename,
                text[:50],
            )

            # Dispatch into Per-Chat Queue with 1.0s Burst Debouncing
            queue_manager.dispatch(
                IncomingMessageEvent(
                    sender_name=sender_name,
                    from_user=from_user,
                    reply_id=reply_id,
                    text=text,
                    has_media=has_media,
                    media_url=media_url,
                    media_type=media_type,
                    media_filename=media_filename,
                    timestamp=time.time(),
                    quoted_text=quoted_text,
                    quoted_sender=quoted_sender,
                    quoted_type=quoted_type,
                    quoted_media_url=quoted_media_url,
                    quoted_media_type=quoted_media_type,
                    quoted_media_filename=quoted_media_filename,
                    quoted_stanza_id=quoted_stanza_id,
                )
            )
            return JSONResponse({"status": "queued", "sender": sender_name, "chat_id": from_user})

        # Scheduler tick
        elif event == "scheduler.tick":
            log.info("Received scheduler proactive tick, evaluating due tasks...")
            from ..agent.proactive import handle_proactive_scheduler_tick

            asyncio.create_task(handle_proactive_scheduler_tick(client))
            return JSONResponse({"status": "tick_processed"})

        return JSONResponse({"status": "ignored_event", "event": event})

    async def handle_vault_file(request: Request) -> Response:
        file_id = request.path_params.get("file_id", "")
        res = get_vault_file_by_id(file_id)
        if not res:
            res = get_vault_file_by_name(file_id)
        if not res:
            return JSONResponse({"status": "not_found", "error": "File not found in vault"}, status_code=404)
        record, raw_bytes = res
        mime = record.get("mime_type", "application/octet-stream")
        filename = record.get("filename", "document")
        return Response(
            content=raw_bytes,
            media_type=mime,
            headers={
                "Content-Disposition": f'inline; filename="{filename}"',
                "Content-Length": str(len(raw_bytes)),
            },
        )

    routes = [
        Route("/health", handle_health, methods=["GET"]),
        Route("/ping", handle_health, methods=["GET"]),
        Route("/ready", handle_ready, methods=["GET"]),
        Route("/vault/file/{file_id}", handle_vault_file, methods=["GET"]),
        Route("/webhooks/waha", handle_waha_webhook, methods=["POST"]),
        Route("/webhooks/scheduler", handle_waha_webhook, methods=["POST"]),
    ]

    @contextlib.asynccontextmanager
    async def _app_lifespan(app):
        async with contextlib.AsyncExitStack() as stack:
            await stack.enter_async_context(outbox_drain_lifespan(client))
            yield

    return Starlette(debug=False, routes=routes, lifespan=_app_lifespan)
