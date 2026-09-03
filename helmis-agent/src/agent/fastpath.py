"""
fastpath.py — Deterministic fast paths for trivial turns.

Top agentic systems avoid loading the full secretary operating manual for
"halo" or "ada tugas apa". This module answers a narrow class of turns
directly — tiny prompt, no tools, no skills payload, no semantic search,
no chat-history rebuild — cutting a ~7s turn to ~2s.

Safety: only *query* domains (task/schedule/note/person) and pure chat are
routed here. Any action intent, destructive verb, media, or ambiguity falls
through to the full agent loop.
"""

import logging
import re
from typing import Any

log = logging.getLogger("helmis-fastpath")

# Tiny persona: enough to sound like Helmis, ~50 tokens vs ~9k.
_CHAT_SYSTEM_PROMPT = (
    "Kamu Helmis, sekretaris AI pribadi Gilang dan Bunga. "
    "Balas santai, hangat, singkat (1-2 kalimat), bahasa Indonesia kasual. "
    "Jangan pakai emoji. Jangan menawarkan bantuan berlebihan. "
    "Kalau pesan user berisi permintaan tindakan atau pertanyaan tentang data, "
    "balas hanya: [FALLBACK]"
)

_QUERY_SYSTEM_PROMPT = (
    "Kamu Helmis, sekretaris AI pribadi Gilang dan Bunga. "
    "User bertanya tentang data mereka. Jawab ringkas dan akurat HANYA dari "
    "DATA yang diberikan di bawah — jangan mengarang, jangan menambah, "
    "jangan menawarkan hal lain. Bahasa Indonesia santai, format WhatsApp "
    "(boleh *bold*, tanpa emoji, tanpa LaTeX). Kalau data kosong, bilang apa adanya. "
    "Kalau pertanyaan tidak bisa dijawab dari data, balas hanya: [FALLBACK]"
)

# Casual chat: short, no digits/time, no action verbs, no question about data.
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

# Query openers that map cleanly onto deterministic data snapshots.
_TASK_QUERY = re.compile(
    r"\b(?:tugas|task|reminder|agenda|deadline)\b", re.IGNORECASE
)
_SCHEDULE_QUERY = re.compile(
    r"\b(?:jadwal|schedule|kalender|kegiatan)\b", re.IGNORECASE
)
_NOTE_QUERY = re.compile(
    r"\b(?:catatan|notes?)\b", re.IGNORECASE
)
_TIME_QUERY = re.compile(
    r"\b(?:jam\s*berapa|tanggal\s*berapa|hari\s*apa|sekarang\s*jam)\b", re.IGNORECASE
)

# Anything risky escapes the fast path.
_UNSAFE_PATTERN = re.compile(
    r"\b(?:"
    r"hapus|delete|buang|ubah|ganti|update|tambah|buat|catat(?:in|kan)|inget|remind|"
    r"kirim|send|forward|simpan|save|geser|tunda|mundur|selesai(?:in|kan)?|"
    r"done|complete|tandai|mark|tolong\s+\w+|cari(?:in|kan)?|bikin(?:in|kan)?|"
    r"buat(?:in|kan)?|jadwal(?:in|kan)|set\b|clear|reconcile"
    r")\b",
    re.IGNORECASE,
)

MAX_FASTPATH_CHARS = 200


def classify_fastpath(text: str) -> str:
    """Return 'chat' | 'tasks' | 'schedules' | 'notes' | 'time' | ''.

    '' means: no fast path, use the full agent loop.
    """
    clean = (text or "").strip()
    if not clean or len(clean) > MAX_FASTPATH_CHARS:
        return ""
    if _UNSAFE_PATTERN.search(clean):
        return ""
    if _CHAT_PATTERN.match(clean):
        return "chat"
    # Pure time query
    if _TIME_QUERY.search(clean) and len(clean) < 60:
        return "time"
    # Data queries: must look like a question/list request, not an action
    is_listish = bool(
        re.search(
            r"^(?:ada|apa|cek|check|lihat|liat|show|list|daftar|sekarang)|\?$|apa\s+(?:aja|saja)",
            clean,
            re.IGNORECASE,
        )
    )
    if not is_listish:
        return ""
    if _TASK_QUERY.search(clean) and not _SCHEDULE_QUERY.search(clean):
        return "tasks"
    if _SCHEDULE_QUERY.search(clean) and not _TASK_QUERY.search(clean):
        return "schedules"
    if _NOTE_QUERY.search(clean):
        return "notes"
    return ""


def _fmt_due(due: str) -> str:
    return f" — due {due}" if due else ""


def _fmt_recurrence(rec: Any) -> str:
    if not isinstance(rec, dict):
        return ""
    if rec.get("type") == "weekly" and rec.get("weekdays"):
        days = "/".join(str(d) for d in rec.get("weekdays", []))
        t = rec.get("time", "")
        return f" (mingguan: {days} {t})" if t else f" (mingguan: {days})"
    return ""


def collect_snapshot(kind: str) -> str:
    """Build a compact data snapshot for the query prompt."""
    if kind == "tasks":
        from ..memory.store import list_tasks

        tasks = list_tasks(status="pending")
        if not tasks:
            return "DATA (pending tasks): TIDAK ADA."
        lines = ["DATA (pending tasks, urut deadline):"]
        for t in tasks[:25]:
            line = f"- {t.get('title', '?')}{_fmt_due(str(t.get('due') or ''))}"
            line += _fmt_recurrence(t.get("recurrence"))
            if t.get("assignee") and t.get("assignee") != "Gilang":
                line += f" [{t['assignee']}]"
            lines.append(line)
        return "\n".join(lines)
    if kind == "schedules":
        from ..memory.store import get_repository

        rows = get_repository().list_schedules(active_only=True)
        if not rows:
            return "DATA (schedules): TIDAK ADA."
        lines = ["DATA (schedules aktif):"]
        for s in rows[:25]:
            lines.append(f"- {s.get('title', '?')} — {s.get('starts_at', '?')}")
        return "\n".join(lines)
    if kind == "notes":
        from ..memory.store import list_notes

        notes = list_notes()
        if not notes:
            return "DATA (notes): TIDAK ADA."
        lines = ["DATA (notes):"]
        for n in notes[:15]:
            title = n.get("title", "?")
            content = str(n.get("content", ""))[:300]
            lines.append(f"- {title}: {content}")
        return "\n".join(lines)
    return ""


async def run_fastpath(
    text: str,
    kind: str,
    sender_name: str,
    chat_completion_fn: Any,
) -> str | None:
    """Execute a fast-path turn. Returns reply text, or None to fall back.

    chat_completion_fn(payload) -> str must issue one plain generateContent
    call (no tools) and return the reply text, raising on total failure.
    """
    if kind == "chat":
        payload = {
            "systemInstruction": {"parts": [{"text": _CHAT_SYSTEM_PROMPT}]},
            "contents": [
                {"role": "user", "parts": [{"text": f"[{sender_name}]: {text}"}]}
            ],
            "generationConfig": {"temperature": 0.4, "maxOutputTokens": 120},
        }
    elif kind == "time":
        from ..memory.store import get_time_of_day_info

        time_str, _ = get_time_of_day_info()
        return f"Sekarang {time_str}."
    else:
        snapshot = collect_snapshot(kind)
        payload = {
            "systemInstruction": {"parts": [{"text": _QUERY_SYSTEM_PROMPT}]},
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": f"{snapshot}\n\nPERTANYAAN: {text}"}
                    ],
                }
            ],
            "generationConfig": {"temperature": 0.0, "maxOutputTokens": 700},
        }

    reply = await chat_completion_fn(payload)
    if not reply or not reply.strip():
        return None
    cleaned = reply.strip()
    if "[FALLBACK]" in cleaned or len(cleaned) > 1200:
        return None  # model thinks it needs the full agent — respect that
    return cleaned
