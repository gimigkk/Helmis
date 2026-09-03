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

# Tiny persona: enough to sound like Helmis, ~60 tokens vs ~9k.
# {time_context} is injected per-turn so greetings match the real clock
# (the full manual gets this from the system prompt; the tiny one must too).
_CHAT_SYSTEM_PROMPT = (
    "Kamu Helmis, sekretaris AI pribadi Gilang dan Bunga. "
    "Waktu sekarang: {time_context}. "
    "Balas santai, hangat, singkat (1-2 kalimat), bahasa Indonesia kasual. "
    "Sesuaikan sapaan dengan waktu (pagi/siang/sore/malam). "
    "Tanpa emoji. Proaktif seperlunya: kalau relevan, tawarkan bantuan "
    "satu kalimat singkat. "
    "Kalau pesan user berisi permintaan tindakan atau pertanyaan tentang data, "
    "balas hanya: [FALLBACK]"
)

# Layout contract mirrors system-prompt.md §4 "Task, Schedule & Timeline
# Layout Standards" so fast-path output is indistinguishable from full-loop
# output: numbered items, *Tugas X:* headers, indented └ sub-lines, blank
# lines between items. Proactive offer at the end keeps the vision.
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

# Deterministic rendering is deliberately limited to the plain overview.
# Qualifiers must reach the agent so it can interpret filters, custom sorting,
# summaries, and requested output formats instead of silently ignoring them.
_OVERVIEW_PHRASES = {
    "tugas apa aja",
    "tugas apa saja",
    "ada tugas apa",
    "ada tugas apa aja",
    "ada tugas apa saja",
    "list tugas",
    "daftar tugas",
    "cek tugas",
    "lihat tugas",
    "list reminder",
    "list reminder dong",
    "daftar reminder",
    "cek jadwal",
    "lihat jadwal",
    "catatan apa aja",
    "catatan apa saja",
    "notes apa aja",
    "notes apa saja",
    "list notes",
    "daftar notes",
    "list catatan",
    "daftar catatan",
    "ada jadwal apa",
    "ada jadwal apa aja",
    "ada jadwal apa saja",
    "list jadwal",
    "daftar jadwal",
}

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


def _time_context() -> str:
    """Compact clock line for tiny prompts (greeting correctness)."""
    from ..memory.store import get_time_of_day_info

    time_str, period_info = get_time_of_day_info()
    return f"{time_str}. {period_info}"


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
    normalized = re.sub(r"[^\w\s]", "", clean.lower())
    if normalized not in _OVERVIEW_PHRASES:
        return ""
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


def _fmt_due_line(due: str) -> str:
    d = (due or "").strip()
    if not d or d.lower() == "no deadline":
        return "   └ Deadline: —"
    return f"   └ Deadline: {d}"


def _render_tasks_reply(tasks: list[dict[str, Any]], routine_count: int) -> str:
    """Render the §4 layout contract in Python. Zero model calls."""
    if not tasks:
        if routine_count > 0:
            return (
                f"Tidak ada tugas aktif selain {routine_count} jadwal absen rutin. "
                "Mau dilihat jadwal absennya?"
            )
        return "Tidak ada tugas aktif. Bersih!"
    lines = ["> *Daftar Tugas Aktif*", ""]
    groups: dict[str, list[dict[str, Any]]] = {}
    order = ["Gilang", "Bunga", "Both"]
    for t in tasks:
        a = str(t.get("assignee") or "Gilang")
        if a.lower() in ("both", "bersama", "kita"):
            key = "Both"
        else:
            key = a.split()[0].title() if a else "Gilang"
        groups.setdefault(key, []).append(t)
    ordered_keys = [k for k in order if k in groups] + [k for k in groups if k not in order]
    for key in ordered_keys:
        label = {"Gilang": "*Tugas Gilang:*", "Bunga": "*Tugas Bunga:*", "Both": "*Tugas Bersama:*"}.get(key, f"*Tugas {key}:*")
        lines.append(label)
        lines.append("")
        for i, t in enumerate(groups[key], 1):
            title = str(t.get("title", "?")).strip()
            lines.append(f"{i}. *{title}*")
            lines.append(_fmt_due_line(str(t.get("due") or "")))
            rec = t.get("recurrence")
            if isinstance(rec, dict) and rec.get("type") == "weekly":
                days = "/".join(str(d) for d in rec.get("weekdays", []))
                tm = rec.get("time", "")
                sched = f"{days} {tm}" if tm else days
                lines.append(f"   └ Jadwal: mingguan {sched}")
            lines.append("")
    # Proactive footer per vision: closest deadline + hidden routine note
    with_due = [t for t in tasks if t.get("due") and str(t.get("due", "")).lower() != "no deadline"]
    if with_due:
        nxt = with_due[0]
        lines.append(f"Terdekat: *{nxt.get('title', '?')}* — {nxt.get('due', '')}")
        lines.append("")
    if routine_count > 0:
        lines.append(f"(+{routine_count} jadwal absen rutin disembunyikan — bilang 'absen apa aja' buat lihat.)")
    return "\n".join(lines).strip()


def _render_notes_reply(notes: list[dict[str, Any]]) -> str:
    if not notes:
        return "Tidak ada catatan tersimpan."
    lines = ["> *Daftar Catatan*", ""]
    for i, n in enumerate(notes[:15], 1):
        title = str(n.get("title", "?")).strip()
        content_raw = str(n.get("content", ""))
        preview = content_raw.strip().replace("\n", " ")[:80]
        suffix = f" — {preview}..." if len(content_raw) > 80 else (f" — {preview}" if preview else "")
        lines.append(f"{i}. *{title}*{suffix}")
        lines.append("")
    return "\n".join(lines).strip()


def _render_schedules_reply(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "Tidak ada jadwal aktif."
    lines = ["> *Daftar Jadwal Aktif*", ""]
    for i, s in enumerate(rows[:25], 1):
        title = str(s.get("title", "?")).strip()
        starts = str(s.get("starts_at", "?")).strip()
        lines.append(f"{i}. *{title}*")
        lines.append(f"   └ Jadwal: {starts}")
        lines.append("")
    return "\n".join(lines).strip()


async def run_fastpath(
    text: str,
    kind: str,
    sender_name: str,
    chat_completion_fn: Any,
) -> str | None:
    """Execute a fast-path turn. Returns reply text, or None to fall back.

    Data queries (tasks/schedules/notes) render deterministically in Python —
    zero model calls, zero provider dependence. Only chat pings the model;
    if it fails, a deterministic greeting keeps the turn alive.
    """
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
            if "[FALLBACK]" not in cleaned and len(cleaned) <= 1200:
                return cleaned
        # Deterministic greeting fallback — never dead, never slow.
        from ..memory.store import get_time_of_day_info

        time_str, _ = get_time_of_day_info()
        period = "pagi" if "Pagi" in time_str else "siang" if "Siang" in time_str else "sore" if "Sore" in time_str else "malam"
        return f"Halo {sender_name}, selamat {period}. Ada yang bisa dibantu?"
    if kind == "time":
        from ..memory.store import get_time_of_day_info

        time_str, _ = get_time_of_day_info()
        return f"Sekarang {time_str}."
    if kind == "tasks":
        from ..memory.store import list_tasks

        work = list_tasks(status="pending", include_routine=False)
        routine_count = len(list_tasks(status="pending", include_routine=True)) - len(work)
        return _render_tasks_reply(work, routine_count)
    if kind == "schedules":
        from ..memory.store import get_repository

        return _render_schedules_reply(get_repository().list_schedules(active_only=True))
    if kind == "notes":
        from ..memory.store import list_notes

        return _render_notes_reply(list_notes())
    return None
