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

    approved = asyncio.run(approve_skill_proposal(str(proposal), skills_dir=str(tmp_path / "active")))
    assert approved["status"] == "success"
    assert Path(approved["active_file"]).exists()
    assert Path(f"{proposal}.approved").exists()
