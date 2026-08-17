"""
webhook.py — Starlette HTTP webhook receiver for WAHA and Scheduler events.
"""

import asyncio
import logging
import os

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .agent import run_agentic_react_loop
from .client import WahaClient
from .history import is_duplicate_message
from .proactive import handle_proactive_scheduler_tick

log = logging.getLogger("helmis-webhook")

GILANG_PHONE = (
    os.environ.get("GILANG_PHONE", "")
    .replace("+", "")
    .replace(" ", "")
    .replace("-", "")
)
BUNGA_PHONE = (
    os.environ.get("BUNGA_PHONE", "")
    .replace("+", "")
    .replace(" ", "")
    .replace("-", "")
)
BOT_PHONE = (
    os.environ.get("BOT_PHONE", "").replace("+", "").replace(" ", "").replace("-", "")
)

TRIO_GROUP_JID = os.environ.get("TRIO_GROUP_JID", "")
ALLOWED_CHATS = set(
    filter(
        None,
        [
            f"{GILANG_PHONE}@c.us" if GILANG_PHONE else None,
            f"{BUNGA_PHONE}@c.us" if BUNGA_PHONE else None,
            TRIO_GROUP_JID if TRIO_GROUP_JID else None,
            os.environ.get("GILANG_LID"),
            os.environ.get("BUNGA_LID"),
        ],
    )
)


def create_webhook_app(client: WahaClient) -> Starlette:
    """Create Starlette app for webhooks and health checks."""

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

            # Ignore self-messages or completely empty messages without media
            if from_me or (not text and not has_media):
                return JSONResponse({"status": "ignored_self_or_empty"})

            # STRICT FILTER 1: Must be from either an authorized group or whitelisted DM
            is_group = from_user.endswith("@g.us")
            if not is_group and from_user not in ALLOWED_CHATS:
                log.debug("Silently ignoring message from non-whitelisted DM: %s", from_user)
                return JSONResponse({"status": "ignored_non_whitelisted_chat"})
            if is_group and TRIO_GROUP_JID and from_user != TRIO_GROUP_JID:
                log.debug("Silently ignoring message from non-whitelisted group: %s", from_user)
                return JSONResponse({"status": "ignored_non_whitelisted_group"})

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
            clean_author = author.split("@")[0].replace("+", "").replace(" ", "").replace("-", "")
            clean_from = from_user.split("@")[0].replace("+", "").replace(" ", "").replace("-", "")
            notify_name = str(
                payload.get("_data", {}).get("notifyName") or payload.get("notifyName") or ""
            )

            # STRICT FILTER 2: Only Gilang or Bunga are authorized
            sender_name: str | None = None
            if (
                (bool(GILANG_PHONE) and (clean_from == GILANG_PHONE or clean_author == GILANG_PHONE))
                or clean_from.startswith("217188174717173")
                or clean_author.startswith("217188174717173")
                or "gilang" in notify_name.lower()
            ):
                sender_name = "Gilang"
            elif (
                (bool(BUNGA_PHONE) and (clean_from == BUNGA_PHONE or clean_author == BUNGA_PHONE))
                or clean_from.startswith("279821464654020")
                or clean_author.startswith("279821464654020")
                or "bunga" in notify_name.lower()
            ):
                sender_name = "Bunga"

            # Silently drop messages from anyone else
            if not sender_name:
                log.debug(
                    "Silently dropping message from unauthorized participant in group: %s (%s)",
                    author,
                    notify_name,
                )
                return JSONResponse({"status": "ignored_unauthorized_sender"})

            # STRICT FILTER 3: Group chat discretion — do NOT interrupt human banter
            is_group = from_user.endswith("@g.us")
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

                has_bot_mention = (
                    "helmis" in text_lower
                    or text_lower.startswith("mis ")
                    or text_lower.startswith("mis,")
                    or text_lower.startswith("mis?")
                    or "@helmis" in text_lower
                    or (bool(bot_clean) and any(bot_clean in str(m) for m in mentioned))
                )

                mentions_other = bool(
                    (
                        any(
                            (bool(gilang_clean) and gilang_clean in str(m))
                            or (bool(bunga_clean) and bunga_clean in str(m))
                            for m in mentioned
                        )
                        or "@bunga" in text_lower
                        or "@gilang" in text_lower
                        or (bool(gilang_clean) and f"@{gilang_clean}" in text_lower)
                        or (bool(bunga_clean) and f"@{bunga_clean}" in text_lower)
                    )
                    and not has_bot_mention
                )

                if mentions_other:
                    log.info("Group message addressed to other person (@mention), ignoring: %s", text[:40])
                    return JSONResponse({"status": "ignored_directed_to_other"})

            log.info(
                "Incoming WhatsApp message from [%s] in (%s) (media: %s): %s",
                sender_name,
                from_user,
                has_media,
                text[:50],
            )

            # Run Autonomous Multi-Step ReAct Agent Loop asynchronously
            async def process_and_reply() -> None:
                nonlocal text
                # Indicate active typing presence while agent reasons and executes tools
                await client.start_typing(chat_id=from_user)
                from .logger import AgentTurnTracer

                tracer = AgentTurnTracer(
                    sender_name=sender_name,
                    chat_id=from_user,
                    message_text=text,
                    has_media=has_media,
                )
                tracer.log_incoming()

                try:
                    is_voice_note = False
                    vn_transcript: str | None = None
                    media_data: dict[str, str] | None = None

                    if has_media and media_url:
                        media_res = await client.download_media_base64(media_url)
                        if media_res:
                            mime_type, b64_data = media_res
                            if mime_type.startswith("audio/"):
                                is_voice_note = True
                                log.info("Phase 1: Running dedicated audio transcription for [%s]...", sender_name)
                                from .agent import transcribe_audio_base64

                                vn_transcript = await transcribe_audio_base64(b64_data, mime_type)
                                if not vn_transcript:
                                    log.warning("Audio was silent or unintelligible.")
                                    fallback_msg = '> "(Audio tidak terdengar jelas)"\n\nMaaf, pesan suara tidak terdengar jelas. Bisa tolong ulangi lagi?'
                                    tracer.log_completed(fallback_msg, status="unintelligible_audio")
                                    await client.send_message(
                                        chat_id=from_user,
                                        text=fallback_msg,
                                        reply_to_message_id=reply_id,
                                    )
                                    return
                                # Set effective text to the exact verified transcript
                                text = vn_transcript
                                tracer.message_text = vn_transcript
                                log.info("Phase 1 Success: Transcribed VN as: %s", text)
                            else:
                                media_data = {"mimeType": mime_type, "data": b64_data}

                    # Phase 2: Run autonomous agent loop on verified text/media
                    reply_text = await run_agentic_react_loop(
                        client=client,
                        sender_name=sender_name,
                        chat_id=from_user,
                        message_text=text,
                        media_data=media_data,
                        max_steps=5,
                        tracer=tracer,
                    )

                    final_text: str | None = None
                    if reply_text and reply_text.strip() not in ("[NO_REPLY]", "NO_REPLY", "None"):
                        clean_reply = reply_text.strip()
                        # If this turn was a Voice Note, guarantee the verified blockquote prefix at Python level
                        if is_voice_note and vn_transcript:
                            if clean_reply.startswith("> "):
                                lines = clean_reply.split("\n", 2)
                                if len(lines) > 2:
                                    clean_reply = lines[2].strip()
                                elif len(lines) > 1:
                                    clean_reply = lines[1].strip()
                            final_text = f'> "{vn_transcript}"\n\n{clean_reply}'
                        else:
                            final_text = clean_reply

                        tracer.log_completed(final_text, status="dispatched")
                        await client.send_message(
                            chat_id=from_user,
                            text=final_text,
                            reply_to_message_id=reply_id if (has_media and reply_id) else None,
                        )
                        log.info("Sent verified reply to [%s] in %s", sender_name, from_user)

                        # Schedule passive background fact extraction into semantic memory using the actual transcript text!
                        from . import semantic_memory

                        asyncio.create_task(
                            semantic_memory.extract_facts_from_turn_background(
                                user_message=text,
                                assistant_reply=final_text,
                                sender_name=sender_name,
                            )
                        )
                    else:
                        tracer.log_completed(None, status="silent_no_reply")
                finally:
                    await client.stop_typing(chat_id=from_user)

            asyncio.create_task(process_and_reply())
            return JSONResponse({"status": "received", "sender": sender_name})

        # Scheduler tick
        elif event == "scheduler.tick":
            log.info("Received scheduler proactive tick, evaluating due tasks...")
            asyncio.create_task(handle_proactive_scheduler_tick(client))
            return JSONResponse({"status": "tick_processed"})

        return JSONResponse({"status": "ignored_event", "event": event})

    routes = [
        Route("/health", handle_health, methods=["GET"]),
        Route("/ping", handle_health, methods=["GET"]),
        Route("/webhooks/waha", handle_waha_webhook, methods=["POST"]),
        Route("/webhooks/scheduler", handle_waha_webhook, methods=["POST"]),
    ]

    return Starlette(debug=False, routes=routes)
