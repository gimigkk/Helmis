"""
whatsapp.py — Tool Handlers for WhatsApp Messaging, Media, and Chat History Inspection.
"""

import logging
import os
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from ..client import WahaClient
from ..memory import log_activity
from .registry import register_tool

log = logging.getLogger("helmis-tools-whatsapp")


def _resolve_target_jid(recipient: str, default_sender: str) -> str:
    gilang_phone = (
        os.environ.get("GILANG_PHONE", "")
        .replace("+", "")
        .replace(" ", "")
        .replace("-", "")
    )
    bunga_phone = (
        os.environ.get("BUNGA_PHONE", "")
        .replace("+", "")
        .replace(" ", "")
        .replace("-", "")
    )
    trio_group = os.environ.get("TRIO_GROUP_JID", "")

    recip_lower = recipient.lower()
    if "bunga" in recip_lower:
        return f"{bunga_phone}@c.us"
    elif "gilang" in recip_lower:
        return f"{gilang_phone}@c.us"
    elif "group" in recip_lower or "trio" in recip_lower:
        return trio_group
    elif recip_lower in ("current", "me", "sender", "self", ""):
        return f"{bunga_phone}@c.us" if "bunga" in default_sender.lower() else f"{gilang_phone}@c.us"
    else:
        clean = recipient.replace("+", "").replace(" ", "").replace("-", "")
        return f"{clean}@c.us"


@register_tool("send_whatsapp_message")
async def handle_send_whatsapp_message(
    args: dict[str, Any],
    default_sender: str,
    client: WahaClient | None = None,
) -> dict[str, Any]:
    recipient = str(args.get("recipient", "")).strip()
    text = str(args.get("text", "")).strip()
    if not text:
        return {"status": "error", "error": "Teks pesan tidak boleh kosong."}
    if not client:
        return {"status": "error", "error": "WAHA client tidak tersedia."}

    target_jid = _resolve_target_jid(recipient, default_sender)
    quote_id = args.get("quote_message_id")
    if quote_id:
        quote_id = str(quote_id).strip()

    await client.send_message(chat_id=target_jid, text=text, reply_to_message_id=quote_id)
    log_activity(f'Direct message sent to {recipient} ({target_jid}): "{text}"')
    log.info(
        "Agent sent direct WhatsApp message to %s (quote: %s): %s",
        target_jid,
        quote_id,
        text[:40],
    )
    return {
        "status": "success",
        "recipient": recipient,
        "message": f"Pesan WhatsApp berhasil dikirim ke {recipient}.",
    }


@register_tool("send_status_update")
async def handle_send_status_update(
    args: dict[str, Any],
    default_sender: str,
    client: WahaClient | None = None,
) -> dict[str, Any]:
    text = str(args.get("text", "")).strip()
    if not text:
        return {"status": "error", "error": "Teks status update tidak boleh kosong."}
    if not client:
        return {"status": "error", "error": "WAHA client tidak tersedia."}

    target_jid = _resolve_target_jid("current", default_sender)
    await client.send_message(chat_id=target_jid, text=text)
    await client.start_typing(chat_id=target_jid)

    log_activity(f'Status update sent to {default_sender} ({target_jid}): "{text}"')
    log.info("Agent sent status update to %s: %s", target_jid, text[:40])
    return {
        "status": "success",
        "message": "Status update terkirim ke WhatsApp. Sekarang lanjutkan dengan eksekusi tool atau sintesis akhir.",
    }


@register_tool("send_whatsapp_media")
async def handle_send_whatsapp_media(
    args: dict[str, Any],
    default_sender: str,
    client: WahaClient | None = None,
) -> dict[str, Any]:
    recipient = str(args.get("recipient", "")).strip()
    media_url = str(args.get("media_url", "")).strip()
    caption = args.get("caption")
    if not media_url:
        return {"status": "error", "error": "URL media tidak boleh kosong."}
    if not client:
        return {"status": "error", "error": "WAHA client tidak tersedia."}

    target_jid = _resolve_target_jid(recipient, default_sender)
    await client.send_media(chat_id=target_jid, media_url=media_url, caption=caption)
    log_activity(f'Media sent to {recipient} ({target_jid}): url={media_url} caption="{caption or ""}"')
    log.info("Agent sent media to %s: %s (caption: %s)", target_jid, media_url, caption)
    return {
        "status": "success",
        "recipient": recipient,
        "message": f"Media berhasil dikirim ke WhatsApp {recipient}.",
    }


@register_tool("get_whatsapp_messages")
async def handle_get_whatsapp_messages(
    args: dict[str, Any],
    client: WahaClient | None = None,
) -> dict[str, Any]:
    target = str(args.get("target", "")).strip()
    limit = int(args.get("limit") or 20)
    date_filter = str(args.get("date", "")).strip().lower() if args.get("date") else None
    since_hours_ago = (
        int(args["since_hours_ago"]) if args.get("since_hours_ago") is not None else None
    )

    if not client:
        return {"status": "error", "error": "WAHA client tidak tersedia."}

    target_jid = _resolve_target_jid(target, default_sender=target)
    tz = ZoneInfo(os.environ.get("TZ", "Asia/Jakarta"))
    now_dt = datetime.now(tz)
    min_ts = None
    max_ts = None

    if since_hours_ago:
        min_ts = (now_dt - timedelta(hours=since_hours_ago)).timestamp()
    elif date_filter:
        if date_filter in ("today", "hari ini"):
            target_day = now_dt.date()
        elif date_filter in ("yesterday", "kemarin"):
            target_day = (now_dt - timedelta(days=1)).date()
        else:
            try:
                target_day = datetime.strptime(date_filter, "%Y-%m-%d").date()
            except Exception:
                target_day = None

        if target_day:
            start_dt = datetime(
                target_day.year, target_day.month, target_day.day, 0, 0, 0, tzinfo=tz
            )
            end_dt = datetime(
                target_day.year, target_day.month, target_day.day, 23, 59, 59, tzinfo=tz
            )
            min_ts = start_dt.timestamp()
            max_ts = end_dt.timestamp()

    fetch_limit = max(min(limit * 2 if (min_ts or max_ts) else limit, 50), 10)
    msgs = await client.get_messages(chat_id=target_jid, limit=fetch_limit)

    formatted_msgs = []
    for m in msgs:
        ts = m.timestamp
        if min_ts and ts < min_ts:
            continue
        if max_ts and ts > max_ts:
            continue
        msg_time_str = (
            datetime.fromtimestamp(ts, tz=tz).strftime("%Y-%m-%d %H:%M WIB")
            if ts
            else "Waktu tidak diketahui"
        )
        formatted_msgs.append(
            {
                "id": m.message_id,
                "from": m.sender_phone,
                "text": m.text,
                "media_url": m.media_url,
                "quoted_text": m.quoted_text,
                "time": msg_time_str,
                "timestamp": ts,
            }
        )
    return {
        "status": "success",
        "target": target,
        "chat_id": target_jid,
        "filter_applied": {"date": date_filter, "since_hours_ago": since_hours_ago},
        "count": len(formatted_msgs),
        "messages": formatted_msgs[:limit],
    }
