"""
skills.py — Dynamic On-Demand Skill Loader for Helmis.
"""

import logging
import os
import re
from typing import Any

from ..memory.store import log_activity
from ..whatsapp.client import WahaClient
from .registry import register_tool

log = logging.getLogger("helmis-tools-skills")


def _get_skills_dir() -> str:
    """Find the root directory for skills."""
    candidates = [
        os.environ.get("SKILLS_DIR", ""),
        "/app/config/skills",
        "/hermes-config/skills",
        "config/skills",
        "../config/skills",
        os.path.join(os.path.dirname(__file__), "../../../config/skills"),
    ]
    for d in candidates:
        if d and os.path.exists(d) and os.path.isdir(d):
            return os.path.abspath(d)
    return ""


def list_available_skills() -> list[dict[str, str]]:
    """Discover all available skills and their summaries."""
    skills_dir = _get_skills_dir()
    if not skills_dir or not os.path.exists(skills_dir):
        return []

    available: list[dict[str, str]] = []
    for entry in sorted(os.listdir(skills_dir)):
        entry_path = os.path.join(skills_dir, entry)
        if os.path.isdir(entry_path):
            skill_file = os.path.join(entry_path, "SKILL.md")
            if os.path.exists(skill_file):
                desc = "Specialized domain skill playbook."
                try:
                    with open(skill_file, encoding="utf-8") as f:
                        txt = f.read(1024)
                        m = re.search(r"description:\s*(.+)", txt, re.IGNORECASE)
                        if m:
                            desc = m.group(1).strip()
                except Exception:
                    pass
                available.append({"name": entry, "description": desc})
    return available


@register_tool("load_skill")
async def handle_load_skill(
    args: dict[str, Any],
    default_sender: str,
    client: WahaClient | None = None,
) -> dict[str, Any]:
    """
    Dynamically load the complete operational playbook for a specialized domain skill.
    """
    name = str(args.get("name") or args.get("skill_name") or "").strip().lower()
    if not name:
        available = list_available_skills()
        return {
            "status": "error",
            "error": "Nama skill tidak boleh kosong.",
            "available_skills": [s["name"] for s in available],
        }

    skills_dir = _get_skills_dir()
    if not skills_dir:
        return {"status": "error", "error": "Direktori config/skills tidak ditemukan."}

    # Normalize skill name (e.g. "pdf_toolkit" -> "pdf-toolkit")
    normalized_name = name.replace("_", "-")
    skill_file = os.path.join(skills_dir, normalized_name, "SKILL.md")

    if not os.path.exists(skill_file):
        available = list_available_skills()
        return {
            "status": "error",
            "error": f"Skill '{name}' tidak ditemukan di sistem.",
            "available_skills": [s["name"] for s in available],
        }

    try:
        with open(skill_file, encoding="utf-8") as f:
            content = f.read()

        # Clean YAML frontmatter for clean model reading
        clean_content = re.sub(r"^---\n.*?\n---\n+", "", content, flags=re.DOTALL).strip()

        log_activity(f"Loaded on-demand skill: {normalized_name}")
        return {
            "status": "success",
            "skill": normalized_name,
            "playbook": clean_content,
            "message": f"Skill *{normalized_name}* berhasil dimuat ke konteks operasional.",
        }
    except Exception as ex:
        log.warning("Failed to load skill %s: %s", normalized_name, ex)
        return {"status": "error", "error": f"Gagal membaca playbook skill: {ex}"}
