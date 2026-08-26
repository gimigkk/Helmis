"""
history.py — Message deduplication and chronological multi-turn history builder.
"""

import logging
import os
import time
from typing import Any

log = logging.getLogger("helmis-history")

BOT_PHONE = (
    os.environ.get("BOT_PHONE", "").replace("+", "").replace(" ", "").replace("-", "")
)

# In-memory message deduplication cache (msg_id -> timestamp)
_seen_message_ids: dict[str, float] = {}


def is_duplicate_message(msg_id: str | None) -> bool:
    """Return True if message was already received in the last 60 seconds."""
    if not msg_id:
        return False
    now = time.time()
    for k in list(_seen_message_ids.keys()):
        if now - _seen_message_ids[k] > 60:
            del _seen_message_ids[k]
    if msg_id in _seen_message_ids:
        return True
    _seen_message_ids[msg_id] = now
    return False


def build_multi_turn_contents(
    history_messages: list[Any],
    sender_name: str,
    current_text: str,
    media_data: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """
    Format recent chat history into chronological alternating user/model contents for Gemini.
    Properly handles multimodal media data without injecting synthetic prompt strings.
    """
    contents: list[dict[str, Any]] = []

    # Sort messages chronologically (oldest to newest)
    sorted_history = sorted(history_messages, key=lambda m: getattr(m, "timestamp", 0))

    # Take up to the last 10 chronological messages
    for msg in sorted_history[-10:]:
        text = msg.text
        if not text:
            continue
        if text.strip() == current_text.strip() and not str(msg.message_id).startswith("true_"):
            continue

        msg_sender = getattr(msg, "sender_name", None)
        is_bot = (
            str(msg.message_id).startswith("true_")
            or getattr(msg, "from_me", False) is True
            or msg_sender == "Helmis"
            or (bool(BOT_PHONE) and BOT_PHONE in str(getattr(msg, "sender_phone", "")))
        )
        role = "model" if is_bot else "user"
        effective_sender = "Helmis" if is_bot else (msg_sender or sender_name)
        content_text = text.strip() if role == "model" else f"[{effective_sender}]: {text.strip()}"

        if contents and contents[-1]["role"] == role:
            contents[-1]["parts"][0]["text"] += f"\n{content_text}"
        else:
            contents.append({"role": role, "parts": [{"text": content_text}]})

    # Prepare current turn parts natively
    current_parts: list[dict[str, Any]] = []
    if media_data:
        current_parts.append({"inlineData": media_data})

    if current_text and current_text.strip():
        current_parts.append({"text": f"[{sender_name}]: {current_text.strip()}"})
    elif not media_data:
        current_parts.append({"text": f"[{sender_name}]: ..."})

    if contents and contents[-1]["role"] == "user":
        if (
            len(current_parts) == 1
            and "text" in current_parts[0]
            and "text" in contents[-1]["parts"][-1]
        ):
            contents[-1]["parts"][-1]["text"] += f"\n{current_parts[0]['text']}"
        else:
            contents[-1]["parts"].extend(current_parts)
    else:
        contents.append({"role": "user", "parts": current_parts})

    return contents
