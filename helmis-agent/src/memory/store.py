"""
memory.py — Persistent store for Helmis memory.

Tasks live in SQLite (WAL) via :mod:`src.memory.task_repository`. People,
notes, and the activity log remain JSON-backed in the ``helmis_memory.json``
sidecar until the second bounded migration. Traces stay append-only JSONL
and are not part of this module.
"""

import json
import logging
import os
import re
import threading
import unicodedata
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any, cast
from zoneinfo import ZoneInfo

from .task_repository import TaskRepository

log = logging.getLogger("helmis-memory")

DATA_DIR = os.environ.get("DATA_DIR", "/app/data" if os.path.exists("/app") else "./data")
TZ = ZoneInfo(os.environ.get("TZ", "Asia/Jakarta"))

_memory_lock = threading.RLock()
TASK_SCHEMA_VERSION = 1

_repository: TaskRepository | None = None
_repository_lock = threading.Lock()


def _resolve_data_dir() -> str:
    return os.environ.get("DATA_DIR", DATA_DIR)


def _resolve_db_path() -> str:
    override = os.environ.get("HELMIS_DB_PATH")
    if override:
        return str(override)
    return os.path.join(_resolve_data_dir(), "helmis.db")


def get_repository() -> TaskRepository:
    """Return the process-wide task repository."""
    global _repository
    db_path = _resolve_db_path()
    with _repository_lock:
        if _repository is None or _repository.database_path != db_path:
            _repository = TaskRepository(db_path)
    return _repository


def identity_key(value: str) -> str:
    """Return a stable, generic semantic key for a task identity."""
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    normalized = re.sub(r"[^\w\s]+", " ", normalized, flags=re.UNICODE)
    return re.sub(r"\s+", " ", normalized).strip()


def _new_task_id() -> str:
    return str(uuid.uuid4())


def _bump_task_version(task: dict[str, Any]) -> None:
    """Advance the optimistic-concurrency version after a mutation."""
    task["version"] = max(1, int(task.get("version") or 1)) + 1
    task["updated_at"] = get_current_time_str()


def _get_memory_file() -> str:
    """Return the deferred JSON sidecar path from the current data directory."""
    return os.path.join(_resolve_data_dir(), "helmis_memory.json")


def _ensure_data_dir() -> None:
    """Ensure data directory exists."""
    os.makedirs(os.path.dirname(_get_memory_file()), exist_ok=True)


def _default_people() -> dict[str, Any]:
    """Env-seeded core directory (Gilang/Bunga).

    Used as defaults on first boot AND as fallback when the sidecar's people
    record is empty — an old sidecar without `people` must never disable
    recipient resolution for proactive reminders.
    """
    return {
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
    }


def load_memory() -> dict[str, Any]:
    """Load memory: tasks from SQLite, people/notes/activity from JSON."""
    _ensure_data_dir()
    default_memory: dict[str, Any] = {
        "schedules": [],
        "people": _default_people(),
        "notes": [],
    }

    mem_path = _get_memory_file()
    json_data: dict[str, Any] = {}
    if os.path.exists(mem_path):
        try:
            with open(mem_path, encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                json_data = loaded
        except Exception as e:
            log.error("Failed to load memory file (%s): %s", mem_path, e)

    mem: dict[str, Any] = {**default_memory, **json_data}
    if not mem.get("people"):
        mem["people"] = _default_people()
    mem["tasks"] = get_repository().list_tasks()
    return cast(dict[str, Any], mem)


def save_memory(data: dict[str, Any]) -> None:
    """Persist deferred JSON records; task state is SQLite-only."""
    json_data = {k: v for k, v in data.items() if k not in ("tasks", "version")}
    _save_json_records(**json_data)


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
        greeting = "Selamat pagi"
    elif 12 <= hour < 15:
        greeting = "Selamat siang"
    elif 15 <= hour < 19:
        greeting = "Selamat sore"
    else:
        greeting = "Selamat malam"

    time_str = now.strftime("%A, %d %B %Y - %H:%M WIB")
    return time_str, greeting


def get_current_time_str() -> str:
    """Get current time formatted in WIB."""
    time_str, _ = get_time_of_day_info()
    return time_str


def _load_json_records(key: str, default: Any) -> Any:
    """Read one non-task record collection from the JSON sidecar file."""
    mem_path = _get_memory_file()
    if not os.path.exists(mem_path):
        return default
    try:
        with open(mem_path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data.get(key, default)
    except Exception as e:
        log.error("Failed to read %s from memory file (%s): %s", key, mem_path, e)
    return default


def _save_json_records(**updates: Any) -> None:
    """Merge non-task record collections into the JSON sidecar file."""
    mem_path = _get_memory_file()
    with _memory_lock:
        existing: dict[str, Any] = {}
        if os.path.exists(mem_path):
            try:
                with open(mem_path, encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    existing = loaded
            except Exception as e:
                log.error("Failed to read memory file for merge (%s): %s", mem_path, e)
        existing.update(updates)
        _save_memory_unlocked(existing)


def get_memory_context_summary() -> str:
    """Format temporal context for the agent prompt without leaking static database dumps."""
    activity_log = cast(
        list[dict[str, Any]], _load_json_records("activity_log", [])
    )
    now_str, period_info = get_time_of_day_info()

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
    entry = {
        "time": get_current_time_str(),
        "summary": summary.strip(),
    }
    log_list = cast(
        list[dict[str, Any]], _load_json_records("activity_log", [])
    )
    log_list.append(entry)
    _save_json_records(activity_log=log_list[-50:])


# Routine/attendance titles: recurring check-ins that are not real work.
# Matches Indonesian + English attendance/class/periodic-checkin patterns.
_ROUTINE_TITLE_PATTERN = re.compile(
    r"\b(?:"
    r"absen(?:\s+\w+)*|"
    r"kehadiran|attendance|"
    r"\babsensi\b|"
    r"(?<!mata\s)(?<!kuliah\s)\bkuliah\b|kelas\b|class\b|"
    r"check[- ]?in\b|checkin\b|"
    r"presensi\b"
    r")",
    re.IGNORECASE,
)

# Real-work verbs: "membuat PPT untuk mata kuliah X" is work even though it
# mentions a course; "Kuliah X" (attendance) is routine.
_WORK_VERB_PATTERN = re.compile(
    r"\b(?:membuat|buat(?:in|kan)?|bikin(?:in|kan)?|mengerjakan|kerjakan|"
    r"mengisi|isi(?:n|in)?|menyelesaikan|mengumpulkan|membaca|mempelajari)\b",
    re.IGNORECASE,
)


def _detect_task_category(title: str, recurrence: dict[str, Any] | None) -> str:
    """Auto-classify a task into 'routine' vs 'work'.

    Routine = recurring attendance/check-in pings (absen kuliah, weekly
    check-ins). Everything else is real work. Recurrence alone does NOT make
    a task routine — a recurring work item ("rekap mingguan") stays work.
    Work verbs (buat/kerjakan/isi...) beat routine keywords: "membuat PPT
    untuk mata kuliah X" is an assignment, not attendance.
    """
    title_l = (title or "").strip()
    if _WORK_VERB_PATTERN.search(title_l):
        return "work"
    if _ROUTINE_TITLE_PATTERN.search(title_l):
        return "routine"
    return "work"


def add_task(
    title: str,
    due: str = "",
    assignee: str = "Gilang",
    priority: str = "normal",
    lead_time_minutes: int = 0,
    task_type: str = "reminder",
    job: dict[str, Any] | None = None,
    *,
    identity_key_value: str | None = None,
    recurrence: dict[str, Any] | None = None,
    recurrence_policy: dict[str, Any] | None = None,
    nag_interval_minutes: int = 10,
    max_nags: int = 6,
    nag_policy: dict[str, Any] | None = None,
    category: str = "",
) -> dict[str, Any]:
    """Add a task, updating only an identical pending semantic key.

    ``identity_key_value`` is optional for backwards compatibility and allows
    callers to distinguish two tasks with the same display title.
    ``category`` separates real work ('work'/'personal'/'shared') from
    recurring attendance pings ('routine') so task overviews stay clean.
    """
    if not title or not title.strip():
        raise ValueError("Task title cannot be empty")
    clean_title = title.strip()
    clean_due = due.strip() if due else "No deadline"
    clean_assignee = assignee.strip() if assignee else "Gilang"
    clean_priority = priority.strip().lower() if priority else "normal"
    if clean_priority not in ("urgent", "normal", "low"):
        clean_priority = "normal"
    clean_lead = max(0, int(lead_time_minutes or 0))
    clean_identity = identity_key(identity_key_value or clean_title)
    clean_recurrence = (
        recurrence if isinstance(recurrence, dict)
        else recurrence_policy if isinstance(recurrence_policy, dict)
        else None
    )
    supplied_nag = nag_policy if isinstance(nag_policy, dict) else {}
    try:
        clean_nag_interval = max(
            1,
            int(supplied_nag.get("interval_minutes", nag_interval_minutes or 10)),
        )
        clean_max_nags = max(0, int(supplied_nag.get("max_nags", max_nags)))
    except (TypeError, ValueError) as exc:
        raise ValueError("Nag interval and max_nags must be numeric") from exc

    clean_task_type = str(task_type).strip().lower() if task_type else "reminder"
    if clean_assignee.lower() == "helmis" or job or clean_task_type in ("scheduled_action", "action", "bot"):
        clean_task_type = "scheduled_action"
        clean_assignee = "Helmis"
        clean_lead = 0

    clean_category = str(category or "").strip().lower()
    if clean_category not in ("routine", "work", "personal", "shared"):
        clean_category = _detect_task_category(clean_title, clean_recurrence)

    repo = get_repository()
    now_str = get_current_time_str()
    payload: dict[str, Any] = {
        "title": clean_title,
        "identity_key": clean_identity,
        "due": clean_due,
        "assignee": clean_assignee,
        "priority": clean_priority,
        "lead_time_minutes": clean_lead,
        "task_type": clean_task_type,
        "category": clean_category,
        "recurrence": clean_recurrence,
        "recurrence_policy": clean_recurrence,
        "nag_interval_minutes": clean_nag_interval,
        "max_nags": clean_max_nags,
        "nag_policy": {
            **{k: v for k, v in supplied_nag.items() if k not in ("interval_minutes", "max_nags")},
            "interval_minutes": clean_nag_interval,
            "max_nags": clean_max_nags,
        },
        "nag_enabled": clean_priority == "urgent" or nag_policy is not None,
    }
    if job is not None:
        payload["job"] = job

    def matcher(candidate: dict[str, Any]) -> bool:
        return identity_key(str(candidate.get("identity_key") or candidate.get("title", ""))) == clean_identity

    def new_record() -> dict[str, Any]:
        return {
            **payload,
            "task_id": _new_task_id(),
            "status": "pending",
            "version": TASK_SCHEMA_VERSION,
            "schema_version": TASK_SCHEMA_VERSION,
            "kickoff_reminded": False,
            "due_reminded": False,
            "nudge_count": 0,
            "last_nudged_at": None,
            "nudge_stopped": False,
            "retry_count": 0,
            "max_retries": 3,
            "execution_status": "pending",
            "created_at": now_str,
            "updated_at": None,
            "completed_at": None,
        }

    return repo.upsert_pending_identity(payload, matcher, new_record)


def _matching_tasks(
    tasks: list[dict[str, Any]],
    *,
    title: str = "",
    task_id: str | None = None,
    identity_key_value: str | None = None,
    include_completed: bool = True,
) -> list[dict[str, Any]]:
    """Resolve task candidates without silently guessing across fuzzy matches."""
    eligible = [
        task
        for task in tasks
        if include_completed or str(task.get("status", "")).lower() != "completed"
    ]
    # An ID is an exact selector and does not require a title or identity key.
    if task_id:
        return [task for task in eligible if str(task.get("task_id")) == task_id]

    selector = identity_key_value or title
    if not selector or not selector.strip():
        return []
    query = identity_key(selector)

    if identity_key_value:
        return [
            task
            for task in eligible
            if identity_key(str(task.get("identity_key") or task.get("title", ""))) == query
        ]

    exact = [task for task in eligible if identity_key(str(task.get("title", ""))) == query]
    if exact:
        return exact
    return [
        task
        for task in eligible
        if query in identity_key(str(task.get("title", "")))
    ]


def update_task(
    title: str = "",
    new_title: str | None = None,
    new_due: str | None = None,
    new_assignee: str | None = None,
    new_status: str | None = None,
    new_priority: str | None = None,
    new_lead_time_minutes: int | None = None,
    new_task_type: str | None = None,
    new_job: dict[str, Any] | None = None,
    *,
    task_id: str | None = None,
    expected_version: int | None = None,
    identity_key_value: str | None = None,
    recurrence: dict[str, Any] | None = None,
    nag_interval_minutes: int | None = None,
    max_nags: int | None = None,
    nag_policy: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Update one task only when the selector resolves unambiguously."""
    repo = get_repository()
    result = repo.mutate_one(
        lambda tasks: _matching_tasks(
            tasks, title=title, task_id=task_id, identity_key_value=identity_key_value
        ),
        expected_version,
        _apply_task_update(
            new_title=new_title,
            identity_key_value=identity_key_value,
            new_due=new_due,
            new_assignee=new_assignee,
            new_status=new_status,
            new_priority=new_priority,
            new_lead_time_minutes=new_lead_time_minutes,
            new_task_type=new_task_type,
            new_job=new_job,
            recurrence=recurrence,
            nag_interval_minutes=nag_interval_minutes,
            max_nags=max_nags,
            nag_policy=nag_policy,
        ),
    )
    return result.get("task") if result.get("outcome") == "committed" else None


def _apply_task_update(
    *,
    new_title: str | None = None,
    identity_key_value: str | None = None,
    new_due: str | None = None,
    new_assignee: str | None = None,
    new_status: str | None = None,
    new_priority: str | None = None,
    new_lead_time_minutes: int | None = None,
    new_task_type: str | None = None,
    new_job: dict[str, Any] | None = None,
    recurrence: dict[str, Any] | None = None,
    nag_interval_minutes: int | None = None,
    max_nags: int | None = None,
    nag_policy: dict[str, Any] | None = None,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Build a mutator that applies field updates to one task record."""

    def mutator(target_task: dict[str, Any]) -> dict[str, Any]:
        if new_title:
            target_task["title"] = new_title.strip()
            if not identity_key_value:
                target_task["identity_key"] = identity_key(target_task["title"])
        if new_due:
            target_task["due"] = new_due.strip()
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
            target_task["priority"] = new_priority.strip().lower()
            target_task["nag_enabled"] = target_task["priority"] == "urgent"
        if new_lead_time_minutes is not None:
            target_task["lead_time_minutes"] = max(0, new_lead_time_minutes)
        if new_task_type:
            target_task["task_type"] = new_task_type.strip().lower()
        if new_job is not None:
            target_task["job"] = new_job
        if recurrence is not None:
            target_task["recurrence"] = recurrence
            target_task["recurrence_policy"] = recurrence
        if nag_interval_minutes is not None:
            target_task["nag_interval_minutes"] = max(1, nag_interval_minutes)
        if max_nags is not None:
            target_task["max_nags"] = max(0, max_nags)
        if nag_policy is not None:
            target_task["nag_policy"] = dict(nag_policy)
        target_task["updated_at"] = get_current_time_str()
        return target_task

    return mutator


def update_task_result(**kwargs: Any) -> dict[str, Any]:
    """Return a lossless, model-facing result for a single task mutation."""
    title = str(kwargs.get("title") or "")
    task_id = str(kwargs.get("task_id") or "").strip() or None
    identity_value = kwargs.get("identity_key_value")
    identity_value = str(identity_value).strip() if identity_value else None
    if not task_id and not title.strip() and not identity_value:
        return {
            "status": "error",
            "outcome": "failed",
            "error": "A non-empty task selector is required.",
        }

    new_priority = kwargs.get("new_priority")
    if new_priority is not None and str(new_priority).strip().lower() not in ("urgent", "normal", "low"):
        return {
            "status": "error",
            "outcome": "failed",
            "error": "Priority must be urgent, normal, or low.",
        }

    expected_version = kwargs.get("expected_version")
    expected_version = int(expected_version) if expected_version is not None else None

    result = get_repository().mutate_one(
        lambda tasks: _matching_tasks(
            tasks, title=title, task_id=task_id, identity_key_value=identity_value
        ),
        expected_version,
        _apply_task_update(
            new_title=kwargs.get("new_title"),
            identity_key_value=identity_value,
            new_due=kwargs.get("new_due"),
            new_assignee=kwargs.get("new_assignee"),
            new_status=kwargs.get("new_status"),
            new_priority=new_priority,
            new_lead_time_minutes=kwargs.get("new_lead_time_minutes"),
            new_task_type=kwargs.get("new_task_type"),
            new_job=kwargs.get("new_job") if isinstance(kwargs.get("new_job"), dict) else None,
            recurrence=kwargs.get("recurrence") if isinstance(kwargs.get("recurrence"), dict) else None,
            nag_interval_minutes=kwargs.get("nag_interval_minutes"),
            max_nags=kwargs.get("max_nags"),
            nag_policy=kwargs.get("nag_policy") if isinstance(kwargs.get("nag_policy"), dict) else None,
        ),
    )
    outcome = str(result.get("outcome"))
    if outcome == "committed":
        task = cast(dict[str, Any], result.get("task"))
        return {
            "status": "applied",
            "outcome": "committed",
            "task_id": result.get("task_id"),
            "affected_ids": result.get("affected_ids"),
            "before": result.get("before"),
            "after": task,
            "task": task,
        }
    status = {"not_found": "not_found", "ambiguous": "ambiguous", "conflict": "conflict"}.get(
        outcome, "failed"
    )
    return {"status": status, "outcome": outcome, **result}


def bulk_delete_tasks(
    *,
    task_id: str | None = None,
    identity_key_value: str | None = None,
    title_query: str | None = None,
    assignee: str | None = None,
    task_type: str | None = None,
    status: str = "pending",
) -> dict[str, Any]:
    """Delete explicitly scoped tasks and report every affected record."""
    if not (task_id or identity_key_value or (title_query and title_query.strip())):
        return {
            "status": "error",
            "outcome": "failed",
            "error": "A non-empty task scope is required.",
        }

    def resolver(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if task_id:
            return [task for task in tasks if str(task.get("task_id")) == task_id]
        query = identity_key(identity_key_value or title_query or "")
        matches: list[dict[str, Any]] = []
        for task in tasks:
            if status and status.lower() != "all" and str(task.get("status", "pending")).lower() != status.lower():
                continue
            candidate = identity_key(str(task.get("identity_key") or task.get("title", "")))
            # Canonical identities are exact scopes; title queries retain keyword matching.
            if identity_key_value:
                if candidate != query:
                    continue
            elif query not in candidate:
                continue
            if assignee and str(task.get("assignee", "")).casefold() != assignee.casefold():
                continue
            if task_type and str(task.get("task_type", "reminder")).casefold() != task_type.casefold():
                continue
            matches.append(task)
        return matches

    result = get_repository().delete_matching(resolver)
    outcome = str(result.get("outcome"))
    if outcome == "committed":
        return {
            "status": "applied",
            "outcome": "committed",
            "deleted_count": result.get("deleted_count", 0),
            "affected_ids": result.get("affected_ids", []),
            "deleted": result.get("deleted", []),
        }
    return {"status": outcome, "outcome": outcome, **result}


def complete_task_result(
    *,
    task_id: str | None = None,
    title: str = "",
    identity_key_value: str | None = None,
    expected_version: int | None = None,
) -> dict[str, Any]:
    """Complete one task only when the selector is unambiguous and current."""
    if not task_id and not title.strip() and not (identity_key_value and identity_key_value.strip()):
        return {
            "status": "error",
            "outcome": "failed",
            "error": "A non-empty task selector is required.",
        }

    result = get_repository().mutate_one(
        lambda tasks: _matching_tasks(
            tasks,
            title=title,
            task_id=task_id,
            identity_key_value=identity_key_value,
            include_completed=False,
        ),
        expected_version,
        _complete_task_mutator,
    )
    outcome = str(result.get("outcome"))
    if outcome == "committed":
        task = cast(dict[str, Any], result.get("task"))
        return {
            "status": "applied",
            "outcome": "committed",
            "task_id": result.get("task_id"),
            "affected_ids": result.get("affected_ids"),
            "before": result.get("before"),
            "after": task,
            "task": task,
        }
    status = {"not_found": "not_found", "ambiguous": "ambiguous", "conflict": "conflict"}.get(
        outcome, "failed"
    )
    return {"status": status, "outcome": outcome, **result}


def _complete_task_mutator(task: dict[str, Any]) -> dict[str, Any]:
    """Mark one task completed inside the repository transaction."""
    task["status"] = "completed"
    task["completed_at"] = get_current_time_str()
    task["updated_at"] = get_current_time_str()
    return task


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
    include_routine: bool = False,
) -> list[dict[str, Any]]:
    """
    List tasks filtered by status ('pending', 'completed', 'all') and task_type ('all', 'reminder', 'scheduled_action').

    By default routine attendance pings ('absen kuliah', recurring check-ins)
    are EXCLUDED — "list my tasks" means real work. Pass
    include_routine=True for the full roster (explicit routine asks,
    scheduler ticks).

    Default sort order is by urgency (earliest deadline first, no-deadline items last).
    """
    tasks = get_repository().list_tasks()
    filtered = tasks if status == "all" else [t for t in tasks if t.get("status") == status]

    if task_type != "all":
        clean_tt = task_type.strip().lower()
        filtered = [t for t in filtered if t.get("task_type", "reminder") == clean_tt]

    if not include_routine:
        filtered = [t for t in filtered if _detect_task_category(str(t.get("title", "")), t.get("recurrence")) == "work"]

    if sort_by == "urgency":
        return sorted(filtered, key=lambda t: parse_due_timestamp(t.get("due", "")))
    elif sort_by == "created":
        return sorted(filtered, key=lambda t: str(t.get("created_at", "")), reverse=True)
    elif sort_by == "alphabetical":
        return sorted(filtered, key=lambda t: str(t.get("title", "")).lower())
    return filtered


def fetch_tickable_tasks() -> list[dict[str, Any]]:
    """Return scheduler-eligible tasks directly from the task repository."""
    return get_repository().fetch_tickable_tasks()


def update_task_fields(
    task_id: str,
    fields: dict[str, Any],
    *,
    expected_version: int | None = None,
) -> dict[str, Any]:
    """Persist scheduler lifecycle fields with exact-ID optimistic concurrency."""
    return get_repository().update_task_fields(task_id, fields, expected_version=expected_version)



def add_person(name: str, phone: str = "", role: str = "", notes: str = "") -> dict[str, Any]:
    """Add or update person in directory."""
    if not name or not name.strip():
        raise ValueError("Person name cannot be empty")
    people = cast(dict[str, Any], _load_json_records("people", {}))
    if not people:
        # Seed from env defaults so a core principal is never lost by an edit
        # to an unrelated contact.
        people = _default_people()
    person_data = {
        "phone": phone.strip(),
        "role": role.strip(),
        "notes": notes.strip(),
        "updated_at": get_current_time_str(),
    }
    people[name.strip()] = person_data
    _save_json_records(people=people)
    return {"name": name.strip(), **person_data}


def get_person(name: str) -> dict[str, Any] | None:
    """Find a person in directory by name substring."""
    people = cast(dict[str, Any], _load_json_records("people", {}))
    if not people:
        people = _default_people()
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
    notes = cast(list[dict[str, Any]], _load_json_records("notes", []))

    # Update existing note if same title
    for n in notes:
        if n.get("title", "").lower() == clean_title.lower():
            n["content"] = clean_content
            n["updated_at"] = get_current_time_str()
            _save_json_records(notes=notes)
            return cast(dict[str, Any], n)

    note_data = {
        "title": clean_title,
        "content": clean_content,
        "created_at": get_current_time_str(),
        "updated_at": get_current_time_str(),
    }
    notes.append(note_data)
    _save_json_records(notes=notes)
    return note_data


def get_note(title: str) -> dict[str, Any] | None:
    """Find a note in memory by title keyword or substring match."""
    if not title or not title.strip():
        return None
    notes = cast(list[dict[str, Any]], _load_json_records("notes", []))
    q = title.lower().strip()
    for n in notes:
        if q in n.get("title", "").lower():
            return cast(dict[str, Any], n)
    return None


def list_notes() -> list[dict[str, Any]]:
    """List all stored notes with their titles and full contents."""
    return cast(list[dict[str, Any]], _load_json_records("notes", []))


def append_to_note(title: str, addition: str) -> dict[str, Any]:
    """Append text or list items to an existing note, or create it if not found."""
    if not title or not title.strip():
        raise ValueError("Judul catatan tidak boleh kosong")
    if not addition or not addition.strip():
        raise ValueError("Teks tambahan tidak boleh kosong")

    clean_title = title.strip()
    clean_addition = addition.strip()
    notes = cast(list[dict[str, Any]], _load_json_records("notes", []))

    for n in notes:
        if clean_title.lower() in n.get("title", "").lower():
            existing_content = str(n.get("content", "")).rstrip()
            if existing_content:
                n["content"] = f"{existing_content}\n{clean_addition}"
            else:
                n["content"] = clean_addition
            n["updated_at"] = get_current_time_str()
            _save_json_records(notes=notes)
            return cast(dict[str, Any], n)

    # Note did not exist, create new
    note_data = {
        "title": clean_title,
        "content": clean_addition,
        "created_at": get_current_time_str(),
        "updated_at": get_current_time_str(),
    }
    notes.append(note_data)
    _save_json_records(notes=notes)
    return note_data


def delete_note(title: str) -> dict[str, Any]:
    """Delete a note from memory by title substring."""
    if not title or not title.strip():
        return {"status": "error", "error": "Judul catatan tidak boleh kosong."}
    notes = cast(list[dict[str, Any]], _load_json_records("notes", []))
    q = title.lower().strip()
    initial_len = len(notes)
    kept = [n for n in notes if q not in n.get("title", "").lower()]
    if len(kept) < initial_len:
        _save_json_records(notes=kept)
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
