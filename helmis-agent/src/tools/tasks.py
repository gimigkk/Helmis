"""
tasks.py — Tool Handlers for Task & Reminder Lifecycle Management.
"""

from typing import Any

from ..memory import add_task, complete_task, delete_task, list_tasks, update_task
from .registry import register_tool


@register_tool("add_task")
def handle_add_task(args: dict[str, Any], default_sender: str) -> dict[str, Any]:
    title = str(args.get("title", "")).strip()
    due = str(args.get("due", "")).strip()
    assignee = str(args.get("assignee") or default_sender).strip()
    priority = str(args.get("priority", "normal")).strip().lower()
    lead_time = int(args.get("lead_time_minutes", 0) or 0)
    if not title:
        return {
            "status": "error",
            "error": "Judul task tidak boleh kosong.",
            "help_needed": "Minta user menyebutkan nama task yang ingin dicatat.",
        }
    task = add_task(
        title=title,
        due=due,
        assignee=assignee,
        priority=priority,
        lead_time_minutes=lead_time,
    )
    p_info = f", Priority: {priority}" if priority != "normal" else ""
    lead_info = f", Lead buffer: {lead_time}m" if lead_time else ""
    return {
        "status": "success",
        "task": task,
        "message": f"Task '{title}' berhasil disimpan dengan deadline '{due}' untuk {assignee}{p_info}{lead_info}.",
    }


@register_tool("list_tasks")
def handle_list_tasks(args: dict[str, Any]) -> dict[str, Any]:
    status = str(args.get("status", "pending"))
    sort_by = str(args.get("sort_by", "urgency"))
    tasks = list_tasks(status=status, sort_by=sort_by)
    return {"status": "success", "count": len(tasks), "sorted_by": sort_by, "tasks": tasks}


@register_tool("complete_task")
def handle_complete_task(args: dict[str, Any]) -> dict[str, Any]:
    title = str(args.get("title", "")).strip()
    completed = complete_task(title)
    if completed:
        return {
            "status": "success",
            "task": completed,
            "message": f"Task '{completed.get('title')}' berhasil ditandai selesai.",
        }
    return {
        "status": "not_found",
        "error": f"Tidak ditemukan task dengan nama '{title}'.",
        "help_needed": "Tanyakan judul task yang tepat kepada user.",
    }


@register_tool("update_task")
def handle_update_task(args: dict[str, Any]) -> dict[str, Any]:
    title = str(args.get("title", "")).strip()
    new_title = args.get("new_title")
    new_due = args.get("new_due")
    new_assignee = args.get("new_assignee")
    new_priority = args.get("new_priority")
    new_lead_time = args.get("new_lead_time_minutes")
    updated = update_task(
        title=title,
        new_title=str(new_title).strip() if new_title else None,
        new_due=str(new_due).strip() if new_due else None,
        new_assignee=str(new_assignee).strip() if new_assignee else None,
        new_priority=str(new_priority).strip() if new_priority else None,
        new_lead_time_minutes=int(new_lead_time) if new_lead_time is not None else None,
    )
    if updated:
        return {
            "status": "success",
            "task": updated,
            "message": f"Task '{updated.get('title')}' berhasil diupdate (Assignee: {updated.get('assignee')}, Due: {updated.get('due')}, Priority: {updated.get('priority', 'normal')}).",
        }
    return {
        "status": "not_found",
        "error": f"Tidak ditemukan task dengan nama '{title}'.",
    }


@register_tool("delete_task")
def handle_delete_task(args: dict[str, Any]) -> dict[str, Any]:
    title = str(args.get("title", "")).strip()
    deleted = delete_task(title)
    if deleted:
        return {
            "status": "success",
            "message": f"Task dengan kata kunci '{title}' berhasil dihapus.",
        }
    return {
        "status": "not_found",
        "error": f"Tidak ditemukan task dengan nama '{title}'.",
        "help_needed": "Tanyakan judul task yang tepat kepada user.",
    }
