"""
contacts.py — Tool Handlers for Directory & Contacts Management.
"""

from typing import Any

from ..memory.store import add_person, get_person
from .registry import register_tool


@register_tool("add_person")
def handle_add_person(args: dict[str, Any]) -> dict[str, Any]:
    name = str(args.get("name", "")).strip()
    phone = str(args.get("phone", "")).strip()
    role = str(args.get("role", "")).strip()
    notes = str(args.get("notes", "")).strip()
    person = add_person(name=name, phone=phone, role=role, notes=notes)
    return {
        "status": "success",
        "person": person,
        "message": f"Kontak '{name}' berhasil disimpan.",
    }


@register_tool("get_person")
def handle_get_person(args: dict[str, Any]) -> dict[str, Any]:
    name = str(args.get("name", "")).strip()
    found_person = get_person(name)
    if found_person:
        return {"status": "success", "person": found_person}
    return {
        "status": "not_found",
        "error": f"Kontak '{name}' belum ada di direktori.",
        "help_needed": "Tanyakan detail kontak baru kepada user jika ingin disimpan.",
    }
