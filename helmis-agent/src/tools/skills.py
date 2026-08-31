"""
skills.py — Dynamic On-Demand Skill Loader for Helmis.
"""

import logging
import os
import re
from typing import Any

from ..memory.store import log_activity
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
    client: Any = None,
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


@register_tool("create_skill")
async def handle_create_skill(
    args: dict[str, Any],
    default_sender: str,
    client: Any = None,
) -> dict[str, Any]:
    """
    Create a new operational skill playbook on disk.
    This implements procedural memory: the agent can crystallize learned procedures
    into reusable SKILL.md files that persist across sessions and become part of
    the agent's active behavioral playbooks.
    """
    name = str(args.get("name") or "").strip().lower().replace(" ", "-").replace("_", "-")
    description = str(args.get("description") or "").strip()
    content = str(args.get("content") or "").strip()

    if not name:
        return {"status": "error", "error": "Nama skill tidak boleh kosong."}
    if not content:
        return {"status": "error", "error": "Konten/prosedur skill tidak boleh kosong."}

    # Sanitize name to prevent path traversal
    safe_name = re.sub(r"[^a-z0-9\-]", "", name)
    if not safe_name:
        return {"status": "error", "error": "Nama skill tidak valid setelah sanitasi."}

    skills_dir = _get_skills_dir()
    if not skills_dir:
        return {"status": "error", "error": "Direktori config/skills tidak ditemukan."}

    skill_dir_path = os.path.join(skills_dir, safe_name)
    skill_file = os.path.join(skill_dir_path, "SKILL.md")
    is_update = os.path.exists(skill_file)

    os.makedirs(skill_dir_path, exist_ok=True)

    skill_md = (
        f"---\n"
        f"name: {safe_name}\n"
        f"description: {description or 'Auto-created procedural skill.'}\n"
        f"---\n\n"
        f"{content}\n"
    )

    try:
        with open(skill_file, "w", encoding="utf-8") as f:
            f.write(skill_md)

        action = "diperbarui" if is_update else "dibuat"
        log_activity(f"Procedural skill '{safe_name}' {action} by agent (requested by {default_sender})")
        return {
            "status": "success",
            "skill": safe_name,
            "action": "updated" if is_update else "created",
            "message": f"Skill *{safe_name}* berhasil {action} dan akan aktif di sesi berikutnya.",
        }
    except Exception as ex:
        log.warning("Failed to create skill %s: %s", safe_name, ex)
        return {"status": "error", "error": f"Gagal menulis skill: {ex}"}


@register_tool("update_skill")
async def handle_update_skill(
    args: dict[str, Any],
    default_sender: str,
    client: Any = None,
) -> dict[str, Any]:
    """
    Update an existing skill playbook by appending or replacing content.
    """
    name = str(args.get("name") or "").strip().lower().replace(" ", "-").replace("_", "-")
    new_content = str(args.get("content") or "").strip()
    append = bool(args.get("append", False))

    if not name or not new_content:
        return {"status": "error", "error": "Nama skill dan konten baru tidak boleh kosong."}

    safe_name = re.sub(r"[^a-z0-9\-]", "", name)
    skills_dir = _get_skills_dir()
    if not skills_dir:
        return {"status": "error", "error": "Direktori config/skills tidak ditemukan."}

    skill_file = os.path.join(skills_dir, safe_name, "SKILL.md")
    if not os.path.exists(skill_file):
        # Delegate to create_skill if skill doesn't exist yet
        return await handle_create_skill(args, default_sender, client)

    try:
        with open(skill_file, encoding="utf-8") as f:
            existing = f.read()

        if append:
            updated = existing.rstrip() + "\n\n" + new_content + "\n"
        else:
            # Replace body content but preserve frontmatter
            frontmatter_match = re.match(r"^(---\n.*?\n---\n+)", existing, flags=re.DOTALL)
            frontmatter = frontmatter_match.group(1) if frontmatter_match else ""
            updated = frontmatter + new_content + "\n"

        with open(skill_file, "w", encoding="utf-8") as f:
            f.write(updated)

        log_activity(f"Procedural skill '{safe_name}' updated by agent (requested by {default_sender})")
        return {
            "status": "success",
            "skill": safe_name,
            "action": "appended" if append else "replaced",
            "message": f"Skill *{safe_name}* berhasil diperbarui.",
        }
    except Exception as ex:
        log.warning("Failed to update skill %s: %s", safe_name, ex)
        return {"status": "error", "error": f"Gagal memperbarui skill: {ex}"}


@register_tool("list_skills")
def handle_list_skills(args: dict[str, Any]) -> dict[str, Any]:
    """List all available skills with their descriptions."""
    available = list_available_skills()
    return {
        "status": "success",
        "count": len(available),
        "skills": available,
    }

