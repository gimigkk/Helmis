"""
policy.py — Explicit group/identity admission policy for WhatsApp ingestion.

Centralizes the group-chat admission rules that were previously inline in the
webhook handler so they are deterministic and testable:
- which payloads count as addressing the bot (quote, name, trigger prefix,
  @mention, phone in mention list),
- which group messages are directed at another human and must be ignored so
the agent does not interrupt human banter.

Response status strings mirror the webhook's existing observability contract.
"""

from __future__ import annotations

import re
from typing import Any

_HELMIS_NAME = "helmis"
_TRIGGER_PREFIX = "mis"


def clean_phone(value: str) -> str:
    """Normalize a phone/LID value to bare digits."""
    return str(value or "").replace("+", "").replace(" ", "").replace("-", "")


def extract_mentioned_ids(payload: dict[str, Any]) -> list[str]:
    """Normalize mention lists across WAHA engines (GOWS/NOWEB/WEBJS)."""
    _data = payload.get("_data") if isinstance(payload.get("_data"), dict) else {}
    raw = (
        payload.get("mentionedIds")
        or payload.get("mentions")
        or payload.get("mentionedJidList")
        or _data.get("mentionedJidList")
        or _data.get("mentions")
        or []
    )
    if isinstance(raw, str):
        return [raw]
    return [str(item) for item in raw]


def mentions_bot(
    text: str,
    mentioned_ids: list[str],
    *,
    bot_phone: str,
    quoted_sender: str | None = None,
) -> bool:
    """Did this group message summon the bot?"""
    text_lower = text.lower()
    bot_clean = clean_phone(bot_phone)
    is_quoting_bot = quoted_sender == "Helmis"
    has_bot_mention = (
        is_quoting_bot
        or _HELMIS_NAME in text_lower
        or text_lower.startswith(f"{_TRIGGER_PREFIX} ")
        or text_lower.startswith(f"{_TRIGGER_PREFIX},")
        or text_lower.startswith(f"{_TRIGGER_PREFIX}?")
        or f"@{_HELMIS_NAME}" in text_lower
        or (bool(bot_clean) and any(bot_clean in mid for mid in mentioned_ids))
    )
    return has_bot_mention


def mentions_other_human(
    text: str,
    mentioned_ids: list[str],
    *,
    owner_phone: str,
    partner_phone: str,
    has_bot_mention: bool,
) -> bool:
    """Is this group message explicitly directed at the other human?"""
    text_lower = text.lower()
    owner_clean = clean_phone(owner_phone)
    partner_clean = clean_phone(partner_phone)
    mentions_human = any(
        (bool(owner_clean) and owner_clean in mid) or (bool(partner_clean) and partner_clean in mid)
        for mid in mentioned_ids
    ) or (
        "@bunga" in text_lower
        or "@gilang" in text_lower
        or (bool(owner_clean) and f"@{owner_clean}" in text_lower)
        or (bool(partner_clean) and f"@{partner_clean}" in text_lower)
    )
    return mentions_human and not has_bot_mention


def decide_group_admission(
    text: str,
    payload: dict[str, Any],
    *,
    bot_phone: str,
    owner_phone: str,
    partner_phone: str,
    quoted_sender: str | None = None,
) -> str:
    """Admission decision for a whitelisted group message.

    Returns the webhook status string: ``queued`` when the bot should answer,
    ``ignored_directed_to_other`` when the message targets another human.
    """
    mentioned_ids = extract_mentioned_ids(payload)
    has_bot_mention = mentions_bot(
        text, mentioned_ids, bot_phone=bot_phone, quoted_sender=quoted_sender
    )
    if mentions_other_human(
        text,
        mentioned_ids,
        owner_phone=owner_phone,
        partner_phone=partner_phone,
        has_bot_mention=has_bot_mention,
    ):
        return "ignored_directed_to_other"
    return "queued"


def is_group_chat(from_user: str) -> bool:
    """WhatsApp group chats end with @g.us."""
    return bool(from_user) and from_user.strip().endswith("@g.us")


_GROUP_JID_PATTERN = re.compile(r"^[^@\s]+@g\.us$", re.IGNORECASE)


def is_valid_group_jid(from_user: str) -> bool:
    """Strict group JID shape check (used for allowlist comparisons)."""
    return bool(_GROUP_JID_PATTERN.match((from_user or "").strip()))
