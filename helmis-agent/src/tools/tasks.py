"""
tasks.py — Tool Handlers for Task & Reminder Lifecycle Management.
"""

from typing import Any

from ..memory.store import (
    add_task,
    bulk_delete_tasks,
    complete_task_result,
    list_tasks,
    update_task_result,
)
from ..whatsapp.client import WahaClient
from .registry import register_tool


@register_tool("add_task")
async def handle_add_task(
    args: dict[str, Any],
    default_sender: str,
    client: WahaClient | None = None,
) -> dict[str, Any]:
    title = str(args.get("title", "")).strip()
    due = str(args.get("due", "")).strip()
    assignee = str(args.get("assignee") or default_sender).strip()
    priority = str(args.get("priority", "normal")).strip().lower()
    lead_time = int(args.get("lead_time_minutes", 0) or 0)
    task_type = str(args.get("task_type", "reminder")).strip().lower()
    job = args.get("job")
    identity = args.get("identity_key") or args.get("identity_key_value")
    recurrence = args.get("recurrence") or args.get("recurrence_policy")
    nag_policy = args.get("nag_policy")
    try:
        nag_interval = int(args.get("nag_interval_minutes", 10) or 10)
        max_nags = int(args.get("max_nags", 6) or 6)
    except (TypeError, ValueError):
        return {
            "status": "error",
            "error": "nag_interval_minutes dan max_nags harus berupa angka.",
        }

    if not title:
        return {
            "status": "error",
            "error": "Judul task tidak boleh kosong.",
            "help_needed": "Minta user menyebutkan nama task atau aksi yang ingin dicatat/dijadwalkan.",
        }

    try:
        task = add_task(
            title=title,
            due=due,
            assignee=assignee,
            priority=priority,
            lead_time_minutes=lead_time,
            task_type=task_type,
            job=job if isinstance(job, dict) else None,
            identity_key_value=str(identity).strip() if identity else None,
            recurrence=recurrence if isinstance(recurrence, dict) else None,
            nag_interval_minutes=nag_interval,
            max_nags=max_nags,
            nag_policy=nag_policy if isinstance(nag_policy, dict) else None,
        )
    except ValueError as exc:
        return {"status": "error", "outcome": "failed", "error": str(exc)}

    # If scheduled action due in near horizon (<=10m), spawn exact-second in-process timer
    if task.get("task_type") == "scheduled_action" or task.get("assignee") == "Helmis":
        from ..agent.proactive import spawn_near_horizon_timer
        spawn_near_horizon_timer(task, client)

    p_info = f", Priority: {priority}" if priority != "normal" else ""
    lead_info = f", Lead buffer: {lead_time}m" if lead_time else ""
    type_label = "Aksi terjadwal" if task.get("task_type") == "scheduled_action" else "Task"
    return {
        "status": "success",
        "outcome": "committed",
        "task_id": task.get("task_id"),
        "affected_ids": [task.get("task_id")],
        "task": task,
        "message": f"{type_label} '{title}' berhasil disimpan dengan jadwal/deadline '{due}' untuk {task.get('assignee', assignee)}{p_info}{lead_info}.",
    }


@register_tool("list_tasks")
def handle_list_tasks(args: dict[str, Any]) -> dict[str, Any]:
    status = str(args.get("status", "pending"))
    sort_by = str(args.get("sort_by", "urgency"))
    task_type = str(args.get("task_type", "all"))
    tasks = list_tasks(status=status, sort_by=sort_by, task_type=task_type)
    return {"status": "success", "count": len(tasks), "sorted_by": sort_by, "task_type": task_type, "tasks": tasks}


@register_tool("complete_task")
def handle_complete_task(args: dict[str, Any]) -> dict[str, Any]:
    title = str(args.get("title") or "").strip()
    task_id = str(args.get("task_id", "")).strip() or None
    identity = args.get("identity_key") or args.get("identity_key_value")
    try:
        expected_version = int(args["expected_version"]) if args.get("expected_version") is not None else None
    except (TypeError, ValueError):
        return {"status": "error", "outcome": "failed", "error": "expected_version harus berupa angka."}
    result = complete_task_result(
        title=title,
        task_id=task_id,
        identity_key_value=str(identity).strip() if identity else None,
        expected_version=expected_version,
    )

    if result["status"] == "applied":
        task = result.get("task") or {}
        return {
            **result,
            "status": "success",
            "task_id": result.get("task_id") or task.get("task_id"),
            "task": task,
            "message": f"Task '{task.get('title')}' berhasil ditandai selesai.",
        }
    if result["status"] == "ambiguous":
        return {
            **result,
            "error": "Beberapa task cocok. Pilih task_id yang tepat agar tidak salah menandai.",
        }
    if result["status"] == "not_found":
        return {
            **result,
            "error": f"Tidak ditemukan task dengan nama '{title or task_id or identity or ''}'.",
            "help_needed": "Tanyakan judul task yang tepat kepada user.",
        }
    return result



@register_tool("update_task")
def handle_update_task(args: dict[str, Any]) -> dict[str, Any]:
    title = str(args.get("title", "")).strip()
    task_id = str(args.get("task_id", "")).strip() or None
    new_title = args.get("new_title")
    new_due = args.get("new_due")
    new_assignee = args.get("new_assignee")
    new_priority = args.get("new_priority")
    new_lead_time = args.get("new_lead_time_minutes")
    new_task_type = args.get("new_task_type")
    new_job = args.get("new_job")
    recurrence = args.get("recurrence") or args.get("recurrence_policy")
    identity = args.get("identity_key") or args.get("identity_key_value")
    try:
        new_interval = int(args["nag_interval_minutes"]) if args.get("nag_interval_minutes") is not None else None
        new_max_nags = int(args["max_nags"]) if args.get("max_nags") is not None else None
        expected_version = int(args["expected_version"]) if args.get("expected_version") is not None else None
        new_lead_time_value = int(new_lead_time) if new_lead_time is not None else None
    except (TypeError, ValueError):
        return {"status": "error", "outcome": "failed", "error": "Nilai versi dan angka kebijakan harus berupa angka."}
    result = update_task_result(
        title=title,
        task_id=task_id,
        identity_key_value=str(identity).strip() if identity else None,
        expected_version=expected_version,
        new_title=str(new_title).strip() if new_title else None,
        new_due=str(new_due).strip() if new_due else None,
        new_assignee=str(new_assignee).strip() if new_assignee else None,
        new_status=str(args["new_status"]).strip() if args.get("new_status") else None,
        new_priority=str(new_priority).strip() if new_priority else None,
        new_lead_time_minutes=new_lead_time_value,
        new_task_type=str(new_task_type).strip() if new_task_type else None,
        new_job=new_job if isinstance(new_job, dict) else None,
        recurrence=recurrence if isinstance(recurrence, dict) else None,
        nag_interval_minutes=new_interval,
        max_nags=new_max_nags,
    )
    if result.get("outcome") == "committed":
        updated = result.get("after") or {}
        return {
            **result,
            "status": "success",
            "message": f"Task '{updated.get('title')}' berhasil diupdate (Assignee: {updated.get('assignee')}, Due: {updated.get('due')}, Priority: {updated.get('priority', 'normal')}).",
        }
    return result


@register_tool("delete_task")
def handle_delete_task(args: dict[str, Any]) -> dict[str, Any]:
    title = str(args.get("title", "")).strip()
    task_id = str(args.get("task_id", "")).strip() or None
    identity = args.get("identity_key") or args.get("identity_key_value")
    if task_id:
        result = bulk_delete_tasks(task_id=task_id)
    else:
        result = bulk_delete_tasks(
            identity_key_value=str(identity).strip() if identity else None,
            title_query=title or None,
            assignee=str(args["assignee"]).strip() if args.get("assignee") else None,
            task_type=str(args["task_type"]).strip() if args.get("task_type") else None,
            status=str(args.get("status", "pending")),
        )
    if result["status"] == "applied":
        return {
            **result,
            "status": "success",
            "deleted_count": result.get("deleted_count", 0),
            "deleted": result.get("deleted", []),
            "message": f"{result.get('deleted_count', 0)} task berhasil dihapus sesuai scope.",
        }
    return result


@register_tool("reconcile_tasks")
def handle_reconcile_tasks(args: dict[str, Any]) -> dict[str, Any]:
    """Apply a generic canonical identity policy to matching task rows."""
    identity = str(args.get("identity_key", "")).strip()
    if not identity:
        return {"status": "error", "error": "identity_key wajib diisi."}
    return bulk_delete_tasks(
        identity_key_value=identity,
        assignee=str(args["assignee"]).strip() if args.get("assignee") else None,
        task_type=str(args["task_type"]).strip() if args.get("task_type") else None,
        status=str(args.get("status", "pending")),
    )
