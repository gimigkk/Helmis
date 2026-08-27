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

_memory_lock = threading.RLock()


def _get_memory_file() -> str:
    import sys
    default_f = globals().get("MEMORY_FILE") or os.path.join(DATA_DIR, "helmis_memory.json")
    if "src.memory" in sys.modules:
        pkg = sys.modules["src.memory"]
        pkg_f = getattr(pkg, "MEMORY_FILE", None)
        if pkg_f and pkg_f != default_f:
            return pkg_f
    if "src.memory.store" in sys.modules:
        mod = sys.modules["src.memory.store"]
        mod_f = getattr(mod, "MEMORY_FILE", None)
        if mod_f and mod_f != default_f:
            return mod_f
    if "src.memory" in sys.modules and hasattr(sys.modules["src.memory"], "MEMORY_FILE"):
        return sys.modules["src.memory"].MEMORY_FILE
    return default_f


def _ensure_data_dir() -> None:
    """Ensure data directory exists."""
    os.makedirs(os.path.dirname(_get_memory_file()), exist_ok=True)


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

    mem_path = _get_memory_file()
    with _memory_lock:
        if not os.path.exists(mem_path):
            # Save default memory atomically
            _save_memory_unlocked(default_memory)
            return default_memory

        try:
            with open(mem_path, encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    for k, v in default_memory.items():
                        if k not in data:
                            data[k] = v
                    return cast(dict[str, Any], data)
                return default_memory
        except Exception as e:
            log.error("Failed to load memory file (%s): %s", mem_path, e)
            return default_memory


def save_memory(data: dict[str, Any]) -> None:
    """Save persistent memory atomically to disk."""
    _ensure_data_dir()
    with _memory_lock:
        _save_memory_unlocked(data)


def _save_memory_unlocked(data: dict[str, Any]) -> None:
    """Internal atomic write helper."""
    mem_path = _get_memory_file()
    tmp_file = f"{mem_path}.tmp.{os.getpid()}"
    try:
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_file, mem_path)
    except Exception as e:
        log.error("Failed to save memory file (%s): %s", mem_path, e)
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
    """Format temporal context for the agent prompt without leaking static database dumps."""
    mem = load_memory()
    now_str, period_info = get_time_of_day_info()

    # Activity log of recent messages/reminders sent by Helmis
    activity_log = mem.get("activity_log", [])
    recent_activities = activity_log[-4:]
    activity_summary = (
        "\n".join([f"- [{a.get('time', '')}] {a.get('summary', '')}" for a in recent_activities])
        if recent_activities
        else "No recent proactive messages logged."
    )

    return f"""
[TEMPORAL CONTEXT]
- Current Local Time: {now_str}
- Current Time of Day: {period_info}
- Timezone: Asia/Jakarta (WIB, UTC+7)
- Recent Proactive Alerts Dispatched by Helmis:
{activity_summary}
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
    task_type: str = "reminder",
    job: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Add a new task or scheduled action to memory (or update existing if same title and pending)."""
    if not title or not title.strip():
        raise ValueError("Task title cannot be empty")
    clean_title = title.strip()
    clean_due = due.strip() if due else "No deadline"
    clean_assignee = assignee.strip() if assignee else "Gilang"
    clean_priority = priority.strip().lower() if priority else "normal"
    if clean_priority not in ("urgent", "normal", "low"):
        clean_priority = "normal"
    clean_lead = lead_time_minutes or 0

    clean_task_type = str(task_type).strip().lower() if task_type else "reminder"
    if clean_assignee.lower() == "helmis" or job or clean_task_type in ("scheduled_action", "action", "bot"):
        clean_task_type = "scheduled_action"
        clean_assignee = "Helmis"
        clean_lead = 0  # Bot actions do not need human preparation lead-time buffers

    mem = load_memory()
    tasks = mem.setdefault("tasks", [])

    # Check if duplicate pending task exists with same title
    for t in tasks:
        if t.get("title", "").lower() == clean_title.lower() and t.get("status") == "pending":
            t["due"] = clean_due
            t["assignee"] = clean_assignee
            t["priority"] = clean_priority
            t["lead_time_minutes"] = clean_lead
            t["task_type"] = clean_task_type
            if job is not None:
                t["job"] = job
            t["updated_at"] = get_current_time_str()
            save_memory(mem)
            return cast(dict[str, Any], t)

    new_task: dict[str, Any] = {
        "title": clean_title,
        "due": clean_due,
        "assignee": clean_assignee,
        "priority": clean_priority,
        "lead_time_minutes": clean_lead,
        "task_type": clean_task_type,
        "status": "pending",
        "kickoff_reminded": False,
        "due_reminded": False,
        "nudge_count": 0,
        "last_nudged_at": None,
        "nudge_stopped": False,
        "retry_count": 0,
        "max_retries": 3,
        "execution_status": "pending",
        "created_at": get_current_time_str(),
        "updated_at": None,
        "completed_at": None,
    }
    if job:
        new_task["job"] = job

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
    new_task_type: str | None = None,
    new_job: dict[str, Any] | None = None,
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
            target_task["execution_status"] = "pending"
            target_task["retry_count"] = 0
        if new_assignee:
            target_task["assignee"] = new_assignee.strip()
        if new_status:
            target_task["status"] = new_status.strip()
            if new_status.strip().lower() == "completed" and not target_task.get("completed_at"):
                target_task["completed_at"] = get_current_time_str()
        if new_priority:
            p = new_priority.strip().lower()
            if p in ("urgent", "normal", "low"):
                target_task["priority"] = p
        if new_lead_time_minutes is not None:
            target_task["lead_time_minutes"] = new_lead_time_minutes
        if new_task_type:
            target_task["task_type"] = new_task_type.strip().lower()
        if new_job is not None:
            target_task["job"] = new_job
        target_task["updated_at"] = get_current_time_str()
        save_memory(mem)
        return cast(dict[str, Any], target_task)
    return None


def parse_due_timestamp(due_str: str) -> float:
    """
    Parse a task due string into a Unix timestamp for urgency sorting.
    Supports:
    - Relative delay offsets: '30 menit lagi', '2 jam lagi', 'in 15 mins'
    - Indonesian time formats: 'jam 3 sore' (15:00), 'jam 8 malam' (20:00), 'setengah 4 sore' (15:30)
    - Cultural period keywords: 'subuh' (04:30), 'maghrib' (18:30), 'isya' (19:30), 'ashar' (15:30), 'dzuhur' (12:00), 'dini hari' (02:00), 'tengah malam' (23:59)
    - Relative dates: 'hari ini', 'besok', 'lusa'
    - Day of week: 'Senin' .. 'Minggu'
    - ISO (YYYY-MM-DD) & Indonesian/English month names (e.g. '28 Agustus 2026', '28 Agustus')
    """
    if not due_str or not due_str.strip() or "no deadline" in due_str.lower():
        return float("inf")

    clean = due_str.strip().lower()
    now = datetime.now(TZ)

    # 1. Relative delay offsets from current moment
    rel_min = re.search(r"(\d+)\s*(?:menit|mins|min|m)\s*(?:lagi|later|from now)?", clean)
    if rel_min and any(k in clean for k in ("lagi", "later", "in ", "after ")):
        mins = int(rel_min.group(1))
        return (now + timedelta(minutes=mins)).timestamp()

    rel_hr = re.search(r"(\d+)\s*(?:jam|hours|hour|hr|h)\s*(?:lagi|later|from now)?", clean)
    if rel_hr and any(k in clean for k in ("lagi", "later", "in ", "after ")):
        hrs = int(rel_hr.group(1))
        return (now + timedelta(hours=hrs)).timestamp()

    # 2. Time Extraction (Indonesian & 24h)
    hour = 23
    minute = 59
    has_time = False

    # A. 'setengah X' or 'set X' (e.g. setengah 8 -> 07:30 / 19:30, jam set 5 sore -> 16:30)
    setengah_match = re.search(r"(?:setengah|set\.?)\s+(\d{1,2})", clean)
    if setengah_match:
        val = int(setengah_match.group(1))
        base_hr = (val - 1) % 24
        minute = 30
        if any(k in clean for k in ("malam", "isya")) and base_hr < 12:
            base_hr += 12
        elif any(k in clean for k in ("sore", "ashar")) and base_hr < 12:
            base_hr += 12
        elif any(k in clean for k in ("siang", "dzuhur")) and base_hr < 12 and base_hr != 11:
            base_hr += 12
        hour = base_hr
        has_time = True

    # B. 'HH:MM' or 'HH.MM'
    if not has_time:
        time_match = re.search(r"(\d{1,2})[:.](\d{2})", clean)
        if time_match:
            hour = int(time_match.group(1))
            minute = int(time_match.group(2))
            has_time = True

    # C. 'jam X' or 'pukul X' with period modifiers
    if not has_time:
        jam_match = re.search(r"(?:jam|pukul)\s+(\d{1,2})\b", clean)
        if jam_match:
            h_val = int(jam_match.group(1))
            minute = 0
            if any(k in clean for k in ("sore", "ashar")) and h_val <= 6:
                h_val += 12
            elif any(k in clean for k in ("malam", "isya")) and h_val <= 11:
                h_val += 12
            elif any(k in clean for k in ("siang", "dzuhur")) and h_val in (1, 2, 3, 4):
                h_val += 12
            hour = h_val
            has_time = True

    # D. Cultural Period Keywords Fallback
    if not has_time:
        if "tengah malam" in clean:
            hour, minute = 23, 59
            has_time = True
        elif "dini hari" in clean:
            hour, minute = 2, 0
            has_time = True
        elif "subuh" in clean:
            hour, minute = 4, 30
            has_time = True
        elif "maghrib" in clean:
            hour, minute = 18, 30
            has_time = True
        elif "isya" in clean:
            hour, minute = 19, 30
            has_time = True
        elif "ashar" in clean:
            hour, minute = 15, 30
            has_time = True
        elif "dzuhur" in clean:
            hour, minute = 12, 0
            has_time = True
        elif "pagi" in clean:
            hour, minute = 8, 0
            has_time = True
        elif "siang" in clean:
            hour, minute = 12, 0
            has_time = True
        elif "sore" in clean:
            hour, minute = 16, 0
            has_time = True
        elif "malam" in clean:
            hour, minute = 20, 0
            has_time = True

    # 3. Date Resolution
    # A. 'hari ini', 'today'
    if "hari ini" in clean or "today" in clean:
        return now.replace(hour=hour, minute=minute, second=0, microsecond=0).timestamp()

    # B. 'besok', 'tomorrow'
    if "besok" in clean or "tomorrow" in clean:
        return (now + timedelta(days=1)).replace(hour=hour, minute=minute, second=0, microsecond=0).timestamp()

    # C. 'lusa'
    if "lusa" in clean:
        return (now + timedelta(days=2)).replace(hour=hour, minute=minute, second=0, microsecond=0).timestamp()

    # D. Day of Week (Senin .. Minggu)
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
                if (hour < now.hour) or (hour == now.hour and minute <= now.minute):
                    days_ahead = 7
            return (now + timedelta(days=days_ahead)).replace(
                hour=hour, minute=minute, second=0, microsecond=0
            ).timestamp()

    # E. ISO YYYY-MM-DD
    iso_match = re.search(r"(\d{4})-(\d{2})-(\d{2})", clean)
    if iso_match:
        try:
            return datetime(
                int(iso_match.group(1)),
                int(iso_match.group(2)),
                int(iso_match.group(3)),
                hour,
                minute,
                0,
                tzinfo=TZ,
            ).timestamp()
        except Exception:
            pass

    # F. Indonesian & English Month Names
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
                return datetime(year, id_months[month_str], day, hour, minute, 0, tzinfo=TZ).timestamp()
            except Exception:
                pass

    # G. Fallback: If time was specified but no date, assume today (or tomorrow if time passed)
    if has_time:
        target_today = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target_today < now:
            return (now + timedelta(days=1)).replace(hour=hour, minute=minute, second=0, microsecond=0).timestamp()
        return target_today.timestamp()

    return float("inf")


def list_tasks(
    status: str = "pending",
    sort_by: str = "urgency",
    task_type: str = "all",
) -> list[dict[str, Any]]:
    """
    List tasks filtered by status ('pending', 'completed', 'all') and task_type ('all', 'reminder', 'scheduled_action').
    Default sort order is by urgency (earliest deadline first, no-deadline items last).
    """
    mem = load_memory()
    tasks = cast(list[dict[str, Any]], mem.get("tasks", []))
    filtered = tasks if status == "all" else [t for t in tasks if t.get("status") == status]

    if task_type != "all":
        clean_tt = task_type.strip().lower()
        filtered = [t for t in filtered if t.get("task_type", "reminder") == clean_tt]

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
