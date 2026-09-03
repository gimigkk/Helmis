"""
schedules.py — Tool Handlers for Generic Schedule and Reminder-Policy Records.

Deterministic routing target: schedule questions must be answered from schedule
records, never by improvising over task lists.
"""

import uuid
from typing import Any

from ..memory.task_repository import TaskRepository
from .registry import register_tool


def _repo() -> TaskRepository:
    from ..memory.store import get_repository

    return get_repository()


@register_tool("list_schedules")
def handle_list_schedules(args: dict[str, Any]) -> dict[str, Any]:
    task_id = str(args.get("task_id") or "").strip() or None
    include_inactive = bool(args.get("include_inactive", False))
    schedules = _repo().list_schedules(task_id=task_id, active_only=not include_inactive)
    return {
        "status": "success",
        "count": len(schedules),
        "schedules": schedules,
    }


@register_tool("create_schedule")
async def handle_create_schedule(args: dict[str, Any]) -> dict[str, Any]:
    starts_raw = str(args.get("starts_at", "")).strip()
    timezone = str(args.get("timezone", "")).strip()
    if not starts_raw or not timezone:
        return {
            "status": "error",
            "outcome": "invalid_arguments",
            "error": "create_schedule butuh starts_at dan timezone.",
        }
    try:
        starts_at = float(starts_raw)
    except ValueError as exc:
        return {
            "status": "error",
            "outcome": "failed",
            "error": f"starts_at harus epoch seconds numerik: {exc}",
        }

    task_id = str(args.get("task_id") or "").strip() or None
    recurrence = args.get("recurrence") if isinstance(args.get("recurrence"), dict) else None
    schedule_id = f"sched_{uuid.uuid4().hex[:12]}"
    record = _repo().create_schedule(
        schedule_id,
        starts_at=starts_at,
        timezone=timezone,
        task_id=task_id,
        recurrence=recurrence,
        owner=str(args.get("owner") or "").strip(),
        source=str(args.get("source", "user")),
        location=str(args.get("location") or "").strip() or None,
    )
    return {
        "status": "success",
        "outcome": "committed",
        "schedule_id": schedule_id,
        "schedule": record,
        "message": f"Jadwal tersimpan (mulai {starts_at:.0f} epoch, tz {timezone}).",
    }


@register_tool("list_reminder_policies")
def handle_list_reminder_policies(args: dict[str, Any]) -> dict[str, Any]:
    task_id = str(args.get("task_id") or "").strip() or None
    schedule_id = str(args.get("schedule_id") or "").strip() or None
    policies = _repo().list_reminder_policies(task_id=task_id, schedule_id=schedule_id)
    return {"status": "success", "count": len(policies), "policies": policies}
