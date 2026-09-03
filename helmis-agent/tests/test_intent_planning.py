"""Tests for typed intent/action planning (src/agent/intent.py)."""

from src.agent.guardrails import classify_turn_intent
from src.agent.intent import (
    TurnPlan,
    build_turn_plan,
    classify_intent,
    plan_system_directive,
    resolve_task_entities,
    should_force_tools,
)


class TestClassificationParity:
    """classify_turn_intent delegates to the typed plan classifier."""

    def test_query_cases(self) -> None:
        assert classify_turn_intent("cek jadwal besok") == "query"
        assert classify_turn_intent("apa aja tugas gw") == "query"
        assert classify_turn_intent("cek tugas yang belum selesai") == "query"
        assert classify_turn_intent("https://docs.google.com/doc") == "query"

    def test_action_cases(self) -> None:
        assert classify_turn_intent("ingetin gw bayar kosan") == "action"
        assert classify_turn_intent("hapus tugas laporan") == "action"
        assert classify_turn_intent("jadwalkan rapat besok") == "action"
        assert classify_turn_intent("catatin nanti gw lupa") == "action"

    def test_chat_cases(self) -> None:
        assert classify_turn_intent("halo gimana kabarnya") == "chat"
        assert classify_turn_intent("") == "chat"


class TestTurnPlan:
    def test_query_plan_has_no_side_effects(self) -> None:
        plan = build_turn_plan("cek jadwal besok")
        assert plan.intent == "query"
        assert plan.action_type == "none"
        assert plan.side_effects == []
        assert plan.destructive is False
        assert plan.source_of_truth == "schedule records"

    def test_create_plan_declares_persistence(self) -> None:
        plan = build_turn_plan("ingetin gw bayar kosan besok")
        assert plan.intent == "action"
        assert plan.action_type == "create"
        assert plan.side_effects == ["persist new record"]
        assert plan.source_of_truth == "task store records"

    def test_delete_plan_is_destructive_and_requires_confirmation(self) -> None:
        plan = build_turn_plan("hapus tugas laporan")
        assert plan.intent == "action"
        assert plan.action_type == "delete"
        assert plan.destructive is True
        assert plan.requires_confirmation is True
        assert plan.confirmation_reason == "destructive_scope"

    def test_bulk_delete_is_destructive(self) -> None:
        plan = build_turn_plan("hapus semua tugas kuliah")
        assert plan.destructive is True
        assert plan.requires_confirmation is True

    def test_single_delete_is_destructive(self) -> None:
        plan = build_turn_plan("hapus tugas 'bayar kosan'")
        assert plan.destructive is True
        assert plan.selectors == ["bayar kosan"]

    def test_update_plan_not_destructive(self) -> None:
        plan = build_turn_plan("geser tugas kosan ke besok")
        assert plan.intent == "action"
        assert plan.action_type == "update"
        assert plan.destructive is False
        assert plan.requires_confirmation is False

    def test_complete_plan_declares_completion_effect(self) -> None:
        plan = build_turn_plan("tandai tugas laporan selesai")
        assert plan.intent == "action"
        assert plan.action_type == "complete"
        assert plan.side_effects == ["mark record completed"]

    def test_quoted_selector_extracted(self) -> None:
        plan = build_turn_plan("selesaikan tugas 'kirim laporan'")
        assert plan.selectors == ["kirim laporan"]


class TestShouldForceTools:
    def test_unambiguous_action_forces_tools(self) -> None:
        assert should_force_tools(build_turn_plan("ingetin gw bayar kosan")) is True

    def test_destructive_does_not_force_tools(self) -> None:
        plan = build_turn_plan("hapus semua tugas kuliah")
        assert plan.destructive is True
        assert should_force_tools(plan) is False

    def test_query_does_not_force_tools(self) -> None:
        assert should_force_tools(build_turn_plan("cek jadwal besok")) is False

    def test_chat_does_not_force_tools(self) -> None:
        assert should_force_tools(build_turn_plan("halo bro")) is False


class TestResolveTaskEntities:
    def test_no_selectors_noop(self) -> None:
        plan = build_turn_plan("ingetin gw bayar kosan")
        resolved = resolve_task_entities(plan)
        assert resolved.matches == []
        assert resolved.requires_confirmation is False

    def test_non_task_domain_noop(self) -> None:
        plan = build_turn_plan("kirim file 'laporan.pdf'")
        assert plan.domain == "vault"
        resolved = resolve_task_entities(plan)
        assert resolved.matches == []

    def test_ambiguous_selector_sets_confirmation(self, sqlite_db) -> None:
        from src.memory.store import add_task

        add_task(title="Bayar kosan bulan ini", due="besok", assignee="Gilang")
        add_task(title="Bayar kosan bulan lalu", due="besok", assignee="Gilang")
        plan = build_turn_plan("selesaikan tugas 'bayar kosan'")
        resolved = resolve_task_entities(plan)
        assert len(resolved.matches) >= 2
        assert resolved.requires_confirmation is True
        assert resolved.confirmation_reason == "ambiguous_selector"

    def test_unique_match_no_confirmation(self, sqlite_db) -> None:
        from src.memory.store import add_task

        add_task(title="Bayar kosan", due="besok", assignee="Gilang")
        add_task(title="Kirim laporan", due="besok", assignee="Gilang")
        plan = build_turn_plan("selesaikan tugas 'bayar kosan'")
        resolved = resolve_task_entities(plan)
        assert len(resolved.matches) == 1
        assert resolved.requires_confirmation is False


class TestPlanSystemDirective:
    def test_query_plan_no_directive(self) -> None:
        assert plan_system_directive(build_turn_plan("cek jadwal besok")) == ""

    def test_action_plan_has_domain_and_effects(self) -> None:
        directive = plan_system_directive(build_turn_plan("ingetin gw bayar kosan"))
        assert "Domain: task" in directive
        assert "persist new record" in directive

    def test_destructive_plan_has_confirmation_order(self) -> None:
        directive = plan_system_directive(build_turn_plan("hapus semua tugas kuliah"))
        assert "DESTRUCTIVE SCOPE" in directive
        assert "Konfirmasi dulu" in directive

    def test_ambiguous_plan_lists_candidates(self, sqlite_db) -> None:
        from src.memory.store import add_task

        add_task(title="Bayar kosan bulan ini", due="besok", assignee="Gilang")
        add_task(title="Bayar kosan bulan lalu", due="besok", assignee="Gilang")
        plan = build_turn_plan("selesaikan tugas 'bayar kosan'")
        resolved = resolve_task_entities(plan)
        directive = plan_system_directive(resolved)
        assert "AMBIGUOUS SELECTOR" in directive
        assert "Bayar kosan bulan ini" in directive
        assert "Bayar kosan bulan lalu" in directive


class TestClassifyIntentMapping:
    def test_coarse_mapping(self) -> None:
        assert classify_intent(build_turn_plan("cek jadwal")) == "query"
        assert classify_intent(build_turn_plan("ingetin gw x")) == "action"
        assert classify_intent(build_turn_plan("wkwk")) == "chat"

    def test_turn_plan_dataclass_defaults(self) -> None:
        plan = TurnPlan(intent="chat", domain="unknown", action_type="none")
        assert plan.selectors == []
        assert plan.side_effects == []
        assert plan.destructive is False
        assert plan.requires_confirmation is False
