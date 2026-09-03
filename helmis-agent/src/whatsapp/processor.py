"""
processor.py — Turn Orchestration, Watchdog Monitoring, and WhatsApp Bubble Dispatching.
"""

import asyncio
import logging
import re
from typing import Any

from ..agent.loop import run_agentic_react_loop
from ..agent.tracer import AgentTurnTracer
from ..memory import extract_facts_from_turn_background
from .client import WahaClient
from .queue import IncomingMessageEvent
from .transcribe import transcribe_audio_base64

log = logging.getLogger("helmis-turn-processor")


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
        elif current_tool == "send_whatsapp_media":
            rec = (tool_args or {}).get("recipient", "")
            return f"sedang mengirim media ke {rec}" if rec else "sedang mengirim media WhatsApp"
        elif current_tool == "get_whatsapp_messages":
            return "sedang mengecek riwayat chat"
        elif current_tool in ("save_note", "append_to_note", "get_note", "list_notes", "delete_note"):
            title = (tool_args or {}).get("title", "")
            if title:
                return f"sedang membaca/memperbarui catatan '{title}'"
            return "sedang mengakses catatan"
        elif current_tool in ("remember_fact", "search_memory", "recall_memory", "correct_fact"):
            q = (tool_args or {}).get("fact", "") or (tool_args or {}).get("query", "")
            return f"sedang mengingat '{q}'" if q else "sedang mengakses memori jangka panjang"
        elif current_tool in ("list_tasks",):
            return "sedang mengecek daftar tugas"
        elif current_tool in ("web_search", "search_web", "read_url"):
            q = (tool_args or {}).get("query", "") or (tool_args or {}).get("url", "")
            return f"sedang membuka '{q}'" if q else "sedang mencari informasi di internet"
        elif current_tool in ("read_vault_file", "list_vault_files"):
            return "sedang membaca file dari brankas"
        elif current_tool == "process_pdf":
            return "sedang memproses dokumen PDF"
        elif current_tool in ("create_schedule", "list_schedules"):
            return "sedang mengatur jadwal"
        elif current_tool == "execute_code":
            return "sedang menghitung sesuatu di sandbox"

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
    Split an assistant reply into separate WhatsApp message bubbles based strictly on the '---' delimiter.
    - If the agent explicitly outputs '---' on its own line, split into separate message bubbles.
    - Preserves all multi-paragraph structures, multi-day schedules, lists, and markdown intact in a single bubble unless '---' is used.
    """
    if not text or not text.strip():
        return []

    clean = text.strip()

    # Split strictly on '---' delimiter on its own line (with optional surrounding whitespace)
    parts = [p.strip() for p in re.split(r"(?:\r?\n|^)\s*---\s*(?:\r?\n|$)", clean) if p.strip()]
    return parts[:5] if parts else [clean]


async def process_batched_turn(
    client: WahaClient,
    batch: list[IncomingMessageEvent],
    mailbox: asyncio.Queue[IncomingMessageEvent] | None = None,
) -> None:
    """Execute complete conversational turn for a batch of debounced WhatsApp messages."""
    if not batch:
        return

    last_event = batch[-1]
    sender_name = last_event.sender_name
    from_user = last_event.from_user
    reply_id = last_event.reply_id

    # Combine burst texts and quoted info
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

    # Preserve every burst media attachment: primary becomes inlineData,
    # additional ones are labeled in text so the model knows they exist.
    media_events = [e for e in batch if e.has_media and e.media_url]
    primary_media_event = media_events[-1] if media_events else None
    additional_media_labels = [
        f"[Lampiran Media: {e.media_filename or e.media_type or 'lampiran'}]"
        for e in media_events[:-1]
    ]
    if additional_media_labels:
        combined_text = f"{combined_text}\n\n{'\n'.join(additional_media_labels)}".strip()

    has_media = bool(media_events)
    media_event = primary_media_event
    media_url = media_event.media_url if media_event else None
    media_filename = media_event.media_filename if media_event else None
    if not media_filename:
        media_fn_event = next((e for e in reversed(batch) if e.media_filename), None)
        if media_fn_event:
            media_filename = media_fn_event.media_filename
    # Message IDs of the burst, for context provenance (never silently dropped)
    [e.reply_id for e in batch if e.reply_id]

    async def _safe_start_typing() -> None:
        try:
            await client.start_typing(chat_id=from_user)
        except Exception:
            pass

    asyncio.create_task(_safe_start_typing())

    tracer = AgentTurnTracer(
        sender_name=sender_name,
        chat_id=from_user,
        message_text=combined_text,
        has_media=has_media,
    )
    tracer.log_incoming()

    turn_state: dict[str, Any] = {"current_tool": None, "tool_args": None}

    # Keepalive typing status for long-running / multi-step steered turns.
    # Failures are caught *per ping* so one WAHA hiccup never kills typing
    # for the rest of the turn (previously the whole task died on first error).
    async def _keep_typing() -> None:
        while True:
            await asyncio.sleep(7.5)
            try:
                await client.start_typing(chat_id=from_user)
            except asyncio.CancelledError:
                raise
            except Exception:
                pass

    typing_keepalive_task = asyncio.create_task(_keep_typing())

    try:
        is_voice_note = False
        vn_transcript: str | None = None
        media_data: dict[str, Any] | None = None

        if has_media and media_url:
            media_res = await client.download_media_base64(media_url)
            if media_res:
                mime_type, b64_data = media_res
                if mime_type.startswith("audio/"):
                    is_voice_note = True
                    log.info("Phase 1: Running dedicated audio transcription for [%s]...", sender_name)
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
                    media_data = {"mimeType": mime_type, "data": b64_data, "filename": media_filename}

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
            quoted_doc_filename: str | None = None
            if quoted_media_event:
                media_type_label = quoted_media_event.quoted_type or "media"
                target_url = quoted_media_event.quoted_media_url
                quoted_doc_filename = quoted_media_event.quoted_media_filename
                if not target_url:
                    try:
                        recent_msgs = await client.get_messages(chat_id=from_user, limit=12)
                        target_msg = None
                        if quoted_media_event.quoted_stanza_id:
                            target_msg = next(
                                (
                                    m
                                    for m in recent_msgs
                                    if quoted_media_event.quoted_stanza_id in m.message_id
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
                # Contextual follow-up fallback: if user text explicitly refers to recent media (e.g. "di foto ini", "video tadi")
                text_lower = combined_text.lower()
                if any(
                    phrase in text_lower
                    for phrase in (
                        "foto ini",
                        "di foto",
                        "foto tadi",
                        "gambar ini",
                        "di gambar",
                        "gambar tadi",
                        "video ini",
                        "di video",
                        "video tadi",
                        "dokumen ini",
                        "file ini",
                        "dokumen tadi",
                        "file tadi",
                        "voice note tadi",
                        "audio tadi",
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
                            media_data = {
                                "mimeType": q_mime,
                                "data": q_b64,
                                "filename": quoted_doc_filename,
                            }
                            log.info(
                                "Attached %s (%s) to turn context",
                                media_type_label,
                                q_mime,
                            )
                except Exception as ex:
                    log.warning("Could not download media %s: %s", target_url, ex)

        # Prepend document label to prompt text if a named document was attached
        if media_data and media_data.get("filename") and not is_voice_note:
            attached_fn = media_data["filename"]
            doc_banner = f"[Dokumen Terlampir: {attached_fn}]"
            if doc_banner not in combined_text:
                combined_text = f"{doc_banner}\n\n{combined_text}" if combined_text else doc_banner
                tracer.message_text = combined_text

        # Dynamic Progress Watchdog: reassure at 12s, then every 30s while the
        # agent is still working. Long 503-storm turns previously went silent
        # after one message, looking like a crash. Every ping states WHAT the
        # agent is doing (current tool + key arg, or last completed tool while
        # it reasons) instead of generic filler.
        async def progress_watchdog() -> None:
            try:
                intervals = [12.0, 30.0, 30.0, 30.0, 30.0]
                elapsed = 0.0
                for interval in intervals:
                    await asyncio.sleep(interval)
                    elapsed += interval
                    if turn_state.get("dispatched_items", 0) > 0:
                        return
                    cur_tool = turn_state.get("current_tool")
                    last_done = turn_state.get("last_completed_tool")
                    if cur_tool:
                        # Model is mid-call on a specific tool — name it.
                        action_desc = describe_intent_action(
                            text=combined_text,
                            has_media=has_media,
                            media_data=media_data,
                            is_voice_note=is_voice_note,
                            current_tool=cur_tool,
                            tool_args=turn_state.get("tool_args"),
                        )
                        tail = f" ({int(elapsed)}s)" if elapsed > 15 else ""
                        reassurance_msg = f"_Helmis {action_desc}{tail}..._"
                    elif last_done:
                        # Between steps: the last finished tool tells the truth
                        # about progress without inventing an action.
                        reassurance_msg = (
                            f"_`{last_done}` selesai ({int(elapsed)}s), Helmis sedang menyusun langkah berikutnya..._"
                        )
                    else:
                        action_desc = describe_intent_action(
                            text=combined_text,
                            has_media=has_media,
                            media_data=media_data,
                            is_voice_note=is_voice_note,
                        )
                        reassurance_msg = f"Sebentar ya, {action_desc}..."

                    log.info("Agent turn taking >%.0fs for [%s]: %s", elapsed, sender_name, reassurance_msg)
                    await client.start_typing(chat_id=from_user)
                    await client.send_message(chat_id=from_user, text=reassurance_msg)
            except asyncio.CancelledError:
                pass
            except Exception as ex:
                log.debug("Progress watchdog error: %s", ex)

        watchdog_task = asyncio.create_task(progress_watchdog())
        try:
            # Phase 2: Run autonomous agent loop on verified text/media with mailbox steering
            reply_text = await run_agentic_react_loop(
                client=client,
                sender_name=sender_name,
                chat_id=from_user,
                message_text=combined_text,
                media_data=media_data,
                max_steps=12,
                tracer=tracer,
                turn_state=turn_state,
                mailbox=mailbox,
            )
        finally:
            watchdog_task.cancel()
            typing_keepalive_task.cancel()

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

            asyncio.create_task(
                extract_facts_from_turn_background(
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
