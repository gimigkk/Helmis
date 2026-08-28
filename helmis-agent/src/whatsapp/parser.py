"""
parser.py — WAHA Webhook Payload and Quoted Message Normalizer.
Extracts media filenames, reply-to quotes, and sender identities across all WAHA engines (GOWS, NOWEB, WEBJS).
"""

import logging
import os
import re
from typing import Any

log = logging.getLogger("helmis-whatsapp-parser")

OWNER_NAME = os.environ.get("OWNER_NAME", "Gilang").strip() or "Gilang"
PARTNER_NAME = os.environ.get("PARTNER_NAME", "Bunga").strip() or "Bunga"

OWNER_PHONE = (
    (os.environ.get("OWNER_PHONE") or os.environ.get("GILANG_PHONE", ""))
    .replace("+", "")
    .replace(" ", "")
    .replace("-", "")
)
GILANG_PHONE = OWNER_PHONE

PARTNER_PHONE = (
    (os.environ.get("PARTNER_PHONE") or os.environ.get("BUNGA_PHONE", ""))
    .replace("+", "")
    .replace(" ", "")
    .replace("-", "")
)
BUNGA_PHONE = PARTNER_PHONE

BOT_PHONE = (
    os.environ.get("BOT_PHONE", "").replace("+", "").replace(" ", "").replace("-", "")
)
OWNER_LID = (
    (os.environ.get("OWNER_LID") or os.environ.get("GILANG_LID") or "217188174717173")
    .replace("+", "").replace(" ", "").replace("-", "").split("@")[0].split(":")[0]
)
GILANG_LID = OWNER_LID

PARTNER_LID = (
    (os.environ.get("PARTNER_LID") or os.environ.get("BUNGA_LID") or "279821464654020")
    .replace("+", "").replace(" ", "").replace("-", "").split("@")[0].split(":")[0]
)
BUNGA_LID = PARTNER_LID

TRIO_GROUP_JID = os.environ.get("TRIO_GROUP_JID", "")
ALLOWED_CHATS = set(
    filter(
        None,
        [
            f"{OWNER_PHONE}@c.us" if OWNER_PHONE else None,
            f"{PARTNER_PHONE}@c.us" if PARTNER_PHONE else None,
            TRIO_GROUP_JID if TRIO_GROUP_JID else None,
            f"{OWNER_LID}@lid" if OWNER_LID else None,
            f"{PARTNER_LID}@lid" if PARTNER_LID else None,
            "217188174717173@lid",
            "279821464654020@lid",
        ],
    )
)


def resolve_sender_identity(from_user: str, author: str = "", notify_name: str = "") -> str | None:
    """Resolve whether sender is Owner or Partner based on phone number, LID, or notifyName."""
    clean_author = author.split("@")[0].split(":")[0].replace("+", "").replace(" ", "").replace("-", "")
    clean_from = from_user.split("@")[0].split(":")[0].replace("+", "").replace(" ", "").replace("-", "")

    import sys
    g_phone = globals().get("OWNER_PHONE") or globals().get("GILANG_PHONE") or os.environ.get("OWNER_PHONE") or os.environ.get("GILANG_PHONE", "")
    b_phone = globals().get("PARTNER_PHONE") or globals().get("BUNGA_PHONE") or os.environ.get("PARTNER_PHONE") or os.environ.get("BUNGA_PHONE", "")
    g_lid = globals().get("OWNER_LID") or globals().get("GILANG_LID") or os.environ.get("OWNER_LID") or os.environ.get("GILANG_LID", "217188174717173")
    b_lid = globals().get("PARTNER_LID") or globals().get("BUNGA_LID") or os.environ.get("PARTNER_LID") or os.environ.get("BUNGA_LID", "279821464654020")
    g_name = globals().get("OWNER_NAME") or os.environ.get("OWNER_NAME", "Gilang")
    b_name = globals().get("PARTNER_NAME") or os.environ.get("PARTNER_NAME", "Bunga")

    for mod_name in ("src.webhook", "src.whatsapp.webhook", "src.whatsapp.parser"):
        if mod_name in sys.modules:
            mod = sys.modules[mod_name]
            g_phone = getattr(mod, "OWNER_PHONE", None) or getattr(mod, "GILANG_PHONE", g_phone) or g_phone
            b_phone = getattr(mod, "PARTNER_PHONE", None) or getattr(mod, "BUNGA_PHONE", b_phone) or b_phone
            g_lid = getattr(mod, "OWNER_LID", None) or getattr(mod, "GILANG_LID", g_lid) or g_lid
            b_lid = getattr(mod, "PARTNER_LID", None) or getattr(mod, "BUNGA_LID", b_lid) or b_lid

    g_clean = str(g_phone).replace("+", "").replace(" ", "").replace("-", "")
    b_clean = str(b_phone).replace("+", "").replace(" ", "").replace("-", "")
    g_lid_clean = str(g_lid).replace("+", "").replace(" ", "").replace("-", "").split("@")[0].split(":")[0]
    b_lid_clean = str(b_lid).replace("+", "").replace(" ", "").replace("-", "").split("@")[0].split(":")[0]

    if (
        (bool(g_clean) and (clean_from == g_clean or clean_author == g_clean))
        or (bool(g_lid_clean) and (clean_from.startswith(g_lid_clean) or clean_author.startswith(g_lid_clean)))
        or g_name.lower() in notify_name.lower()
        or "gilang" in notify_name.lower()
    ):
        return g_name
    elif (
        (bool(b_clean) and (clean_from == b_clean or clean_author == b_clean))
        or (bool(b_lid_clean) and (clean_from.startswith(b_lid_clean) or clean_author.startswith(b_lid_clean)))
        or b_name.lower() in notify_name.lower()
        or "bunga" in notify_name.lower()
    ):
        return b_name

    return None


def extract_media_filename(payload: dict[str, Any]) -> str | None:
    """
    Extract original media / document filename from WAHA payloads across all engines (GOWS, NOWEB, WEBJS).
    Checks media.filename, top-level filename/fileName, _data.filename/_data.title, and Protobuf documentMessage.fileName/title.
    """
    # 1. media object
    media_obj = payload.get("media") if isinstance(payload.get("media"), dict) else {}
    if media_obj:
        fn = media_obj.get("filename") or media_obj.get("fileName")
        if fn and str(fn).strip():
            return str(fn).strip()

    # 2. top-level payload attributes
    for key in ("filename", "fileName", "title"):
        val = payload.get(key)
        if val and isinstance(val, str) and val.strip():
            return val.strip()

    # 3. _data container
    _data_raw = payload.get("_data")
    _data: dict[str, Any] = _data_raw if isinstance(_data_raw, dict) else {}
    for key in ("filename", "fileName", "title"):
        val = _data.get(key)
        if val and isinstance(val, str) and val.strip():
            return val.strip()

    # 4. GOWS Protobuf message structure (_data.Message.documentMessage)
    msg_raw = _data.get("Message")
    msg_obj: dict[str, Any] = msg_raw if isinstance(msg_raw, dict) else {}
    doc_raw = msg_obj.get("documentMessage")
    if isinstance(doc_raw, dict):
        fn = doc_raw.get("fileName") or doc_raw.get("title")
        if fn and str(fn).strip():
            return str(fn).strip()

    # 5. Check if body or caption is a clean single-line filename with standard document extension
    body = str(payload.get("body") or "").strip()
    if body and re.search(r"\.(pdf|docx?|xlsx?|pptx?|zip|csv|txt|jpe?g|png|webp|bin)$", body, re.IGNORECASE):
        if "\n" not in body and len(body) <= 120 and "/" not in body:
            return body

    return None


def extract_quoted_info(
    payload: dict[str, Any],
) -> tuple[str | None, str | None, str | None, str | None, str | None, str | None, str | None]:
    """
    Extract quoted / replied message metadata from WAHA payloads across all engines (GOWS, NOWEB, WEBJS).
    Returns (quoted_text, quoted_sender, quoted_type, quoted_media_url, quoted_media_type, quoted_stanza_id, quoted_media_filename).
    """
    quoted_text: str | None = None
    quoted_sender: str | None = None
    quoted_type: str | None = None
    quoted_media_url: str | None = None
    quoted_media_type: str | None = None
    quoted_stanza_id: str | None = None
    quoted_media_filename: str | None = None

    def resolve_sender(participant: str, from_me: bool) -> str:
        if from_me:
            return "Helmis"
        resolved = resolve_sender_identity(participant, participant)
        if resolved:
            return resolved
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
            fn = media_obj.get("filename") or media_obj.get("fileName")
            if fn:
                quoted_media_filename = str(fn).strip()
        if not quoted_media_filename:
            for k in ("filename", "fileName", "title"):
                if reply_to.get(k):
                    quoted_media_filename = str(reply_to[k]).strip()
                    break
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
            if not quoted_media_filename:
                for k in ("filename", "fileName", "title"):
                    if data_quoted.get(k):
                        quoted_media_filename = str(data_quoted[k]).strip()
                        break
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
                doc_title = doc.get("fileName") or doc.get("title")
                quoted_type = "document"
                if doc_title:
                    quoted_media_filename = str(doc_title).strip()
                    quoted_text = f'Dokumen: "{quoted_media_filename}"'
                else:
                    quoted_text = "Dokumen"
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
            quoted_text = f'Dokumen: "{quoted_media_filename}"' if quoted_media_filename else "Dokumen"
        elif quoted_type == "sticker":
            quoted_text = "Stiker"

    return (
        quoted_text,
        quoted_sender,
        quoted_type,
        quoted_media_url,
        quoted_media_type,
        quoted_stanza_id,
        quoted_media_filename,
    )
