"""One-time import of JSON task archives into the SQLite task repository."""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from .task_repository import TaskRepository


def _stable_import_id(task: dict[str, Any], index: int) -> str:
    fields = "|".join(str(task.get(field, "")) for field in ("title", "due", "assignee", "created_at", "status"))
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"helmis:imported-task:{index}:{fields}"))


def _normalize(task: Any, index: int) -> dict[str, Any]:
    record = dict(task) if isinstance(task, dict) else {"title": str(task or "")}
    title = str(record.get("title") or "").strip()
    record.setdefault("task_id", _stable_import_id(record, index))
    record["title"] = title
    record.setdefault("identity_key", " ".join(title.casefold().split()))
    record.setdefault("status", "pending")
    record.setdefault("version", 1)
    return record


def migrate_json_tasks(
    source: str | os.PathLike[str], database: str | os.PathLike[str]
) -> dict[str, Any]:
    """Import tasks, verify counts, and archive the JSON source without deleting it."""
    source_path = Path(source)
    if not source_path.exists():
        return {"status": "skipped", "reason": "source_missing", "imported": 0}
    with source_path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    raw_tasks = payload.get("tasks", []) if isinstance(payload, dict) else []
    tasks = [_normalize(task, index) for index, task in enumerate(raw_tasks)]
    repository = TaskRepository(str(database))
    before = repository.list_tasks()
    repository.load_or_migrate(tasks)
    after = repository.list_tasks()
    imported_ids = {str(task["task_id"]) for task in tasks}
    stored_ids = {str(task["task_id"]) for task in after}
    if not imported_ids.issubset(stored_ids):
        raise RuntimeError("SQLite migration verification failed: imported task IDs are missing")
    archived = source_path.with_name(
        f"{source_path.name}.migrated-{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    )
    source_path.rename(archived)
    return {
        "status": "migrated", "imported": len(tasks),
        "database_rows": len(after), "previous_rows": len(before),
        "archived_source": str(archived),
    }


def main() -> None:
    data_dir = Path(os.environ.get("DATA_DIR", "./data"))
    source = Path(os.environ.get("MEMORY_FILE", data_dir / "helmis_memory.json"))
    database = Path(os.environ.get("HELMIS_DB_PATH", data_dir / "helmis.db"))
    print(json.dumps(migrate_json_tasks(source, database), ensure_ascii=False))


if __name__ == "__main__":
    main()
