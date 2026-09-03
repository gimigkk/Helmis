"""
test_compact_mode.py — Query turns carry slim context, same model contract.
"""



from src.agent.cascade import load_compact_system_prompt, load_domain_skills, load_system_prompt
from src.tools.schema import GEMINI_TOOLS, get_compact_tools


class TestCompactTools:
    def test_task_query_gets_task_tools_only(self) -> None:
        compact = get_compact_tools("task")
        names = {d["name"] for d in compact[0]["function_declarations"]}
        assert {"list_tasks", "add_task", "complete_task", "update_task", "delete_task"} <= names
        # escape hatches present so model can pull more tool families
        assert "load_skill" in names and "list_skills" in names
        # irrelevant families absent
        assert "search_vault_files" not in names
        assert "send_whatsapp_message" not in names

    def test_full_payload_unchanged(self) -> None:
        compact = get_compact_tools("task")
        assert len(GEMINI_TOOLS[0]["function_declarations"]) > len(compact[0]["function_declarations"])

    def test_compact_always_smaller(self) -> None:
        for domain in ["task", "schedule", "note", "memory", "person", "vault"]:
            compact = get_compact_tools(domain)
            assert len(str(compact)) < len(str(GEMINI_TOOLS)), domain

    def test_safety_never_empty(self) -> None:
        compact = get_compact_tools("nonexistent-domain")
        assert compact  # falls back to full set


class TestCompactPrompt:
    def test_keeps_core_invariants(self) -> None:
        prompt = load_compact_system_prompt()
        # zero-assumption grounding (§2)
        assert "MUST NEVER assume" in prompt or "Zero Assumptions" in prompt
        # layout contract (§4)
        assert "Daftar Tugas Aktif" in prompt
        assert "Tugas Gilang" in prompt

    def test_drops_irrelevant_sections(self) -> None:
        prompt = load_compact_system_prompt()
        # vault grounding + procedural memory doctrine stay out
        assert "Vault Grounding" not in prompt
        assert "Procedural Memory" not in prompt
        assert len(prompt) < len(load_system_prompt()) * 0.75


class TestDomainSkills:
    def test_task_query_gets_task_skills(self) -> None:
        skills = load_domain_skills("task")
        assert "task-manager" in skills
        assert "recurring-reminders" in skills
        # vault/pdf playbooks stay out of task queries
        assert "pdf-toolkit" not in skills
        assert "vault-manager" not in skills

    def test_smaller_than_full(self) -> None:
        assert len(load_domain_skills("task")) < len(load_domain_skills("unknown"))
