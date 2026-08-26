"""
webhook.py — Starlette HTTP webhook receiver for WAHA and Scheduler events.
"""

import asyncio
import logging
import os
import re
import time
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from .agent import run_agentic_react_loop
from .client import WahaClient
from .history import is_duplicate_message
from .proactive import handle_proactive_scheduler_tick
from .queue import ChatQueueManager, IncomingMessageEvent
from .vault import get_vault_file_by_id, get_vault_file_by_name

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
GILANG_LID = (
    os.environ.get("GILANG_LID") or "217188174717173"
).replace("+", "").replace(" ", "").replace("-", "").split("@")[0].split(":")[0]

BUNGA_LID = (
    os.environ.get("BUNGA_LID") or "279821464654020"
).replace("+", "").replace(" ", "").replace("-", "").split("@")[0].split(":")[0]

TRIO_GROUP_JID = os.environ.get("TRIO_GROUP_JID", "")
ALLOWED_CHATS = set(
    filter(
        None,
        [
            f"{GILANG_PHONE}@c.us" if GILANG_PHONE else None,
            f"{BUNGA_PHONE}@c.us" if BUNGA_PHONE else None,
            TRIO_GROUP_JID if TRIO_GROUP_JID else None,
            f"{GILANG_LID}@lid" if GILANG_LID else None,
            f"{BUNGA_LID}@lid" if BUNGA_LID else None,
            "217188174717173@lid",
            "279821464654020@lid",
        ],
    )
)


def extract_quoted_info(
    payload: dict[str, Any],
) -> tuple[str | None, str | None, str | None, str | None, str | None, str | None]:
    """
    Extract quoted / replied message metadata from WAHA payloads across all engines (GOWS, NOWEB, WEBJS).
    Returns (quoted_text, quoted_sender, quoted_type, quoted_media_url, quoted_media_type, quoted_stanza_id).
    """
    quoted_text: str | None = None
    quoted_sender: str | None = None
    quoted_type: str | None = None
    quoted_media_url: str | None = None
    quoted_media_type: str | None = None
    quoted_stanza_id: str | None = None

    def resolve_sender(participant: str, from_me: bool) -> str:
        if from_me:
            return "Helmis"
        clean = participant.split("@")[0].split(":")[0].replace("+", "").replace(" ", "").replace("-", "")
        if (bool(GILANG_PHONE) and clean == GILANG_PHONE) or (bool(GILANG_LID) and (clean == GILANG_LID or clean.startswith(GILANG_LID))):
            return "Gilang"
        if (bool(BUNGA_PHONE) and clean == BUNGA_PHONE) or (bool(BUNGA_LID) and (clean == BUNGA_LID or clean.startswith(BUNGA_LID))):
            return "Bunga"
        return "Pesan Sebelumnya"

    # 1. Top-level replyTo
    reply_to = payload.get("replyTo")
    if isinstance(reply_to, dict):
        quoted_type = str(reply_to.get("type", "")).strip().lower() or None
        quoted_text = str(reply_to.get("body") or reply_to.get("caption") or "").strip() or None
        quoted_stanza_id = str(reply_to.get("id", "")).strip() or None
        media_obj = reply_to.get("media") if isinstance(reply_to.get("media"), dict) else {}
        if media_obj:
            quoted_media_url = str(media_obj.get("url", "")) or None
            quoted_media_type = str(media_obj.get("mimetype", "")) or None
        part = str(reply_to.get("participant") or reply_to.get("from") or "")
        quoted_sender = resolve_sender(part, bool(reply_to.get("fromMe", False)))

    # 2. _data.quotedMsg
    _data_raw = payload.get("_data")
    _data: dict[str, Any] = _data_raw if isinstance(_data_raw, dict) else {}
    if not quoted_stanza_id:
        quoted_stanza_id = str(_data.get("quotedStanzaId") or "").strip() or None

    if not quoted_text and not quoted_type:
        data_quoted = _data.get("quotedMsg") or payload.get("quotedMsg")
        if isinstance(data_quoted, dict):
            quoted_type = str(data_quoted.get("type", "")).strip().lower() or None
            quoted_text = str(data_quoted.get("body") or data_quoted.get("caption") or "").strip() or None
            if not quoted_stanza_id:
                quoted_stanza_id = str(data_quoted.get("id", "")).strip() or None
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
        if not quoted_stanza_id:
            quoted_stanza_id = str(context_info.get("stanzaId", "")).strip() or None

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
                if audio.get("url"):
                    quoted_media_url = str(audio["url"])
                quoted_media_type = "audio/ogg"
            elif "imageMessage" in q_msg:
                img = q_msg["imageMessage"]
                caption = str(img.get("caption", "")).strip()
                quoted_type = "image"
                quoted_text = f'Foto / Gambar{": " + caption if caption else ""}'
                if img.get("url"):
                    quoted_media_url = str(img["url"])
                quoted_media_type = "image/jpeg"
            elif "videoMessage" in q_msg:
                vid = q_msg["videoMessage"]
                caption = str(vid.get("caption", "")).strip()
                quoted_type = "video"
                quoted_text = f'Video{": " + caption if caption else ""}'
                if vid.get("url"):
                    quoted_media_url = str(vid["url"])
                quoted_media_type = "video/mp4"
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
                if doc.get("url"):
                    quoted_media_url = str(doc["url"])
                quoted_media_type = str(doc.get("mimetype") or "application/pdf")
            elif "stickerMessage" in q_msg:
                quoted_type = "sticker"
                quoted_text = "Stiker"

    # Fallback type descriptions if text is still empty
    if quoted_type and not quoted_text:
        if quoted_type in ("ptt", "audio"):
            quoted_text = "Pesan Suara (Voice Note)"
        elif quoted_type == "video":
            quoted_text = "Video"
        elif quoted_type == "image":
            quoted_text = "Foto / Gambar"
        elif quoted_type == "document":
            quoted_text = "Dokumen"
        elif quoted_type == "sticker":
            quoted_text = "Stiker"

    return (
        quoted_text,
        quoted_sender,
        quoted_type,
        quoted_media_url,
        quoted_media_type,
        quoted_stanza_id,
    )


def describe_intent_action(
    text: str,
    has_media: bool = False,
    media_data: dict[str, Any] | None = None,
    is_voice_note: bool = False,
    current_tool: str | None = None,
    tool_args: dict[str, Any] | None = None,
) -> str:
    """Generate a sharp, non-templated description of what Helmis is actively working on."""
    if current_tool:
        if current_tool == "search_vault_files":
            q = (tool_args or {}).get("query", "")
            return f"sedang mencari dokumen '{q}' di dalam brankas" if q else "sedang mencari file di dalam brankas"
        elif current_tool == "save_vault_file":
            fn = (tool_args or {}).get("filename", "")
            return f"sedang menyimpan file '{fn}' ke brankas dokumen" if fn else "sedang menyimpan dokumen ke brankas"
        elif current_tool == "delete_vault_files":
            t = (tool_args or {}).get("target", "")
            return f"sedang menghapus file '{t}' dari brankas dokumen" if t else "sedang menghapus file dari brankas"
        elif current_tool == "move_vault_files":
            t = (tool_args or {}).get("target", "")
            dest = (tool_args or {}).get("destination_directory", "")
            return f"sedang memindahkan file '{t}' ke folder '{dest}'" if (t and dest) else "sedang merapikan dan memindahkan file di brankas"
        elif current_tool == "send_vault_file":
            fn = (tool_args or {}).get("file_id_or_name", "")
            return f"sedang mengambil dan menyiapkan file '{fn}' untuk dikirim" if fn else "sedang menyiapkan pengiriman file"
        elif current_tool == "search_web":
            q = (tool_args or {}).get("query", "")
            return f"sedang mencari informasi di web tentang '{q}'" if q else "sedang mencari informasi di internet"
        elif current_tool in ("add_task", "update_task", "complete_task", "delete_task"):
            title = (tool_args or {}).get("title", "")
            return f"sedang memperbarui catatan tugas '{title}'" if title else "sedang memperbarui daftar tugas"
        elif current_tool == "send_whatsapp_message":
            rec = (tool_args or {}).get("recipient", "")
            return f"sedang meneruskan pesan ke {rec}" if rec else "sedang mengirimkan pesan WhatsApp"

    # Inferred from user input / media context
    t_lower = text.lower()
    if is_voice_note:
        return "sedang mendengarkan dan mentranskripsi pesan suara kamu"
    if has_media or media_data:
        mime = (media_data or {}).get("mimeType", "")
        if "pdf" in mime or "document" in mime or "pdf" in t_lower:
            return "sedang membaca dan memproses dokumen PDF yang kamu kirim"
        elif "image" in mime or "foto" in t_lower or "gambar" in t_lower:
            return "sedang menganalisis gambar yang kamu kirim"
        elif "video" in mime or "video" in t_lower:
            return "sedang menganalisis video yang kamu kirim"

    if any(w in t_lower for w in ("hapus", "apus", "delete", "buang")):
        return "sedang mengecek brankas untuk menghapus file yang dimaksud"
    elif any(w in t_lower for w in ("simpen", "save", "taruh", "arsip")):
        return "sedang memproses penyimpanan file ke brankas"
    elif any(w in t_lower for w in ("kirim", "send", "bagi", "minta")):
        return "sedang mencari dan menyiapkan file yang kamu minta"
    elif any(w in t_lower for w in ("cari", "search", "cek harga", "googling", "info")):
        return "sedang mencari informasi dan data terkait"
    elif any(w in t_lower for w in ("ingetin", "jadwal", "tugas", "reminder", "deadline")):
        return "sedang mengecek jadwal dan menyusun pengingat"

    return "sedang menganalisis pesan dan menyiapkan jawabannya"


def split_into_bubbles(text: str) -> list[str]:
    """
    Split an assistant reply into natural human WhatsApp message bubbles.
    - If explicit '---' separator is used, split into separate message bubbles.
    - If text contains multiple conversational paragraphs ('\n\n'), split each conversational paragraph into its own bubble.
    - Preserves structured lists (e.g. header + numbered bullets), code blocks, and single cohesive notes in a single bubble.
    """
    if not text or not text.strip():
        return []

    clean = text.strip()

    # 1. Explicit bubble separator
    if "\n---\n" in clean or "\n--- \n" in clean:
        parts = [p.strip() for p in re.split(r"\n---(?:\s*)\n", clean) if p.strip()]
        if parts:
            return parts[:5]

    # 2. Keep single code blocks in 1 bubble
    if clean.startswith("```") and clean.endswith("```"):
        return [clean]

    # 3. Split by paragraphs (\n\n)
    paragraphs = [p.strip() for p in clean.split("\n\n") if p.strip()]
    if len(paragraphs) <= 1:
        return [clean]

    bubbles: list[str] = []
    current_bubble: list[str] = []

    for p in paragraphs:
        lines = p.splitlines()
        # Check if p is a structured list (numbered 1., 2. or bullets -, *, •)
        is_list = any(
            line.strip().startswith(tuple(f"{i}." for i in range(1, 20)))
            or line.strip().startswith(("- ", "* ", "• "))
            for line in lines
        )

        if is_list:
            # If there's a short intro header before this list (e.g. "Daftar tugas:"), group them into 1 bubble
            if (
                current_bubble
                and len(current_bubble) == 1
                and len(current_bubble[0]) < 120
                and not any(
                    current_bubble[0].strip().startswith(tuple(f"{i}." for i in range(1, 20)))
                    for line in current_bubble[0].splitlines()
                )
            ):
                current_bubble.append(p)
                bubbles.append("\n\n".join(current_bubble))
                current_bubble = []
            else:
                if current_bubble:
                    bubbles.append("\n\n".join(current_bubble))
                    current_bubble = []
                bubbles.append(p)
        else:
            # Conversational paragraph
            if current_bubble:
                bubbles.append("\n\n".join(current_bubble))
                current_bubble = []
            current_bubble.append(p)

    if current_bubble:
        bubbles.append("\n\n".join(current_bubble))

    return bubbles[:5] if bubbles else [clean]


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
            elif e.quoted_type == "video":
                quoted_desc = f'Video{": " + quoted_desc if quoted_desc and quoted_desc != "Video" else ""}'
            elif e.quoted_type == "image":
                quoted_desc = f'Foto / Gambar{": " + quoted_desc if quoted_desc and quoted_desc != "Foto / Gambar" else ""}'
            elif e.quoted_type == "document":
                quoted_desc = f'Dokumen{": " + quoted_desc if quoted_desc and quoted_desc != "Dokumen" else ""}'
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

        turn_state: dict[str, Any] = {"current_tool": None, "tool_args": None}

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

            # If no direct media was attached, check if a quoted or recent media message was referenced
            if not media_data:
                quoted_media_event = next(
                    (
                        e
                        for e in reversed(batch)
                        if e.quoted_type in ("image", "video", "document")
                        or e.quoted_media_url
                        or e.quoted_stanza_id
                    ),
                    None,
                )
                target_url: str | None = None
                media_type_label: str = "media"
                if quoted_media_event:
                    media_type_label = quoted_media_event.quoted_type or "media"
                    target_url = quoted_media_event.quoted_media_url
                    if not target_url:
                        try:
                            recent_msgs = await client.get_messages(chat_id=from_user, limit=12)
                            target_msg = None
                            if quoted_media_event.quoted_stanza_id:
                                target_msg = next(
                                    (
                                        m
                                        for m in recent_msgs
                                        if quoted_media_event.quoted_stanza_id in str(m.message_id)
                                    ),
                                    None,
                                )
                            if not target_msg:
                                target_msg = next(
                                    (m for m in reversed(recent_msgs) if m.media_url), None
                                )
                            if target_msg and target_msg.media_url:
                                target_url = target_msg.media_url
                        except Exception as ex:
                            log.warning("Could not resolve quoted media from chat history: %s", ex)
                else:
                    # Contextual follow-up fallback: if user text refers to recent media ("di video ini?", "itu motor apa?")
                    text_lower = combined_text.lower()
                    if any(
                        kw in text_lower
                        for kw in (
                            "video",
                            "foto",
                            "gambar",
                            "dokumen",
                            "ini",
                            "itu",
                            "motor",
                            "mobil",
                            "plat",
                            "orang",
                            "suara",
                        )
                    ):
                        try:
                            recent_msgs = await client.get_messages(chat_id=from_user, limit=6)
                            recent_media_msg = next(
                                (m for m in reversed(recent_msgs) if m.media_url), None
                            )
                            if recent_media_msg and recent_media_msg.media_url:
                                target_url = recent_media_msg.media_url
                                media_type_label = "contextual_recent"
                        except Exception as ex:
                            log.warning(
                                "Could not resolve recent media for contextual follow-up: %s", ex
                            )

                if target_url:
                    try:
                        q_media_res = await client.download_media_base64(target_url)
                        if q_media_res:
                            q_mime, q_b64 = q_media_res
                            if not q_mime.startswith("audio/"):
                                media_data = {"mimeType": q_mime, "data": q_b64}
                                log.info(
                                    "Attached %s (%s) to turn context",
                                    media_type_label,
                                    q_mime,
                                )
                    except Exception as ex:
                        log.warning("Could not download media %s: %s", target_url, ex)

            # Watchdog task: if agent is taking > 7.5 seconds (genuinely stuck or deep research), send reassurance
            async def progress_watchdog() -> None:
                try:
                    await asyncio.sleep(7.5)
                    # Don't fire if items were already dispatched to the chat or turn finished
                    if turn_state.get("dispatched_items", 0) > 0:
                        return
                    action_desc = describe_intent_action(
                        text=combined_text,
                        has_media=has_media,
                        media_data=media_data,
                        is_voice_note=is_voice_note,
                        current_tool=turn_state.get("current_tool"),
                        tool_args=turn_state.get("tool_args"),
                    )
                    log.info("Agent turn taking >7.5s for [%s]: %s", sender_name, action_desc)
                    await client.start_typing(chat_id=from_user)
                    reassurance_msg = f"Sebentar ya, {action_desc}..."
                    await client.send_message(chat_id=from_user, text=reassurance_msg)
                except asyncio.CancelledError:
                    pass
                except Exception as ex:
                    log.debug("Progress watchdog error: %s", ex)

            watchdog_task = asyncio.create_task(progress_watchdog())
            try:
                # Phase 2: Run autonomous agent loop on verified text/media
                reply_text = await run_agentic_react_loop(
                    client=client,
                    sender_name=sender_name,
                    chat_id=from_user,
                    message_text=combined_text,
                    media_data=media_data,
                    max_steps=12,
                    tracer=tracer,
                    turn_state=turn_state,
                )
            finally:
                watchdog_task.cancel()

            final_text: str | None = None
            if reply_text and reply_text.strip() not in ("[NO_REPLY]", "NO_REPLY", "None"):
                clean_reply = reply_text.strip()
                for prefix in ("[Helmis]:", "[Helmis]: ", "[Gilang]:", "[Gilang]: ", "[Bunga]:", "[Bunga]: "):
                    if clean_reply.startswith(prefix):
                        clean_reply = clean_reply[len(prefix):].strip()

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
                bubbles = split_into_bubbles(final_text)
                for idx, bubble in enumerate(bubbles):
                    if idx > 0:
                        # Simulate natural human typing pause between bubbles
                        await client.start_typing(chat_id=from_user)
                        await asyncio.sleep(0.4)
                    await client.send_message(
                        chat_id=from_user,
                        text=bubble,
                        reply_to_message_id=reply_id if (idx == 0 and has_media and reply_id) else None,
                    )
                log.debug("Sent %d verified bubble(s) to [%s] in %s", len(bubbles), sender_name, from_user)

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
        except Exception as err:
            log.exception("Unhandled error processing turn for [%s]: %s", sender_name, err)
            fallback_err = "Maaf, sempat terjadi kendala teknis saat memproses pesan ini. Boleh tolong ulangi lagi?"
            try:
                await client.send_message(chat_id=from_user, text=fallback_err)
            except Exception:
                pass
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
            clean_author = author.split("@")[0].split(":")[0].replace("+", "").replace(" ", "").replace("-", "")
            clean_from = from_user.split("@")[0].split(":")[0].replace("+", "").replace(" ", "").replace("-", "")
            notify_name = str(
                payload.get("_data", {}).get("notifyName") or payload.get("notifyName") or ""
            )

            # STRICT AUTHORIZATION: Only Gilang or Bunga are authorized
            sender_name: str | None = None
            if (
                (bool(GILANG_PHONE) and (clean_from == GILANG_PHONE or clean_author == GILANG_PHONE))
                or (bool(GILANG_LID) and (clean_from.startswith(GILANG_LID) or clean_author.startswith(GILANG_LID)))
                or "gilang" in notify_name.lower()
            ):
                sender_name = "Gilang"
            elif (
                (bool(BUNGA_PHONE) and (clean_from == BUNGA_PHONE or clean_author == BUNGA_PHONE))
                or (bool(BUNGA_LID) and (clean_from.startswith(BUNGA_LID) or clean_author.startswith(BUNGA_LID)))
                or "bunga" in notify_name.lower()
            ):
                sender_name = "Bunga"

            log.info("Webhook message from=%s (clean_from=%s) author=%s (clean_author=%s) resolved_sender=%s text=%r", from_user, clean_from, author, clean_author, sender_name, text[:40])

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
                    quoted_stanza_id=quoted_stanza_id,
                )
            )
            return JSONResponse({"status": "queued", "sender": sender_name, "chat_id": from_user})

        # Scheduler tick
        elif event == "scheduler.tick":
            log.info("Received scheduler proactive tick, evaluating due tasks...")
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
