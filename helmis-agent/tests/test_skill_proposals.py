import asyncio
from pathlib import Path

from src.tools.skills import approve_skill_proposal, handle_create_skill


def test_auto_skill_is_stored_as_untrusted_proposal(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SKILL_PROPOSALS_DIR", str(tmp_path / "proposals"))
    result = asyncio.run(
        handle_create_skill(
            {
                "name": "auto-example",
                "description": "A reusable example.",
                "content": "# Example\n\n```text\nuse this procedure\n```",
            },
            "Helmis-AutoCrystallizer",
        )
    )
    assert result["status"] == "pending"
    proposal = Path(result["proposal"])
    assert proposal.exists()
    assert "status: proposed" in proposal.read_text()

    approved = asyncio.run(
        approve_skill_proposal(str(proposal), skills_dir=str(tmp_path / "active"))
    )
    assert approved["status"] == "success"
    assert Path(approved["active_file"]).exists()
    assert Path(f"{proposal}.approved").exists()


def _write_proposal(
    proposals_dir: Path, name: str, body: str, description: str = "Test proposal."
) -> Path:
    proposals_dir.mkdir(parents=True, exist_ok=True)
    proposal = proposals_dir / f"{name}.md"
    proposal.write_text(
        f"---\nname: {name}\ndescription: {description}\nstatus: proposed\nrequested_by: tester\n---\n\n{body}",
        encoding="utf-8",
    )
    return proposal


def test_approve_versions_and_archives_previous_active(tmp_path: Path, monkeypatch) -> None:
    from src.tools.skills import list_skill_versions

    monkeypatch.setenv("SKILL_PROPOSALS_DIR", str(tmp_path / "proposals"))
    active = tmp_path / "active"
    active.mkdir()
    existing = active / "auto-example"
    existing.mkdir()
    (existing / "SKILL.md").write_text(
        "---\nname: auto-example\ndescription: Old version.\n---\n\nOld playbook body that is long enough.\n",
        encoding="utf-8",
    )

    proposal = _write_proposal(
        tmp_path / "proposals", "auto-example", "# New\n\n```text\nnew procedure\n```"
    )
    result = asyncio.run(approve_skill_proposal(str(proposal), skills_dir=str(active)))
    assert result["status"] == "success"
    assert result["previous_version"] == 1
    assert result["version"] == 2

    versions = list_skill_versions("auto-example", skills_dir=str(active))
    assert versions["status"] == "success"
    assert versions["active_version"] == 2
    assert "v001" in versions["archived_versions"]
    assert (active / "auto-example" / ".versions" / "v001.md").exists()
    registry = (active / ".skill-registry.json").read_text()
    assert "proposal_approval" in registry
    assert "sha256" in registry


def test_rollback_restores_previous_version_and_is_reversible(tmp_path: Path, monkeypatch) -> None:
    from src.tools.skills import list_skill_versions, rollback_skill

    monkeypatch.setenv("SKILL_PROPOSALS_DIR", str(tmp_path / "proposals"))
    active = tmp_path / "active"
    proposals_dir = tmp_path / "proposals"

    proposal = _write_proposal(
        proposals_dir, "auto-rollback", "# V1\n\n```text\nfirst procedure\n```"
    )
    first = asyncio.run(approve_skill_proposal(str(proposal), skills_dir=str(active)))
    assert first["status"] == "success" and first["version"] == 1
    skill_file = active / "auto-rollback" / "SKILL.md"
    assert "first procedure" in skill_file.read_text()

    # Approve a second (worse) proposal -> becomes v2 active
    proposal2 = _write_proposal(
        proposals_dir, "auto-rollback", "# V2\n\n```text\nbroken procedure\n```"
    )
    second = asyncio.run(approve_skill_proposal(str(proposal2), skills_dir=str(active)))
    assert second["status"] == "success" and second["version"] == 2
    assert "broken procedure" in skill_file.read_text()

    rolled = rollback_skill("auto-rollback", skills_dir=str(active))
    assert rolled["status"] == "success"
    assert rolled["rolled_back_from"] == 2
    assert rolled["active_version"] == 1
    assert "first procedure" in skill_file.read_text()

    versions = list_skill_versions("auto-rollback", skills_dir=str(active))
    assert versions["source"] == "rollback_from_v2"
    assert versions["active_version"] == 1


def test_rollback_rejects_target_not_older(tmp_path: Path, monkeypatch) -> None:
    from src.tools.skills import rollback_skill

    monkeypatch.setenv("SKILL_PROPOSALS_DIR", str(tmp_path / "proposals"))
    active = tmp_path / "active"
    proposal = _write_proposal(tmp_path / "proposals", "auto-guard", "# V1\n\n```text\nbody\n```")
    result = asyncio.run(approve_skill_proposal(str(proposal), skills_dir=str(active)))
    assert result["version"] == 1
    rolled = rollback_skill("auto-guard", to_version=1, skills_dir=str(active))
    assert rolled["status"] == "error"
    rolled_missing = rollback_skill("does-not-exist", skills_dir=str(active))
    assert rolled_missing["status"] == "not_found"


def test_proposal_candidate_workflow_reject(tmp_path: Path, monkeypatch) -> None:
    from src.tools.skills import list_proposals, reject_proposal

    monkeypatch.setenv("SKILL_PROPOSALS_DIR", str(tmp_path / "proposals"))
    proposals_dir = tmp_path / "proposals"
    _write_proposal(proposals_dir, "auto-candidate-a", "# A\n\n```text\nbody a\n```")
    _write_proposal(proposals_dir, "auto-candidate-b", "# B\n\n```text\nbody b\n```")

    listing = list_proposals()
    assert listing["pending_count"] == 2
    assert {p["name"] for p in listing["pending"]} == {"auto-candidate-a", "auto-candidate-b"}

    target = str(proposals_dir / "auto-candidate-a.md")
    rejected = reject_proposal(target, reason="duplicate of existing skill")
    assert rejected["status"] == "success"
    assert Path(rejected["rejected_file"]).exists()
    assert "duplicate of existing skill" in Path(rejected["rejected_file"]).read_text()

    listing_after = list_proposals()
    assert listing_after["pending_count"] == 1
    assert listing_after["pending"][0]["name"] == "auto-candidate-b"
    assert len(listing_after["rejected"]) == 1

    outside = tmp_path / "outside.md"
    outside.write_text("---\nname: x\n---\n\nbody\n", encoding="utf-8")
    assert reject_proposal(str(outside))["status"] == "error"
