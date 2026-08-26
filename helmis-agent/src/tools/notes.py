"""
notes.py — Tool Handlers for Shared Notes, Memos, and Living Lists.
"""

from typing import Any

from ..memory.store import append_to_note, delete_note, get_note, list_notes, save_note
from .registry import register_tool


@register_tool("save_note")
def handle_save_note(args: dict[str, Any]) -> dict[str, Any]:
    title = str(args.get("title", "")).strip()
    content = str(args.get("content", "")).strip()
    if not title or not content:
        return {"status": "error", "error": "Judul dan isi catatan tidak boleh kosong."}
    note = save_note(title=title, content=content)
    return {
        "status": "success",
        "note": note,
        "message": f"Catatan '{title}' berhasil disimpan.",
    }


@register_tool("get_note")
def handle_get_note(args: dict[str, Any]) -> dict[str, Any]:
    title = str(args.get("title", "")).strip()
    if not title:
        return {"status": "error", "error": "Judul catatan tidak boleh kosong."}
    found_note = get_note(title)
    if found_note:
        return {"status": "success", "note": found_note}
    return {
        "status": "not_found",
        "error": f"Tidak ditemukan catatan dengan judul '{title}'.",
        "help_needed": "Gunakan 'list_notes' untuk melihat semua catatan yang tersimpan.",
    }


@register_tool("list_notes")
def handle_list_notes(args: dict[str, Any]) -> dict[str, Any]:
    notes = list_notes()
    return {"status": "success", "count": len(notes), "notes": notes}


@register_tool("append_to_note")
def handle_append_to_note(args: dict[str, Any]) -> dict[str, Any]:
    title = str(args.get("title", "")).strip()
    text = str(args.get("text") or args.get("addition") or "").strip()
    if not title or not text:
        return {
            "status": "error",
            "error": "Judul catatan dan teks tambahan tidak boleh kosong.",
        }
    appended = append_to_note(title=title, addition=text)
    return {
        "status": "success",
        "note": appended,
        "message": f"Berhasil menambahkan ke catatan '{appended.get('title')}'.",
    }


@register_tool("delete_note")
def handle_delete_note(args: dict[str, Any]) -> dict[str, Any]:
    title = str(args.get("title", "")).strip()
    return delete_note(title=title)
