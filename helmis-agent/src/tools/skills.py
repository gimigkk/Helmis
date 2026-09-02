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


def _get_proposals_dir() -> str:
    """Return the writable proposal store, never the active skill directory."""
    configured = os.environ.get("SKILL_PROPOSALS_DIR", "")
    if configured:
        return os.path.abspath(configured)
    data_dir = os.environ.get("DATA_DIR", "./data")
    return os.path.abspath(os.path.join(data_dir, "skill-proposals"))


def _validate_skill_content(name: str, description: str, content: str) -> str | None:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", name):
        return "Nama skill harus berupa slug alfanumerik maksimal 64 karakter."
    if len(description) > 500:
        return "Deskripsi skill terlalu panjang."
    if len(content) > 50_000:
        return "Konten skill terlalu besar."
    if "```" not in content and len(content) < 20:
        return "Konten skill terlalu pendek untuk menjadi playbook yang valid."
    return None


async def approve_skill_proposal(proposal: str, *, skills_dir: str | None = None) -> dict[str, Any]:
    """Promote one validated proposal into the active skill directory explicitly."""
    proposal_path = os.path.abspath(proposal)
    proposals_dir = os.path.abspath(_get_proposals_dir())
    if os.path.commonpath((proposal_path, proposals_dir)) != proposals_dir:
        return {"status": "error", "error": "Proposal path is outside the proposal store."}
    if not os.path.isfile(proposal_path):
        return {"status": "not_found", "error": "Skill proposal tidak ditemukan."}
    with open(proposal_path, encoding="utf-8") as handle:
        content = handle.read()
    match = re.match(r"^---\nname:\s*([a-z0-9-]+)\n.*?\n---\n\n(.*)\Z", content, re.DOTALL)
    if not match:
        return {"status": "error", "error": "Format proposal skill tidak valid."}
    name, body = match.group(1), match.group(2).rstrip() + "\n"
    validation_error = _validate_skill_content(name, "", body)
    if validation_error:
        return {"status": "error", "error": validation_error}
    target_root = os.path.abspath(skills_dir or _get_skills_dir())
    if not target_root:
        return {"status": "error", "error": "Direktori skill aktif tidak ditemukan."}
    target_dir = os.path.join(target_root, name)
    os.makedirs(target_dir, exist_ok=True)
    target_file = os.path.join(target_dir, "SKILL.md")
    with open(target_file, "w", encoding="utf-8") as handle:
        handle.write(f"---\nname: {name}\ndescription: Approved procedural skill.\n---\n\n{body}")
    os.replace(proposal_path, f"{proposal_path}.approved")
    return {"status": "success", "skill": name, "active_file": target_file}


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

    validation_error = _validate_skill_content(safe_name, description, content)
    if validation_error:
        return {"status": "error", "error": validation_error}

    # Generated skills are proposals until an operator explicitly approves them.
    if safe_name.startswith("auto-") and default_sender == "Helmis-AutoCrystallizer":
        proposals_dir = _get_proposals_dir()
        proposal_file = os.path.join(proposals_dir, f"{safe_name}.md")
        os.makedirs(proposals_dir, exist_ok=True)
        skill_md = f"---\nname: {safe_name}\ndescription: {description or 'Proposed procedural skill.'}\nstatus: proposed\nrequested_by: {default_sender}\n---\n\n{content}\n"
        try:
            with open(proposal_file, "x", encoding="utf-8") as f:
                f.write(skill_md)
        except FileExistsError:
            return {"status": "pending", "skill": safe_name, "proposal": proposal_file}
        except Exception as ex:
            return {"status": "error", "error": f"Gagal menyimpan proposal skill: {ex}"}
        return {
            "status": "pending",
            "skill": safe_name,
            "proposal": proposal_file,
            "message": f"Skill *{safe_name}* disimpan sebagai proposal dan belum aktif.",
        }

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
