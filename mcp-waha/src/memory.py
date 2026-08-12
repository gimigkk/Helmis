"""
memory.py — Persistent JSON store for Helmis memory (tasks, schedule, people, notes).

Persists data to /app/data/helmis_memory.json so it survives restarts.
Provides clean Python methods to query and update memory.
"""

import json
import logging
import os
from datetime import datetime
from typing import Any, cast
from zoneinfo import ZoneInfo

log = logging.getLogger("helmis-memory")

DATA_DIR = os.environ.get("DATA_DIR", "/app/data" if os.path.exists("/app") else "./data")
MEMORY_FILE = os.path.join(DATA_DIR, "helmis_memory.json")
TZ = ZoneInfo(os.environ.get("TZ", "Asia/Jakarta"))


def _ensure_data_dir() -> None:
    """Ensure data directory exists."""
    os.makedirs(os.path.dirname(MEMORY_FILE), exist_ok=True)


def load_memory() -> dict[str, Any]:
    """Load persistent memory from disk."""
    _ensure_data_dir()
    default_memory: dict[str, Any] = {
        "tasks": [],
        "schedules": [],
        "people": {
            "Gilang": {
                "phone": "+6281932062070",
                "role": "User / Principal",
                "notes": "Direct, prefers concise updates",
            },
            "Bunga": {
                "phone": "+6281398971445",
                "role": "User / Principal",
                "notes": "Co-principal",
            },
        },
        "notes": [],
    }

    if not os.path.exists(MEMORY_FILE):
        save_memory(default_memory)
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
    """Save persistent memory to disk."""
    _ensure_data_dir()
    try:
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        log.error("Failed to save memory file (%s): %s", MEMORY_FILE, e)


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
    active_tasks = [t for t in tasks if t.get("status") != "completed"]

    def format_task_line(t: dict[str, Any]) -> str:
        due = t.get("due", "No deadline")
        title = t.get("title", "")
        assignee = t.get("assignee", "Gilang")
        if t.get("reminded"):
            remind_status = f" | [REMINDER SENT to {assignee} at {t.get('reminded_at', 'earlier')}]"
        else:
            remind_status = " | [Reminder NOT sent yet]"
        return f"- [{due}] {title} (Assignee: {assignee}){remind_status}"

    tasks_summary = (
        "\n".join([format_task_line(t) for t in active_tasks])
        if active_tasks
        else "No active tasks recorded yet. (Do NOT invent fake tasks!)"
    )

    # Activity log of recent messages/reminders sent by Helmis
    activity_log = mem.get("activity_log", [])
    recent_activities = activity_log[-6:]
    activity_summary = (
        "\n".join(
            [f"- [{a.get('time', '')}] {a.get('summary', '')}" for a in recent_activities]
        )
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


def add_task(title: str, due: str = "", assignee: str = "Gilang") -> dict[str, Any]:
    """Add a new task to memory (or update existing if same title and pending)."""
    if not title or not title.strip():
        raise ValueError("Task title cannot be empty")
    clean_title = title.strip()
    clean_due = due.strip() if due else "No deadline"
    clean_assignee = assignee.strip() if assignee else "Gilang"

    mem = load_memory()
    tasks = mem.setdefault("tasks", [])

    # Check if duplicate pending task exists with same title
    for t in tasks:
        if t.get("title", "").lower() == clean_title.lower() and t.get("status") == "pending":
            t["due"] = clean_due
            t["assignee"] = clean_assignee
            t["updated_at"] = get_current_time_str()
            save_memory(mem)
            return cast(dict[str, Any], t)

    new_task = {
        "title": clean_title,
        "due": clean_due,
        "assignee": clean_assignee,
        "status": "pending",
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
) -> dict[str, Any] | None:
    """Update existing task fields by title substring match."""
    mem = load_memory()
    tasks = mem.get("tasks", [])
    query = title.lower().strip()
    for t in tasks:
        if query in t.get("title", "").lower():
            if new_title:
                t["title"] = new_title.strip()
            if new_due:
                t["due"] = new_due.strip()
            if new_assignee:
                t["assignee"] = new_assignee.strip()
            if new_status:
                t["status"] = new_status.strip()
            t["updated_at"] = get_current_time_str()
            save_memory(mem)
            return cast(dict[str, Any], t)
    return None


def list_tasks(status: str = "pending") -> list[dict[str, Any]]:
    """List tasks filtered by status ('pending', 'completed', 'all'). Default is pending."""
    mem = load_memory()
    tasks = cast(list[dict[str, Any]], mem.get("tasks", []))
    if status == "all":
        return tasks
    return [t for t in tasks if t.get("status") == status]


def complete_task(title: str) -> dict[str, Any] | None:
    """Mark a task as completed by title substring match."""
    mem = load_memory()
    tasks = mem.get("tasks", [])
    query = title.lower().strip()
    for t in tasks:
        if query in t.get("title", "").lower() and t.get("status") != "completed":
            t["status"] = "completed"
            t["completed_at"] = get_current_time_str()
            save_memory(mem)
            return cast(dict[str, Any], t)
    return None


def delete_task(title: str) -> bool:
    """Delete a task by title substring match."""
    mem = load_memory()
    tasks = mem.get("tasks", [])
    initial_len = len(tasks)
    mem["tasks"] = [t for t in tasks if title.lower() not in t.get("title", "").lower()]
    save_memory(mem)
    return len(mem["tasks"]) < initial_len


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
    """Save a note to memory."""
    mem = load_memory()
    note_data = {
        "title": title.strip(),
        "content": content.strip(),
        "created_at": get_current_time_str(),
    }
    mem.setdefault("notes", []).append(note_data)
    save_memory(mem)
    return note_data


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
