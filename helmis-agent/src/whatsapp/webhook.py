"""
webhook.py — Starlette HTTP Webhook Controller for WAHA and Scheduler events.
"""

import asyncio
import logging
import time

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

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
from .processor import process_batched_turn
from .queue import ChatQueueManager, IncomingMessageEvent

log = logging.getLogger("helmis-whatsapp-webhook")


def create_webhook_app(client: WahaClient) -> Starlette:
    """Create Starlette app for webhooks and health checks with Per-Chat Debounce Queue."""

    async def turn_runner(batch: list[IncomingMessageEvent], mailbox: asyncio.Queue[IncomingMessageEvent] | None = None) -> None:
        await process_batched_turn(client=client, batch=batch, mailbox=mailbox)

    queue_manager = ChatQueueManager(turn_handler=turn_runner, debounce_seconds=1.0)

    async def handle_health(request: Request) -> JSONResponse:
        waha_ok = await client.is_reachable()
        return JSONResponse(
            {"status": "ok", "waha_reachable": waha_ok}, status_code=200 if waha_ok else 503
        )

    async def handle_waha_webhook(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"status": "invalid_json"}, status_code=400)

        event = body.get("event")
        payload = body.get("payload", {})

        # Handle incoming message events
        if event in ("message", "message.any"):
            from_user = str(payload.get("from", "")).strip()
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

            # Check duplicate event
            if is_duplicate_message(reply_id):
                log.debug("Ignoring duplicate message event: %s", reply_id)
                return JSONResponse({"status": "ignored_duplicate"})

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

            is_group = from_user.endswith("@g.us")
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
                text_lower = text.lower()
                bot_clean = BOT_PHONE.replace("+", "").replace(" ", "").replace("-", "")
                gilang_clean = GILANG_PHONE.replace("+", "").replace(" ", "").replace("-", "")
                bunga_clean = BUNGA_PHONE.replace("+", "").replace(" ", "").replace("-", "")

                _data_dict = payload.get("_data") if isinstance(payload.get("_data"), dict) else {}
                mentioned = (
                    payload.get("mentionedIds")
                    or payload.get("mentions")
                    or payload.get("mentionedJidList")
                    or _data_dict.get("mentionedJidList")
                    or _data_dict.get("mentions")
                    or []
                )

                is_quoting_bot = (quoted_sender == "Helmis")
                has_bot_mention = (
                    is_quoting_bot
                    or "helmis" in text_lower
                    or text_lower.startswith("mis ")
                    or text_lower.startswith("mis,")
                    or text_lower.startswith("mis?")
                    or "@helmis" in text_lower
                    or (bool(bot_clean) and any(bot_clean in str(m) for m in mentioned))
                )

                mentions_other = (
                    any(
                        (bool(gilang_clean) and gilang_clean in str(m))
                        or (bool(bunga_clean) and bunga_clean in str(m))
                        for m in mentioned
                    )
                    or "@bunga" in text_lower
                    or "@gilang" in text_lower
                    or (bool(gilang_clean) and f"@{gilang_clean}" in text_lower)
                    or (bool(bunga_clean) and f"@{bunga_clean}" in text_lower)
                ) and not has_bot_mention

                if mentions_other:
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
            from ..proactive import handle_proactive_scheduler_tick

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
        Route("/vault/file/{file_id}", handle_vault_file, methods=["GET"]),
        Route("/webhooks/waha", handle_waha_webhook, methods=["POST"]),
        Route("/webhooks/scheduler", handle_waha_webhook, methods=["POST"]),
    ]

    return Starlette(debug=False, routes=routes)
