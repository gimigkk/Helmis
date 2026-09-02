"""
skills.py — Dynamic On-Demand Skill Loader for Helmis.
"""

import hashlib
import json
import logging
import os
import re
from datetime import UTC, datetime
from typing import Any

from ..memory.store import log_activity
from .registry import register_tool

log = logging.getLogger("helmis-tools-skills")

_SKILL_FRONTMATTER_PATTERN = r"^---\nname:\s*([a-z0-9-]+)\n.*?\n---\n\n(.*)\Z"


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


def _skill_versions_dir(skills_dir: str, name: str) -> str:
    """Version history lives inside the skill dir, but the loader only ever
    reads SKILL.md, so archived versions never leak into the active prompt."""
    return os.path.join(skills_dir, name, ".versions")


def _content_sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _read_registry(skills_dir: str) -> dict[str, Any]:
    registry_file = os.path.join(skills_dir, ".skill-registry.json")
    if not os.path.exists(registry_file):
        return {}
    try:
        with open(registry_file, encoding="utf-8") as handle:
            data = json.load(handle)
            return data if isinstance(data, dict) else {}
    except Exception as ex:
        log.warning("Failed to read skill registry: %s", ex)
        return {}


def _write_registry(skills_dir: str, registry: dict[str, Any]) -> None:
    registry_file = os.path.join(skills_dir, ".skill-registry.json")
    tmp_file = f"{registry_file}.tmp.{os.getpid()}"
    try:
        with open(tmp_file, "w", encoding="utf-8") as handle:
            json.dump(registry, handle, indent=2, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_file, registry_file)
    except Exception as ex:
        log.warning("Failed to write skill registry: %s", ex)
        if os.path.exists(tmp_file):
            try:
                os.remove(tmp_file)
            except Exception:
                pass


def _record_version(
    skills_dir: str,
    name: str,
    *,
    content: str,
    source: str,
    proposal_path: str | None = None,
    previous_version: int | None = None,
) -> int:
    """Snapshot the current active SKILL.md into .versions/ and update the
    registry with audit metadata. Returns the new version number."""
    registry = _read_registry(skills_dir)
    entry = registry.get(name, {})
    previous = (
        previous_version if previous_version is not None else int(entry.get("version", 0)) or None
    )
    version = (previous or 0) + 1
    now = datetime.now(UTC).isoformat()

    versions_dir = _skill_versions_dir(skills_dir, name)
    os.makedirs(versions_dir, exist_ok=True)
    version_file = os.path.join(versions_dir, f"v{version:03d}.md")
    with open(version_file, "w", encoding="utf-8") as handle:
        handle.write(content)

    entry.update(
        {
            "version": version,
            "updated_at": now,
            "source": source,
            "sha256": _content_sha256(content),
            "version_file": version_file,
        }
    )
    if proposal_path:
        entry["proposal_path"] = proposal_path
    if previous_version is not None:
        entry["previous_version"] = previous_version
    registry[name] = entry
    _write_registry(skills_dir, registry)
    return version


async def approve_skill_proposal(proposal: str, *, skills_dir: str | None = None) -> dict[str, Any]:
    """Promote one validated proposal into the active skill directory explicitly.

    Versioned: the prior active SKILL.md (if any) is snapshotted to
    .versions/vNNN.md before overwrite, and the promotion is recorded in
    .skill-registry.json with audit metadata (version, sha256, source,
    proposal path). Rollback is possible via rollback_skill().
    """
    proposal_path = os.path.abspath(proposal)
    proposals_dir = os.path.abspath(_get_proposals_dir())
    if os.path.commonpath((proposal_path, proposals_dir)) != proposals_dir:
        return {"status": "error", "error": "Proposal path is outside the proposal store."}
    if not os.path.isfile(proposal_path):
        return {"status": "not_found", "error": "Skill proposal tidak ditemukan."}
    with open(proposal_path, encoding="utf-8") as handle:
        content = handle.read()
    match = re.match(_SKILL_FRONTMATTER_PATTERN, content, re.DOTALL)
    if not match:
        return {"status": "error", "error": "Format proposal skill tidak valid."}
    name, body = match.group(1), match.group(2).rstrip() + "\n"
    description_match = re.search(r"^description:\s*(.+)$", content, re.MULTILINE)
    description = description_match.group(1).strip() if description_match else ""
    validation_error = _validate_skill_content(name, description, body)
    if validation_error:
        return {"status": "error", "error": validation_error}
    target_root = os.path.abspath(skills_dir or _get_skills_dir())
    if not target_root:
        return {"status": "error", "error": "Direktori skill aktif tidak ditemukan."}
    target_dir = os.path.join(target_root, name)
    target_file = os.path.join(target_dir, "SKILL.md")

    previous_version: int | None = None
    if os.path.exists(target_file):
        with open(target_file, encoding="utf-8") as handle:
            prior_content = handle.read()
        registry_before = _read_registry(target_root).get(name, {})
        previous_version = int(registry_before.get("version", 0)) or None
        if previous_version is None:
            previous_version = 1
            os.makedirs(_skill_versions_dir(target_root, name), exist_ok=True)
            with open(
                os.path.join(_skill_versions_dir(target_root, name), "v001.md"),
                "w",
                encoding="utf-8",
            ) as handle:
                handle.write(prior_content)
        else:
            with open(
                os.path.join(_skill_versions_dir(target_root, name), f"v{previous_version:03d}.md"),
                "w",
                encoding="utf-8",
            ) as handle:
                handle.write(prior_content)

    os.makedirs(target_dir, exist_ok=True)
    active_content = f"---\nname: {name}\ndescription: {description or 'Approved procedural skill.'}\n---\n\n{body}"
    with open(target_file, "w", encoding="utf-8") as handle:
        handle.write(active_content)
    version = _record_version(
        target_root,
        name,
        content=active_content,
        source="proposal_approval",
        proposal_path=proposal_path,
        previous_version=previous_version,
    )
    os.replace(proposal_path, f"{proposal_path}.approved")
    log_activity(
        f"Skill proposal '{name}' approved as v{version} (from {os.path.basename(proposal_path)})"
    )
    return {
        "status": "success",
        "skill": name,
        "active_file": target_file,
        "version": version,
        "previous_version": previous_version,
    }


def list_skill_versions(name: str, *, skills_dir: str | None = None) -> dict[str, Any]:
    """List archived versions + registry metadata for one skill."""
    clean_name = re.sub(r"[^a-z0-9\-]", "", str(name).strip().lower())
    target_root = os.path.abspath(skills_dir or _get_skills_dir())
    if not target_root:
        return {"status": "error", "error": "Direktori skill aktif tidak ditemukan."}
    registry = _read_registry(target_root)
    entry = registry.get(clean_name)
    if not entry:
        return {
            "status": "not_found",
            "error": f"Tidak ada riwayat versi untuk skill '{clean_name}'.",
        }
    versions_dir = _skill_versions_dir(target_root, clean_name)
    archived = []
    if os.path.isdir(versions_dir):
        for f in sorted(os.listdir(versions_dir)):
            if re.fullmatch(r"v\d{3}\.md", f):
                archived.append(f[:-3])
    return {
        "status": "success",
        "skill": clean_name,
        "active_version": entry.get("version"),
        "source": entry.get("source"),
        "updated_at": entry.get("updated_at"),
        "sha256": entry.get("sha256"),
        "archived_versions": archived,
    }


def rollback_skill(
    name: str,
    *,
    to_version: int | None = None,
    skills_dir: str | None = None,
    rolled_back_by: str = "operator",
) -> dict[str, Any]:
    """Restore the previous active version of a skill (one-command rollback).

    Default target = latest archived version. The current active content is
    snapshotted first, so rollback itself is versioned and reversible.
    """
    clean_name = re.sub(r"[^a-z0-9\-]", "", str(name).strip().lower())
    target_root = os.path.abspath(skills_dir or _get_skills_dir())
    if not target_root:
        return {"status": "error", "error": "Direktori skill aktif tidak ditemukan."}
    registry = _read_registry(target_root)
    entry = registry.get(clean_name)
    if not entry or not entry.get("version"):
        return {
            "status": "not_found",
            "error": f"Tidak ada riwayat versi untuk skill '{clean_name}'.",
        }

    active_version = int(entry["version"])
    versions_dir = _skill_versions_dir(target_root, clean_name)
    if to_version is None:
        # Default: the version the registry says preceded the current one.
        to_version = int(entry.get("previous_version", 0)) or None
        if to_version is None:
            return {
                "status": "not_found",
                "error": f"Tidak ada versi sebelumnya tercatat untuk skill '{clean_name}'.",
            }
    if to_version >= active_version:
        return {
            "status": "error",
            "error": f"Versi target v{to_version} harus lebih lama dari versi aktif v{active_version}.",
        }
    source_file = os.path.join(versions_dir, f"v{to_version:03d}.md")
    if not os.path.isfile(source_file):
        return {"status": "not_found", "error": f"Versi v{to_version} tidak ditemukan di arsip."}

    with open(source_file, encoding="utf-8") as handle:
        restore_content = handle.read()
    match = re.match(_SKILL_FRONTMATTER_PATTERN, restore_content, re.DOTALL)
    if not match:
        return {"status": "error", "error": f"Arsip v{to_version} korup atau format tidak dikenal."}

    target_file = os.path.join(target_root, clean_name, "SKILL.md")
    if os.path.exists(target_file):
        with open(target_file, encoding="utf-8") as handle:
            current_content = handle.read()
        # Archive current active as its own numbered version (reversible rollback)
        os.makedirs(versions_dir, exist_ok=True)
        with open(
            os.path.join(versions_dir, f"v{active_version:03d}.md"), "w", encoding="utf-8"
        ) as handle:
            handle.write(current_content)

    os.makedirs(os.path.dirname(target_file), exist_ok=True)
    with open(target_file, "w", encoding="utf-8") as handle:
        handle.write(restore_content)

    now = datetime.now(UTC).isoformat()
    entry.update(
        {
            "version": to_version,
            "updated_at": now,
            "source": f"rollback_from_v{active_version}",
            "sha256": _content_sha256(restore_content),
            "previous_version": active_version,
            "rolled_back_by": rolled_back_by,
            "rolled_back_at": now,
        }
    )
    registry[clean_name] = entry
    _write_registry(target_root, registry)
    log_activity(
        f"Skill '{clean_name}' rolled back v{active_version} -> v{to_version} by {rolled_back_by}"
    )
    return {
        "status": "success",
        "skill": clean_name,
        "rolled_back_from": active_version,
        "active_version": to_version,
    }


def list_proposals(*, proposals_dir: str | None = None) -> dict[str, Any]:
    """Candidate workflow: list pending (and rejected) skill proposals."""
    root = os.path.abspath(proposals_dir or _get_proposals_dir())
    pending: list[dict[str, str]] = []
    rejected: list[dict[str, str]] = []
    if os.path.isdir(root):
        for f in sorted(os.listdir(root)):
            path = os.path.join(root, f)
            if not os.path.isfile(path):
                continue
            info: dict[str, str] = {"proposal": path}
            try:
                with open(path, encoding="utf-8") as handle:
                    head = handle.read(2048)
                name_m = re.search(r"^name:\s*(.+)$", head, re.MULTILINE)
                desc_m = re.search(r"^description:\s*(.+)$", head, re.MULTILINE)
                req_m = re.search(r"^requested_by:\s*(.+)$", head, re.MULTILINE)
                if name_m:
                    info["name"] = name_m.group(1).strip()
                if desc_m:
                    info["description"] = desc_m.group(1).strip()
                if req_m:
                    info["requested_by"] = req_m.group(1).strip()
            except Exception:
                info["read_error"] = "true"
            if f.endswith(".rejected"):
                info["proposal"] = path[: -len(".rejected")]
                rejected.append(info)
            elif f.endswith(".md"):
                pending.append(info)
    return {
        "status": "success",
        "pending_count": len(pending),
        "pending": pending,
        "rejected": rejected,
    }


def reject_proposal(
    proposal: str, *, proposals_dir: str | None = None, reason: str = ""
) -> dict[str, Any]:
    """Candidate workflow: mark one proposal rejected (kept for audit, never injected)."""
    proposal_path = os.path.abspath(proposal)
    root = os.path.abspath(proposals_dir or _get_proposals_dir())
    if os.path.commonpath((proposal_path, root)) != root:
        return {"status": "error", "error": "Proposal path is outside the proposal store."}
    if not os.path.isfile(proposal_path):
        return {"status": "not_found", "error": "Skill proposal tidak ditemukan."}
    if not proposal_path.endswith(".md"):
        return {
            "status": "error",
            "error": "Hanya proposal berstatus pending (.md) yang bisa ditolak.",
        }
    rejected_path = f"{proposal_path}.rejected"
    with open(proposal_path, encoding="utf-8") as handle:
        original = handle.read()
    with open(rejected_path, "w", encoding="utf-8") as handle:
        handle.write(
            f"<!-- rejected_at: {datetime.now(UTC).isoformat()} reason: {reason or 'unspecified'} -->\n"
            + original
        )
    os.remove(proposal_path)
    log_activity(
        f"Skill proposal '{os.path.basename(proposal_path)}' rejected{': ' + reason if reason else ''}"
    )
    return {"status": "success", "proposal": proposal_path, "rejected_file": rejected_path}


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
        if is_update:
            registry_before = _read_registry(skills_dir).get(safe_name, {})
            _record_version(
                skills_dir,
                safe_name,
                content=skill_md,
                source="agent_update",
                previous_version=int(registry_before.get("version", 0)) or None,
            )
        else:
            _record_version(skills_dir, safe_name, content=skill_md, source="agent_create")
        log_activity(
            f"Procedural skill '{safe_name}' {action} by agent (requested by {default_sender})"
        )
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

        registry_before = _read_registry(skills_dir).get(safe_name, {})
        _record_version(
            skills_dir,
            safe_name,
            content=updated,
            source="agent_update" if not append else "agent_append",
            previous_version=int(registry_before.get("version", 0)) or None,
        )
        log_activity(
            f"Procedural skill '{safe_name}' updated by agent (requested by {default_sender})"
        )
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
