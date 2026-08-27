"""
test_skills.py — Unit tests for Dynamic On-Demand Skill Loader (Option B).
"""

import pytest

from src.agent.cascade import load_all_skills
from src.tools import execute_tool_call
from src.tools.skills import handle_load_skill, list_available_skills


def test_list_available_skills() -> None:
    """Verify discovery of all available skills in config/skills."""
    skills = list_available_skills()
    skill_names = [s["name"] for s in skills]
    assert "pdf-toolkit" in skill_names
    assert "vault-manager" in skill_names
    assert "task-manager" in skill_names


@pytest.mark.asyncio
async def test_load_skill_pdf_toolkit() -> None:
    """Verify loading pdf-toolkit playbook dynamically."""
    res = await handle_load_skill({"name": "pdf-toolkit"}, default_sender="Gilang")
    assert res["status"] == "success"
    assert res["skill"] == "pdf-toolkit"
    assert "process_pdf" in res["playbook"]
    assert "Merging PDFs" in res["playbook"]
    assert "---" not in res["playbook"][:10]  # Frontmatter stripped


@pytest.mark.asyncio
async def test_load_skill_unknown_fallback() -> None:
    """Verify unknown skill returns clear error with available choices."""
    res = await handle_load_skill({"name": "non_existent_skill"}, default_sender="Gilang")
    assert res["status"] == "error"
    assert "tidak ditemukan" in res["error"]
    assert "pdf-toolkit" in res["available_skills"]


@pytest.mark.asyncio
async def test_load_skill_empty_name() -> None:
    """Verify empty skill name handling."""
    res = await handle_load_skill({"name": ""}, default_sender="Gilang")
    assert res["status"] == "error"
    assert "tidak boleh kosong" in res["error"]


@pytest.mark.asyncio
async def test_react_tool_execution_for_load_skill() -> None:
    """Verify tool execution through execute_tool_call router."""
    res = await execute_tool_call(
        func_name="load_skill",
        args={"name": "pdf_toolkit"},
        default_sender="Gilang",
    )
    assert res["status"] == "success"
    assert res["skill"] == "pdf-toolkit"


def test_cascade_load_all_skills_on_demand_segregation() -> None:
    """Verify cascade prompt loader lists pdf-toolkit in on-demand section."""
    prompt = load_all_skills()
    assert "## ON-DEMAND DOMAIN SKILLS" in prompt
    assert "`pdf-toolkit`" in prompt
    # Verify the full heavy playbook of pdf-toolkit is NOT dumped into the base prompt
    assert "### SKILL: pdf-toolkit" not in prompt
