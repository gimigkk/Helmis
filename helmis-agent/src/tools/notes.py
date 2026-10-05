"""
notes.py — Tool Handlers for Shared Notes, Memos, and Living Lists.
"""

import re
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


@register_tool("search_notes")
def handle_search_notes(args: dict[str, Any]) -> dict[str, Any]:
    query = str(args.get("query") or args.get("q") or "").strip().lower()
    if not query:
        return {"status": "error", "error": "Query pencarian catatan tidak boleh kosong."}
    all_notes = list_notes()
    matched = []
    q_words = set(re.findall(r"\w+", query))
    for n in all_notes:
        title = str(n.get("title", "")).lower()
        content = str(n.get("content", "")).lower()
        if query in title or query in content:
            matched.append(n)
        elif q_words and (len(q_words & set(re.findall(r"\w+", title))) >= 2 or len(q_words & set(re.findall(r"\w+", content))) >= 3):
            matched.append(n)
    return {
        "status": "success",
        "count": len(matched),
        "notes": matched,
        "query": query,
    }


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
