"""
webhook.py — Starlette HTTP webhook receiver for WAHA and Scheduler events.
"""

import asyncio
import logging
import os
import time
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .agent import run_agentic_react_loop
from .client import WahaClient
from .history import is_duplicate_message
from .proactive import handle_proactive_scheduler_tick
from .queue import ChatQueueManager, IncomingMessageEvent

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


def extract_quoted_info(
    payload: dict[str, Any],
) -> tuple[str | None, str | None, str | None, str | None, str | None]:
    """
    Extract quoted / replied message metadata from WAHA payloads across all engines (GOWS, NOWEB, WEBJS).
    Returns (quoted_text, quoted_sender, quoted_type, quoted_media_url, quoted_media_type).
    """
    quoted_text: str | None = None
    quoted_sender: str | None = None
    quoted_type: str | None = None
    quoted_media_url: str | None = None
    quoted_media_type: str | None = None

    def resolve_sender(participant: str, from_me: bool) -> str:
        if from_me:
            return "Helmis"
        clean = participant.split("@")[0].replace("+", "").replace(" ", "").replace("-", "")
        if (bool(GILANG_PHONE) and clean == GILANG_PHONE) or clean.startswith("217188174717173"):
            return "Gilang"
        if (bool(BUNGA_PHONE) and clean == BUNGA_PHONE) or clean.startswith("279821464654020"):
            return "Bunga"
        return "Pesan Sebelumnya"

    # 1. Top-level replyTo
    reply_to = payload.get("replyTo")
    if isinstance(reply_to, dict):
        quoted_type = str(reply_to.get("type", "")).strip().lower() or None
        quoted_text = str(reply_to.get("body") or reply_to.get("caption") or "").strip() or None
        media_obj = reply_to.get("media") if isinstance(reply_to.get("media"), dict) else {}
        if media_obj:
            quoted_media_url = str(media_obj.get("url", "")) or None
        part = str(reply_to.get("participant") or reply_to.get("from") or "")
        quoted_sender = resolve_sender(part, bool(reply_to.get("fromMe", False)))

    # 2. _data.quotedMsg
    _data_raw = payload.get("_data")
    _data: dict[str, Any] = _data_raw if isinstance(_data_raw, dict) else {}
    if not quoted_text and not quoted_type:
        data_quoted = _data.get("quotedMsg") or payload.get("quotedMsg")
        if isinstance(data_quoted, dict):
            quoted_type = str(data_quoted.get("type", "")).strip().lower() or None
            quoted_text = str(data_quoted.get("body") or data_quoted.get("caption") or "").strip() or None
            part = str(_data.get("quotedParticipant") or payload.get("quotedParticipant") or "")
            quoted_sender = resolve_sender(part, bool(data_quoted.get("fromMe", False)))

    # 3. GOWS Protobuf contextInfo (extendedTextMessage.contextInfo or contextInfo)
    msg_raw = _data.get("Message")
    msg_obj: dict[str, Any] = msg_raw if isinstance(msg_raw, dict) else {}
    ext_raw = msg_obj.get("extendedTextMessage")
    ext_obj: dict[str, Any] = ext_raw if isinstance(ext_raw, dict) else {}
    context_info = (
        ext_obj.get("contextInfo")
        or _data.get("contextInfo")
        or payload.get("contextInfo")
    )
    if isinstance(context_info, dict):
        part = str(context_info.get("participant") or "")
        if not quoted_sender and part:
            quoted_sender = resolve_sender(part, False)

        q_msg = context_info.get("quotedMessage")
        if isinstance(q_msg, dict):
            if "audioMessage" in q_msg:
                audio = q_msg["audioMessage"]
                sec = audio.get("seconds")
                quoted_type = "ptt" if audio.get("ptt") else "audio"
                quoted_text = f"Pesan Suara / Voice Note ({sec} detik)" if sec else "Pesan Suara (Voice Note)"
            elif "imageMessage" in q_msg:
                img = q_msg["imageMessage"]
                caption = str(img.get("caption", "")).strip()
                quoted_type = "image"
                quoted_text = f'Foto / Gambar{": " + caption if caption else ""}'
            elif "conversation" in q_msg:
                quoted_type = "chat"
                quoted_text = str(q_msg["conversation"]).strip()
            elif "extendedTextMessage" in q_msg:
                quoted_type = "chat"
                quoted_text = str(q_msg["extendedTextMessage"].get("text", "")).strip()
            elif "documentMessage" in q_msg:
                doc = q_msg["documentMessage"]
                doc_title = doc.get("title") or doc.get("fileName")
                quoted_type = "document"
                quoted_text = f'Dokumen{": " + str(doc_title) if doc_title else ""}'
            elif "stickerMessage" in q_msg:
                quoted_type = "sticker"
                quoted_text = "Stiker"

    # Fallback type descriptions if text is still empty
    if quoted_type and not quoted_text:
        if quoted_type in ("ptt", "audio"):
            quoted_text = "Pesan Suara (Voice Note)"
        elif quoted_type in ("image", "video"):
            quoted_text = "Foto / Gambar"
        elif quoted_type == "document":
            quoted_text = "Dokumen"
        elif quoted_type == "sticker":
            quoted_text = "Stiker"

    return quoted_text, quoted_sender, quoted_type, quoted_media_url, quoted_media_type


def create_webhook_app(client: WahaClient) -> Starlette:
    """Create Starlette app for webhooks and health checks with Per-Chat Debounce Queue."""

    async def process_batched_turn(batch: list[IncomingMessageEvent]) -> None:
        if not batch:
            return

        last_event = batch[-1]
        sender_name = last_event.sender_name
        from_user = last_event.from_user
        reply_id = last_event.reply_id

        # Combine all debounced texts into a single coherent prompt, preserving quoted context
        all_texts: list[str] = []
        for e in batch:
            t = e.text.strip() if e.text else ""

            # Resolve quoted content (text or media)
            quoted_desc = e.quoted_text
            if e.quoted_type in ("ptt", "audio"):
                if e.quoted_media_url:
                    try:
                        q_media_res = await client.download_media_base64(e.quoted_media_url)
                        if q_media_res:
                            q_mime, q_b64 = q_media_res
                            from .agent import transcribe_audio_base64

                            q_transcript = await transcribe_audio_base64(q_b64, q_mime)
                            if q_transcript:
                                quoted_desc = f'Pesan Suara (Voice Note): "{q_transcript}"'
                            else:
                                quoted_desc = "Pesan Suara (Voice Note)"
                        else:
                            quoted_desc = "Pesan Suara (Voice Note)"
                    except Exception as err:
                        log.warning("Could not transcribe quoted VN: %s", err)
                        quoted_desc = "Pesan Suara (Voice Note)"
                else:
                    quoted_desc = "Pesan Suara (Voice Note)"
            elif e.quoted_type in ("image", "video"):
                quoted_desc = f'Foto / Gambar{": " + quoted_desc if quoted_desc else ""}'
            elif e.quoted_type == "document":
                quoted_desc = f'Dokumen{": " + quoted_desc if quoted_desc else ""}'
            elif e.quoted_type == "sticker":
                quoted_desc = "Stiker"

            if quoted_desc:
                q_label = e.quoted_sender or "Pesan Sebelumnya"
                quoted_block = f'> [{q_label}]: "{quoted_desc.strip()}"'
                t = f"{quoted_block}\n\n{t}" if t else quoted_block

            if t:
                all_texts.append(t)

        combined_text = "\n\n".join(all_texts)

        has_media = any(e.has_media for e in batch)
        media_event = next((e for e in reversed(batch) if e.has_media and e.media_url), None)
        media_url = media_event.media_url if media_event else None

        await client.start_typing(chat_id=from_user)
        from .logger import AgentTurnTracer

        tracer = AgentTurnTracer(
            sender_name=sender_name,
            chat_id=from_user,
            message_text=combined_text,
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
                        combined_text = vn_transcript
                        tracer.message_text = vn_transcript
                        log.info("Phase 1 Success: Transcribed VN as: %s", combined_text)
                    else:
                        media_data = {"mimeType": mime_type, "data": b64_data}

            # Phase 2: Run autonomous agent loop on verified text/media
            reply_text = await run_agentic_react_loop(
                client=client,
                sender_name=sender_name,
                chat_id=from_user,
                message_text=combined_text,
                media_data=media_data,
                max_steps=5,
                tracer=tracer,
            )

            final_text: str | None = None
            if reply_text and reply_text.strip() not in ("[NO_REPLY]", "NO_REPLY", "None"):
                clean_reply = reply_text.strip()
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
                log.debug("Sent verified reply to [%s] in %s", sender_name, from_user)

                from . import semantic_memory

                asyncio.create_task(
                    semantic_memory.extract_facts_from_turn_background(
                        user_message=combined_text,
                        assistant_reply=final_text,
                        sender_name=sender_name,
                    )
                )
            else:
                tracer.log_completed(None, status="silent_no_reply")
        finally:
            await client.stop_typing(chat_id=from_user)

    queue_manager = ChatQueueManager(turn_handler=process_batched_turn, debounce_seconds=1.0)

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
            clean_author = author.split("@")[0].replace("+", "").replace(" ", "").replace("-", "")
            clean_from = from_user.split("@")[0].replace("+", "").replace(" ", "").replace("-", "")
            notify_name = str(
                payload.get("_data", {}).get("notifyName") or payload.get("notifyName") or ""
            )

            # STRICT AUTHORIZATION: Only Gilang or Bunga are authorized
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
                    "Silently dropping message from unauthorized sender: from=%s author=%s (%s)",
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
            ) = extract_quoted_info(payload)
            if quoted_text or quoted_type:
                log.info(
                    "Detected quoted message in [%s] from [%s] (type: %s): %s",
                    from_user,
                    quoted_sender,
                    quoted_type,
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

            log.debug(
                "Incoming WhatsApp message from [%s] in (%s) (media: %s): %s",
                sender_name,
                from_user,
                has_media,
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
                    timestamp=time.time(),
                    quoted_text=quoted_text,
                    quoted_sender=quoted_sender,
                    quoted_type=quoted_type,
                    quoted_media_url=quoted_media_url,
                    quoted_media_type=quoted_media_type,
                )
            )
            return JSONResponse({"status": "queued", "sender": sender_name, "chat_id": from_user})

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
