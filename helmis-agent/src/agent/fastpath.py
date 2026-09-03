"""
fastpath.py — Model-driven fast paths for trivial turns.

Latency comes from context, not intelligence. Chat turns use a tiny prompt;
the model still decides everything ([FALLBACK] escape hatch). Data queries
take the normal agent loop — model calls list_tasks (routine hidden by
default), model formats/filters as asked. No phrase whitelists, no
deterministic rendering of user-facing data.
"""

import logging
import re
from typing import Any

log = logging.getLogger("helmis-fastpath")

# Tiny persona: model decides, escape hatch preserves adaptability.
# {time_context} = live clock + exact greeting (no verbose hints).
_CHAT_SYSTEM_PROMPT = (
    "Kamu Helmis, sekretaris AI pribadi Gilang dan Bunga. "
    "{time_context} "
    "Balas santai, chill, singkat (1-2 kalimat), bahasa Indonesia kasual. "
    "Tanpa emoji. Proaktif seperlunya: kalau relevan, tawarkan bantuan "
    "satu kalimat singkat. "
    "Kalau pesan user berisi permintaan tindakan atau pertanyaan tentang data, "
    "balas hanya: [FALLBACK]"
)

# Casual chat: short interjections/greetings/thanks/acks only.
_CHAT_PATTERN = re.compile(
    r"^(?:"
    r"(?:halo+w?|hai+|hei+|hallo+|hello+|woi+|woy+|p+|ping+|bro|sis|bos+)"
    r"|selamat\s+(?:pagi|siang|sore|malam)"
    r"|met\s+(?:pagi|siang|sore|malam)"
    r"|pagi+|siang+|sore+|malam+"
    r"|(?:makasih|makasi|terima\s*kasih|thanks|thank\s*you|thx)"
    r"|(?:sip+|oke+|ok+|okey+|yes+|no+|nggak|ngga|gak|ga|iy+a+)"
    r"|(?:assalam(?:ualaikum)?|salam)"
    r"|(?:gt?|gitu|oh|hm+|hmm+|hehe|wkwk|haha|xixi|lol|lmao)"
    r")[\s!.,]*$",
    re.IGNORECASE,
)

_TIME_QUERY = re.compile(
    r"\b(?:jam\s*berapa|tanggal\s*berapa|hari\s*apa|sekarang\s*jam)\b", re.IGNORECASE
)

# Anything risky escapes to the full agent loop.
_UNSAFE_PATTERN = re.compile(
    r"\b(?:"
    r"hapus|delete|buang|ubah|ganti|update|tambah|buat|catat(?:in|kan)|inget|remind|"
    r"kirim|send|forward|simpan|save|geser|tunda|mundur|selesai(?:in|kan)?|"
    r"done|complete|tandai|mark|tolong\s+\w+|cari(?:in|kan)?|bikin(?:in|kan)?|"
    r"jadwal(?:in|kan)|set\b|clear|reconcile"
    r")\b",
    re.IGNORECASE,
)

MAX_FASTPATH_CHARS = 200


def _time_context() -> str:
    """Compact clock line for tiny prompts (greeting correctness)."""
    from ..memory.store import get_time_of_day_info

    time_str, period_info = get_time_of_day_info()
    return f"{time_str}. {period_info}"


def _deterministic_greeting(sender_name: str) -> str:
    from ..memory.store import get_time_of_day_info

    time_str, _ = get_time_of_day_info()
    period = (
        "pagi" if "Pagi" in time_str
        else "siang" if "Siang" in time_str
        else "sore" if "Sore" in time_str
        else "malam"
    )
    return f"Halo {sender_name}, selamat {period}. Ada yang bisa dibantu?"


def classify_fastpath(text: str) -> str:
    """Return 'chat' | 'time' | ''.

    '' means: full agent loop (all data queries live there — model decides
    filtering/formatting through normal tool calling).
    """
    clean = (text or "").strip()
    if not clean or len(clean) > MAX_FASTPATH_CHARS:
        return ""
    if _UNSAFE_PATTERN.search(clean):
        return ""
    if _CHAT_PATTERN.match(clean):
        return "chat"
    if _TIME_QUERY.search(clean) and len(clean) < 60:
        return "time"
    return ""


async def run_fastpath(
    text: str,
    kind: str,
    sender_name: str,
    chat_completion_fn: Any,
) -> str | None:
    """Execute a fast-path turn. Returns reply text, or None to fall back."""
    if kind == "chat":
        payload = {
            "systemInstruction": {
                "parts": [{"text": _CHAT_SYSTEM_PROMPT.format(time_context=_time_context())}]
            },
            "contents": [
                {"role": "user", "parts": [{"text": f"[{sender_name}]: {text}"}]}
            ],
            "generationConfig": {"temperature": 0.4, "maxOutputTokens": 120},
        }
        try:
            reply = await chat_completion_fn(payload)
        except Exception:
            reply = None
        if reply:
            cleaned = reply.strip()
            if "[FALLBACK]" in cleaned:
                return None  # model defers to the full agent — respect that
            if len(cleaned) <= 1200:
                return cleaned
        return _deterministic_greeting(sender_name)
    if kind == "time":
        from ..memory.store import get_time_of_day_info

        time_str, _ = get_time_of_day_info()
        return f"Sekarang {time_str}."
    return None
