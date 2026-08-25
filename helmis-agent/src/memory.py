"""
memory.py — Persistent JSON store for Helmis memory (tasks, schedule, people, notes).

Persists data to /app/data/helmis_memory.json so it survives restarts.
Provides clean Python methods to query and update memory.
"""

import json
import logging
import os
import re
import threading
from datetime import datetime, timedelta
from typing import Any, cast
from zoneinfo import ZoneInfo

log = logging.getLogger("helmis-memory")

DATA_DIR = os.environ.get("DATA_DIR", "/app/data" if os.path.exists("/app") else "./data")
MEMORY_FILE = os.path.join(DATA_DIR, "helmis_memory.json")
TZ = ZoneInfo(os.environ.get("TZ", "Asia/Jakarta"))

_memory_lock = threading.Lock()


def _ensure_data_dir() -> None:
    """Ensure data directory exists."""
    os.makedirs(os.path.dirname(MEMORY_FILE), exist_ok=True)


def load_memory() -> dict[str, Any]:
    """Load persistent memory from disk with thread-safety."""
    _ensure_data_dir()
    default_memory: dict[str, Any] = {
        "tasks": [],
        "schedules": [],
        "people": {
            "Gilang": {
                "phone": os.environ.get("GILANG_PHONE", "+6281234567890"),
                "role": "User / Principal",
                "notes": "Direct, prefers concise updates",
            },
            "Bunga": {
                "phone": os.environ.get("BUNGA_PHONE", "+6289876543210"),
                "role": "User / Principal",
                "notes": "Co-principal",
            },
        },
        "notes": [],
    }

    with _memory_lock:
        if not os.path.exists(MEMORY_FILE):
            # Save default memory atomically
            _save_memory_unlocked(default_memory)
            return default_memory

        try:
            with open(MEMORY_FILE, encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    for k, v in default_memory.items():
                        if k not in data:
                            data[k] = v
                    return cast(dict[str, Any], data)
                return default_memory
        except Exception as e:
            log.error("Failed to load memory file (%s): %s", MEMORY_FILE, e)
            return default_memory


def save_memory(data: dict[str, Any]) -> None:
    """Save persistent memory atomically to disk."""
    _ensure_data_dir()
    with _memory_lock:
        _save_memory_unlocked(data)


def _save_memory_unlocked(data: dict[str, Any]) -> None:
    """Internal atomic write helper."""
    tmp_file = f"{MEMORY_FILE}.tmp.{os.getpid()}"
    try:
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_file, MEMORY_FILE)
    except Exception as e:
        log.error("Failed to save memory file (%s): %s", MEMORY_FILE, e)
        if os.path.exists(tmp_file):
            try:
                os.remove(tmp_file)
            except Exception:
                pass


def get_time_of_day_info() -> tuple[str, str]:
    """Get current time formatted in WIB and the corresponding Indonesian time-of-day period."""
    now = datetime.now(TZ)
    hour = now.hour
    if 5 <= hour < 12:
        period = "Pagi"
        greeting = "Selamat pagi"
    elif 12 <= hour < 15:
        period = "Siang"
        greeting = "Selamat siang"
    elif 15 <= hour < 19:
        period = "Sore"
        greeting = "Selamat sore"
    else:
        period = "Malam"
        greeting = "Selamat malam"

    time_str = now.strftime("%A, %d %B %Y - %H:%M WIB")
    return time_str, f"{period} (Gunakan sapaan '{greeting}' jika menyapa)"


def get_current_time_str() -> str:
    """Get current time formatted in WIB."""
    time_str, _ = get_time_of_day_info()
    return time_str


def get_memory_context_summary() -> str:
    """Format memory state into prompt context."""
    mem = load_memory()
    now_str, period_info = get_time_of_day_info()

    tasks = mem.get("tasks", [])
    active_tasks = sorted(
        [t for t in tasks if t.get("status") != "completed"],
        key=lambda t: parse_due_timestamp(t.get("due", "")),
    )

    def format_task_line(t: dict[str, Any]) -> str:
        due = t.get("due", "No deadline")
        title = t.get("title", "")
        assignee = t.get("assignee", "Gilang")
        p_val = t.get("priority", "normal")
        priority_tag = f" [{p_val.upper()}]" if p_val != "normal" else ""
        lead_val = t.get("lead_time_minutes", 0)
        lead_tag = f" (Lead: {lead_val}m)" if lead_val else ""
        if t.get("reminded") or t.get("due_reminded"):
            remind_status = f" | [REMINDER SENT to {assignee} at {t.get('reminded_at', 'earlier')}]"
        elif t.get("kickoff_reminded"):
            remind_status = f" | [KICKOFF PREP SENT to {assignee}]"
        else:
            remind_status = " | [Reminder NOT sent yet]"
        return f"- [{due}]{priority_tag} {title}{lead_tag} (Assignee: {assignee}){remind_status}"

    tasks_summary = (
        "\n".join([format_task_line(t) for t in active_tasks])
        if active_tasks
        else "No active tasks recorded yet. (Do NOT invent fake tasks!)"
    )

    # Activity log of recent messages/reminders sent by Helmis
    activity_log = mem.get("activity_log", [])
    recent_activities = activity_log[-6:]
    activity_summary = (
        "\n".join([f"- [{a.get('time', '')}] {a.get('summary', '')}" for a in recent_activities])
        if recent_activities
        else "No recent proactive messages logged."
    )

    people = mem.get("people", {})
    people_summary = (
        "\n".join(
            [
                f"- {name}: {info.get('role', '')} | {info.get('notes', '')}"
                for name, info in people.items()
            ]
        )
        if people
        else "No contacts recorded yet."
    )

    notes = mem.get("notes", [])
    notes_summary = "\n".join([f"- {n.get('content')}" for n in notes]) if notes else "No notes."

    return f"""
[TEMPORAL CONTEXT & LIVE MEMORY]
- Current Local Time: {now_str}
- Current Time of Day: {period_info}
- Temporal Rule: Always respect the current time of day. NEVER greet with 'Selamat pagi' during sore/malam!
- Active Tasks & Reminder Status:
{tasks_summary}
- Recent Messages & Reminders Dispatched by Helmis:
{activity_summary}
- People Directory:
{people_summary}
- Shared Notes:
{notes_summary}
"""


def log_activity(summary: str) -> None:
    """Log an action or sent reminder into memory activity log."""
    mem = load_memory()
    entry = {
        "time": get_current_time_str(),
        "summary": summary.strip(),
    }
    log_list = mem.setdefault("activity_log", [])
    log_list.append(entry)
    mem["activity_log"] = log_list[-50:]
    save_memory(mem)


def add_task(
    title: str,
    due: str = "",
    assignee: str = "Gilang",
    priority: str = "normal",
    lead_time_minutes: int = 0,
) -> dict[str, Any]:
    """Add a new task to memory (or update existing if same title and pending)."""
    if not title or not title.strip():
        raise ValueError("Task title cannot be empty")
    clean_title = title.strip()
    clean_due = due.strip() if due else "No deadline"
    clean_assignee = assignee.strip() if assignee else "Gilang"
    clean_priority = priority.strip().lower() if priority else "normal"
    if clean_priority not in ("urgent", "normal", "low"):
        clean_priority = "normal"
    clean_lead = int(lead_time_minutes or 0)

    mem = load_memory()
    tasks = mem.setdefault("tasks", [])

    # Check if duplicate pending task exists with same title
    for t in tasks:
        if t.get("title", "").lower() == clean_title.lower() and t.get("status") == "pending":
            t["due"] = clean_due
            t["assignee"] = clean_assignee
            t["priority"] = clean_priority
            t["lead_time_minutes"] = clean_lead
            t["updated_at"] = get_current_time_str()
            save_memory(mem)
            return cast(dict[str, Any], t)

    new_task = {
        "title": clean_title,
        "due": clean_due,
        "assignee": clean_assignee,
        "priority": clean_priority,
        "lead_time_minutes": clean_lead,
        "status": "pending",
        "kickoff_reminded": False,
        "due_reminded": False,
        "nudge_count": 0,
        "last_nudged_at": None,
        "nudge_stopped": False,
        "created_at": get_current_time_str(),
    }
    tasks.append(new_task)
    save_memory(mem)
    return new_task


def update_task(
    title: str,
    new_title: str | None = None,
    new_due: str | None = None,
    new_assignee: str | None = None,
    new_status: str | None = None,
    new_priority: str | None = None,
    new_lead_time_minutes: int | None = None,
) -> dict[str, Any] | None:
    """Update existing task fields by title (exact match first, then substring)."""
    mem = load_memory()
    tasks = mem.get("tasks", [])
    query = title.lower().strip()

    # Pass 1: Exact match
    target_task = next((t for t in tasks if t.get("title", "").lower().strip() == query), None)
    # Pass 2: Substring match
    if not target_task:
        target_task = next((t for t in tasks if query in t.get("title", "").lower()), None)

    if target_task:
        if new_title:
            target_task["title"] = new_title.strip()
        if new_due:
            target_task["due"] = new_due.strip()
            # Reset reminder lifecycle on reschedule / snooze
            target_task["kickoff_reminded"] = False
            target_task["due_reminded"] = False
            target_task["reminded"] = False
            target_task["nudge_count"] = 0
            target_task["last_nudged_at"] = None
            target_task["nudge_stopped"] = False
        if new_assignee:
            target_task["assignee"] = new_assignee.strip()
        if new_status:
            target_task["status"] = new_status.strip()
        if new_priority:
            p = new_priority.strip().lower()
            if p in ("urgent", "normal", "low"):
                target_task["priority"] = p
        if new_lead_time_minutes is not None:
            target_task["lead_time_minutes"] = int(new_lead_time_minutes)
        target_task["updated_at"] = get_current_time_str()
        save_memory(mem)
        return cast(dict[str, Any], target_task)
    return None


def parse_due_timestamp(due_str: str) -> float:
    """
    Parse a task due string into a Unix timestamp for urgency sorting.
    Supports relative dates (hari ini, besok, lusa), day-of-week (Senin..Minggu),
    ISO format (YYYY-MM-DD), and Indonesian/English month names.
    """
    if not due_str or not due_str.strip() or "no deadline" in due_str.lower():
        return float("inf")

    clean = due_str.strip().lower()
    now = datetime.now(TZ)

    # Extract time HH:MM or HH.MM
    hour = 23
    minute = 59
    time_match = re.search(r"(\d{1,2})[:.](\d{2})", clean)
    if time_match:
        hour = int(time_match.group(1))
        minute = int(time_match.group(2))
    elif "pagi" in clean:
        hour = 8
        minute = 0
    elif "siang" in clean:
        hour = 12
        minute = 0
    elif "sore" in clean:
        hour = 16
        minute = 0
    elif "malam" in clean:
        hour = 20
        minute = 0

    # 1. Relative keywords: "hari ini", "today"
    if "hari ini" in clean or "today" in clean:
        target_dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        return target_dt.timestamp()

    # 2. "besok", "tomorrow"
    if "besok" in clean or "tomorrow" in clean:
        target_dt = (now + timedelta(days=1)).replace(hour=hour, minute=minute, second=0, microsecond=0)
        return target_dt.timestamp()

    # 3. "lusa"
    if "lusa" in clean:
        target_dt = (now + timedelta(days=2)).replace(hour=hour, minute=minute, second=0, microsecond=0)
        return target_dt.timestamp()

    # 4. Day of Week (Senin .. Minggu)
    id_days = {
        "senin": 0, "monday": 0, "mon": 0,
        "selasa": 1, "tuesday": 1, "tue": 1,
        "rabu": 2, "wednesday": 2, "wed": 2,
        "kamis": 3, "thursday": 3, "thu": 3,
        "jumat": 4, "jum'at": 4, "friday": 4, "fri": 4,
        "sabtu": 5, "saturday": 5, "sat": 5,
        "minggu": 6, "ahad": 6, "sunday": 6, "sun": 6,
    }
    for day_name, day_idx in id_days.items():
        if re.search(rf"\b{day_name}\b", clean):
            days_ahead = (day_idx - now.weekday()) % 7
            if days_ahead == 0:
                # If day is today but specified hour is already in the past, roll to next week
                if (hour < now.hour) or (hour == now.hour and minute <= now.minute):
                    days_ahead = 7
            target_dt = (now + timedelta(days=days_ahead)).replace(hour=hour, minute=minute, second=0, microsecond=0)
            return target_dt.timestamp()

    # 5. ISO YYYY-MM-DD
    iso_match = re.search(r"(\d{4})-(\d{2})-(\d{2})", clean)
    if iso_match:
        try:
            target_dt = datetime(
                int(iso_match.group(1)),
                int(iso_match.group(2)),
                int(iso_match.group(3)),
                hour,
                minute,
                0,
                tzinfo=TZ,
            )
            return target_dt.timestamp()
        except Exception:
            pass

    # 6. Indonesian & English month names (e.g. 28 Agustus 2026 or 28 Agustus)
    id_months = {
        "januari": 1, "jan": 1,
        "februari": 2, "feb": 2,
        "maret": 3, "mar": 3,
        "april": 4, "apr": 4,
        "mei": 5, "may": 5,
        "juni": 6, "jun": 6,
        "juli": 7, "jul": 7,
        "agustus": 8, "agt": 8, "aug": 8, "august": 8,
        "september": 9, "sep": 9,
        "oktober": 10, "okt": 10, "oct": 10, "october": 10,
        "november": 11, "nov": 11,
        "desember": 12, "des": 12, "dec": 12, "december": 12,
    }
    date_month_match = re.search(r"(\d{1,2})\s+([a-zA-Z]+)(?:\s+(\d{4}))?", clean)
    if date_month_match:
        day = int(date_month_match.group(1))
        month_str = date_month_match.group(2).lower()
        year = int(date_month_match.group(3)) if date_month_match.group(3) else now.year
        if month_str in id_months:
            try:
                target_dt = datetime(year, id_months[month_str], day, hour, minute, 0, tzinfo=TZ)
                return target_dt.timestamp()
            except Exception:
                pass

    return float("inf")


def list_tasks(status: str = "pending", sort_by: str = "urgency") -> list[dict[str, Any]]:
    """
    List tasks filtered by status ('pending', 'completed', 'all').
    Default sort order is by urgency (earliest deadline first, no-deadline items last).
    """
    mem = load_memory()
    tasks = cast(list[dict[str, Any]], mem.get("tasks", []))
    filtered = tasks if status == "all" else [t for t in tasks if t.get("status") == status]

    if sort_by == "urgency":
        return sorted(filtered, key=lambda t: parse_due_timestamp(t.get("due", "")))
    elif sort_by == "created":
        return sorted(filtered, key=lambda t: str(t.get("created_at", "")), reverse=True)
    elif sort_by == "alphabetical":
        return sorted(filtered, key=lambda t: str(t.get("title", "")).lower())
    return filtered


def complete_task(title: str) -> dict[str, Any] | None:
    """Mark a task as completed by title (exact match first, then substring)."""
    mem = load_memory()
    tasks = mem.get("tasks", [])
    query = title.lower().strip()

    # Pass 1: Exact match on active tasks
    target_task = next(
        (t for t in tasks if t.get("title", "").lower().strip() == query and t.get("status") != "completed"),
        None,
    )
    # Pass 2: Substring match
    if not target_task:
        target_task = next(
            (t for t in tasks if query in t.get("title", "").lower() and t.get("status") != "completed"),
            None,
        )

    if target_task:
        target_task["status"] = "completed"
        target_task["completed_at"] = get_current_time_str()
        save_memory(mem)
        return cast(dict[str, Any], target_task)
    return None


def delete_task(title: str) -> bool:
    """Delete a single task by title (exact match first, then best substring match)."""
    mem = load_memory()
    tasks = mem.get("tasks", [])
    query = title.lower().strip()

    # Pass 1: Exact match
    target_idx = next(
        (i for i, t in enumerate(tasks) if t.get("title", "").lower().strip() == query),
        None,
    )
    # Pass 2: Substring match (delete only the single matched item, never bulk)
    if target_idx is None:
        target_idx = next(
            (i for i, t in enumerate(tasks) if query in t.get("title", "").lower()),
            None,
        )

    if target_idx is not None:
        tasks.pop(target_idx)
        save_memory(mem)
        return True
    return False


def add_person(name: str, phone: str = "", role: str = "", notes: str = "") -> dict[str, Any]:
    """Add or update person in directory."""
    if not name or not name.strip():
        raise ValueError("Person name cannot be empty")
    mem = load_memory()
    person_data = {
        "phone": phone.strip(),
        "role": role.strip(),
        "notes": notes.strip(),
        "updated_at": get_current_time_str(),
    }
    mem.setdefault("people", {})[name.strip()] = person_data
    save_memory(mem)
    return {"name": name.strip(), **person_data}


def get_person(name: str) -> dict[str, Any] | None:
    """Find a person in directory by name substring."""
    mem = load_memory()
    people = mem.get("people", {})
    query = name.lower().strip()
    for p_name, p_data in people.items():
        if query in p_name.lower():
            return {"name": p_name, **p_data}
    return None


def save_note(title: str, content: str) -> dict[str, Any]:
    """Save or update a note in memory."""
    if not title or not title.strip():
        raise ValueError("Judul catatan tidak boleh kosong")
    if not content or not content.strip():
        raise ValueError("Isi catatan tidak boleh kosong")

    clean_title = title.strip()
    clean_content = content.strip()
    mem = load_memory()
    notes = mem.setdefault("notes", [])

    # Update existing note if same title
    for n in notes:
        if n.get("title", "").lower() == clean_title.lower():
            n["content"] = clean_content
            n["updated_at"] = get_current_time_str()
            save_memory(mem)
            return cast(dict[str, Any], n)

    note_data = {
        "title": clean_title,
        "content": clean_content,
        "created_at": get_current_time_str(),
        "updated_at": get_current_time_str(),
    }
    notes.append(note_data)
    save_memory(mem)
    return note_data


def get_note(title: str) -> dict[str, Any] | None:
    """Find a note in memory by title keyword or substring match."""
    if not title or not title.strip():
        return None
    mem = load_memory()
    notes = mem.get("notes", [])
    q = title.lower().strip()
    for n in notes:
        if q in n.get("title", "").lower():
            return cast(dict[str, Any], n)
    return None


def list_notes() -> list[dict[str, Any]]:
    """List all stored notes with their titles and full contents."""
    mem = load_memory()
    return cast(list[dict[str, Any]], mem.get("notes", []))


def append_to_note(title: str, addition: str) -> dict[str, Any]:
    """Append text or list items to an existing note, or create it if not found."""
    if not title or not title.strip():
        raise ValueError("Judul catatan tidak boleh kosong")
    if not addition or not addition.strip():
        raise ValueError("Teks tambahan tidak boleh kosong")

    clean_title = title.strip()
    clean_addition = addition.strip()
    mem = load_memory()
    notes = mem.setdefault("notes", [])

    for n in notes:
        if clean_title.lower() in n.get("title", "").lower():
            existing_content = str(n.get("content", "")).rstrip()
            if existing_content:
                n["content"] = f"{existing_content}\n{clean_addition}"
            else:
                n["content"] = clean_addition
            n["updated_at"] = get_current_time_str()
            save_memory(mem)
            return cast(dict[str, Any], n)

    # Note did not exist, create new
    note_data = {
        "title": clean_title,
        "content": clean_addition,
        "created_at": get_current_time_str(),
        "updated_at": get_current_time_str(),
    }
    notes.append(note_data)
    save_memory(mem)
    return note_data


def delete_note(title: str) -> dict[str, Any]:
    """Delete a note from memory by title substring."""
    if not title or not title.strip():
        return {"status": "error", "error": "Judul catatan tidak boleh kosong."}
    mem = load_memory()
    notes = mem.get("notes", [])
    q = title.lower().strip()
    initial_len = len(notes)
    kept = [n for n in notes if q not in n.get("title", "").lower()]
    if len(kept) < initial_len:
        mem["notes"] = kept
        save_memory(mem)
        return {"status": "success", "message": f"Catatan '{title}' berhasil dihapus."}
    return {"status": "not_found", "error": f"Catatan dengan judul '{title}' tidak ditemukan."}


def search_memory(query: str) -> dict[str, Any]:
    """Search tasks, people, and notes for a keyword query."""
    mem = load_memory()
    q = query.lower().strip()
    matching_tasks = [
        t
        for t in mem.get("tasks", [])
        if q in t.get("title", "").lower() or q in t.get("due", "").lower()
    ]
    matching_people = {
        k: v for k, v in mem.get("people", {}).items() if q in k.lower() or q in str(v).lower()
    }
    matching_notes = [
        n
        for n in mem.get("notes", [])
        if q in n.get("title", "").lower() or q in n.get("content", "").lower()
    ]
    return {
        "tasks": matching_tasks,
        "people": matching_people,
        "notes": matching_notes,
    }
