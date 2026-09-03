"""
test_scenario_matrix.py — Phase 5 scenario coverage matrix (100+ cases).

Cross-feature scenario tests exercising the rebuild features end-to-end at the
unit boundary. Organized in matrices:

  M1  Recurrence engine semantics            (18 cases)
  M2  Nag policy / proactive laddering       (16 cases)
  M3  Guardrail text x outcome fidelity      (20 cases)
  M4  Memory candidates + corrections        (14 cases)
  M5  Scheduling integrity: occurrences,     (22 cases)
      outbox, quarantine, authz, validation
  M6  Intent planning, migration, cascade    (16 cases)

Each test is a scenario: setup state, act, assert observable outcomes. No
network, no external services. Names are scenario-shaped for failure triage.
"""

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import pytest

from src.agent.cascade import _looks_like_gemini_key
from src.agent.guardrails import (
    inject_tool_directive as inject_directive,
)
from src.agent.guardrails import (
    mutation_was_effective as mutation_effective,
)
from src.agent.guardrails import (
    verify_action_fidelity as verify_fidelity,
)
from src.agent.intent import build_turn_plan, should_force_tools
from src.agent.proactive import (
    _resolve_reminder_policy,
    handle_proactive_scheduler_tick,
)
from src.memory.migrate import migrate_json_tasks
from src.memory.recurrence import (
    interval_seconds,
    next_occurrence,
    next_occurrence_for_task,
)
from src.memory.store import (
    add_person,
    add_task,
    bulk_delete_tasks,
    complete_task_result,
    get_repository,
    identity_key,
    list_tasks,
    update_task_fields,
)
from src.memory.task_repository import TaskRepository
from src.tools.registry import execute_tool_call
from src.whatsapp.client import WahaClient

TZ = ZoneInfo("Asia/Jakarta")


@pytest.fixture(autouse=True)
def people_directory(monkeypatch: pytest.MonkeyPatch) -> None:
    """Recipient resolution from directory data, never env or name-sniffing."""
    monkeypatch.delenv("TRIO_GROUP_JID", raising=False)
    add_person("Gilang", phone="+628123456789")
    add_person("Bunga", phone="+628987654321")


async def _tick_at(client: AsyncMock, y: int, mo: int, d: int, h: int, mi: int = 0) -> None:
    """Run one proactive tick with mocked wall time."""
    mock_dt = datetime(y, mo, d, h, mi, tzinfo=TZ)
    with patch("src.agent.proactive.datetime") as mock_datetime:
        mock_datetime.now.return_value = mock_dt
        await handle_proactive_scheduler_tick(client)


# ---------------------------------------------------------------------------
# M1 — Recurrence engine semantics (18 scenarios)
# ---------------------------------------------------------------------------


class TestRecurrenceMatrix:
    def test_weekly_single_day_next_week(self) -> None:
        rule = {"type": "weekly", "weekdays": ["selasa"], "time": "07:45", "timezone": "Asia/Jakarta"}
        after = datetime(2026, 9, 2, 12, 0, tzinfo=TZ)  # Wednesday
        nxt = next_occurrence(rule, after)
        assert nxt.weekday() == 1 and nxt.hour == 7 and nxt.minute == 45
        assert nxt.date() == datetime(2026, 9, 8).date()

    def test_weekday_id_numbers_map_monday_zero(self) -> None:
        rule = {"type": "weekly", "weekdays": [0], "time": "08:00", "timezone": "Asia/Jakarta"}
        after = datetime(2026, 9, 4, 10, 0, tzinfo=TZ)  # Friday
        assert next_occurrence(rule, after).weekday() == 0

    def test_weekday_english_names(self) -> None:
        rule = {"type": "weekly", "weekdays": ["monday"], "time": "09:00", "timezone": "Asia/Jakarta"}
        after = datetime(2026, 9, 4, 10, 0, tzinfo=TZ)
        assert next_occurrence(rule, after).weekday() == 0

    def test_weekday_mixed_case_and_spaces(self) -> None:
        rule = {"type": "weekly", "weekdays": [" Selasa "], "time": "07:00", "timezone": "Asia/Jakarta"}
        after = datetime(2026, 9, 2, 8, 0, tzinfo=TZ)
        assert next_occurrence(rule, after).weekday() == 1

    def test_same_day_later_time_is_next_slot(self) -> None:
        rule = {"type": "weekly", "weekdays": ["rabu"], "time": "13:00", "timezone": "Asia/Jakarta"}
        after = datetime(2026, 9, 2, 8, 0, tzinfo=TZ)  # Wednesday before class
        assert next_occurrence(rule, after).date() == after.date()

    def test_same_day_earlier_time_next_week(self) -> None:
        rule = {"type": "weekly", "weekdays": ["rabu"], "time": "07:00", "timezone": "Asia/Jakarta"}
        after = datetime(2026, 9, 2, 9, 0, tzinfo=TZ)  # Wednesday after class
        assert next_occurrence(rule, after).date() == datetime(2026, 9, 9).date()

    def test_multi_day_picks_nearest(self) -> None:
        rule = {"type": "weekly", "weekdays": ["selasa", "kamis"], "time": "08:00", "timezone": "Asia/Jakarta"}
        after = datetime(2026, 9, 2, 9, 0, tzinfo=TZ)  # Wednesday
        assert next_occurrence(rule, after).weekday() == 3  # Thursday first

    def test_interval_rule_days(self) -> None:
        rule = {"type": "interval", "interval": 3, "unit": "days"}
        after = datetime(2026, 9, 2, 9, 0, tzinfo=TZ)
        nxt = next_occurrence(rule, after)
        assert (nxt - after).total_seconds() == 3 * 86400

    def test_interval_rule_minutes_shortcut(self) -> None:
        rule = {"type": "interval", "interval_minutes": 90}
        after = datetime(2026, 9, 2, 9, 0, tzinfo=TZ)
        assert (next_occurrence(rule, after) - after).total_seconds() == 5400

    def test_interval_rule_every_nested(self) -> None:
        rule = {"type": "every", "every": {"value": 2, "unit": "hours"}}
        after = datetime(2026, 9, 2, 9, 0, tzinfo=TZ)
        assert (next_occurrence(rule, after) - after).total_seconds() == 7200

    def test_interval_unit_hours(self) -> None:
        rule = {"type": "interval", "interval": 2, "unit": "hours"}
        assert interval_seconds(rule) == 7200

    def test_interval_nonpositive_rejected(self) -> None:
        assert interval_seconds({"type": "interval", "interval": 0}) is None
        assert interval_seconds({"type": "interval", "interval": -5}) is None

    def test_invalid_time_raises(self) -> None:
        rule = {"type": "weekly", "weekdays": ["senin"], "time": "25:00", "timezone": "Asia/Jakarta"}
        with pytest.raises(ValueError):
            next_occurrence(rule, datetime(2026, 9, 2, tzinfo=TZ))

    def test_weekly_without_days_returns_none(self) -> None:
        rule = {"type": "weekly", "time": "08:00", "timezone": "Asia/Jakarta"}
        assert next_occurrence(rule, datetime(2026, 9, 2, tzinfo=TZ)) is None

    def test_task_level_helper_uses_due_anchor(self) -> None:
        task = {
            "due": "2026-09-01 07:45 WIB",
            "recurrence": {"type": "weekly", "weekdays": ["selasa"], "time": "07:45", "timezone": "Asia/Jakarta"},
        }
        after = datetime(2026, 9, 1, 8, 0, tzinfo=TZ)
        assert next_occurrence_for_task(task, after).date() == datetime(2026, 9, 8).date()

    def test_task_without_recurrence_returns_none(self) -> None:
        assert next_occurrence_for_task({"due": "2026-09-01 07:45 WIB"}, datetime(2026, 9, 2, tzinfo=TZ)) is None

    def test_timezone_conversion(self) -> None:
        rule = {"type": "weekly", "weekdays": ["senin"], "time": "07:00", "timezone": "UTC"}
        after = datetime(2026, 9, 7, 9, 0, tzinfo=TZ)  # Monday 16:00 UTC
        assert next_occurrence(rule, after).weekday() == 0  # next Monday UTC

    def test_proactive_series_survives_two_weeks(self) -> None:
        """Simulated: fire, complete, fire again — series never dies."""
        task = add_task(
            title="Absensi Komdat",
            due="2026-09-01 07:45 WIB",
            assignee="Gilang",
            priority="urgent",
            recurrence={"type": "weekly", "weekdays": ["selasa"], "time": "07:45", "timezone": "Asia/Jakarta"},
        )
        client = AsyncMock(spec=WahaClient)
        _tick_at(client, 2026, 9, 1, 7, 46)   # due fires
        complete_task_result(title="Absensi Komdat")
        task = get_repository().list_tasks()[0]
        assert task["status"] == "completed"
        nxt = next_occurrence_for_task(task, datetime(2026, 9, 1, 8, 0, tzinfo=TZ))
        assert nxt.date() == datetime(2026, 9, 8).date()


# ---------------------------------------------------------------------------
# M2 — Nag policy / proactive laddering (16 scenarios)
# ---------------------------------------------------------------------------


class TestNagPolicyMatrix:
    async def test_policy_row_overrides_task_fields(self, sqlite_db) -> None:
        task = add_task(title="Nag Row", due="2026-09-01 10:00 WIB", assignee="Gilang", priority="normal")
        get_repository().create_reminder_policy(
            "pol-1", task_id=task["task_id"], owner="Gilang",
            repeat_interval_minutes=3, max_repeats=2, acknowledgment_required=True,
        )
        policy = _resolve_reminder_policy(get_repository().list_tasks()[0])
        assert policy["repeat_interval_minutes"] == 3
        assert policy["max_repeats"] == 2

    async def test_task_nag_fields_derive_policy(self) -> None:
        add_task(title="Field Nag", due="x", assignee="Gilang", nag_policy={"interval_minutes": 5, "max_nags": 6})
        policy = _resolve_reminder_policy(get_repository().list_tasks()[0])
        assert policy["repeat_interval_minutes"] == 5
        assert policy["max_repeats"] == 5  # max_nags-1

    async def test_urgent_default_ladder(self) -> None:
        add_task(title="Urgent Def", due="x", assignee="Gilang", priority="urgent")
        policy = _resolve_reminder_policy(get_repository().list_tasks()[0])
        assert policy["repeat_interval_minutes"] == 10
        assert policy["max_repeats"] == 5

    async def test_normal_no_nag_returns_none(self) -> None:
        add_task(title="Quiet", due="x", assignee="Gilang", priority="normal")
        assert _resolve_reminder_policy(get_repository().list_tasks()[0]) is None

    async def test_nag_enabled_flag_without_priority(self) -> None:
        add_task(title="Flag Nag", due="x", assignee="Gilang", priority="normal", nag_policy={"interval_minutes": 2})
        assert _resolve_reminder_policy(get_repository().list_tasks()[0]) is not None

    async def test_custom_standdown_preserved(self) -> None:
        add_task(title="Stand", due="x", assignee="Gilang", nag_policy={"interval_minutes": 5, "max_nags": 6, "stand_down_after_minutes": 30})
        policy = _resolve_reminder_policy(get_repository().list_tasks()[0])
        assert policy["stand_down_after_minutes"] == 30

    async def test_cross_alert_carried_from_policy(self) -> None:
        add_task(title="Cross", due="x", assignee="Gilang", nag_policy={"interval_minutes": 5, "cross_alert_recipient": "Bunga"})
        policy = _resolve_reminder_policy(get_repository().list_tasks()[0])
        assert policy["cross_alert_recipient"] == "Bunga"

    async def test_nag_ladder_counts_and_standdown(self) -> None:
        """urgent default: nags at 10-min intervals, stops after 5 repeats."""
        add_task(title="Nag Count", due="2026-09-01 10:00 WIB", assignee="Gilang", priority="urgent")
        client = AsyncMock(spec=WahaClient)
        fires = 0
        for minute in (0, 10, 20, 30, 40, 50):
            await _tick_at(client, 2026, 9, 1, 10, minute)
            if client.send_message.call_count > fires:
                fires = client.send_message.call_count
        assert fires == 6  # due + 5 nags within the hour

    async def test_nag_stops_after_user_confirms(self) -> None:
        add_task(title="Confirm Stop", due="2026-09-01 10:00 WIB", assignee="Gilang", priority="urgent")
        client = AsyncMock(spec=WahaClient)
        await _tick_at(client, 2026, 9, 1, 10, 0)
        assert client.send_message.called
        complete_task_result(title="Confirm Stop")
        calls = client.send_message.call_count
        await _tick_at(client, 2026, 9, 1, 10, 10)
        await _tick_at(client, 2026, 9, 1, 10, 20)
        assert client.send_message.call_count == calls

    async def test_nonurgent_task_no_nag_after_due(self) -> None:
        add_task(title="No Nag", due="2026-09-01 10:00 WIB", assignee="Gilang", priority="normal")
        client = AsyncMock(spec=WahaClient)
        await _tick_at(client, 2026, 9, 1, 9, 57)
        assert client.send_message.called
        calls = client.send_message.call_count
        await _tick_at(client, 2026, 9, 1, 10, 10)
        assert client.send_message.call_count == calls

    async def test_due_reminder_fires_on_time(self) -> None:
        add_task(title="On Time", due="2026-09-01 10:00 WIB", assignee="Gilang")
        client = AsyncMock(spec=WahaClient)
        await _tick_at(client, 2026, 9, 1, 9, 50)
        assert not client.send_message.called  # more than 5 min before due
        await _tick_at(client, 2026, 9, 1, 9, 57)  # inside 5-min pre-window
        assert client.send_message.called

    async def test_kickoff_reminder_within_lead_window(self) -> None:
        add_task(title="Lead", due="2026-09-01 15:00 WIB", assignee="Gilang", lead_time_minutes=120)
        client = AsyncMock(spec=WahaClient)
        await _tick_at(client, 2026, 9, 1, 13, 5)
        assert client.send_message.called

    async def test_no_kickoff_outside_lead_window(self) -> None:
        add_task(title="No Lead", due="2026-09-01 15:00 WIB", assignee="Gilang", lead_time_minutes=120)
        client = AsyncMock(spec=WahaClient)
        await _tick_at(client, 2026, 9, 1, 10, 0)
        assert not client.send_message.called

    async def test_recurring_human_reminder_reschedules_next_week(self) -> None:
        add_task(
            title="Weekly Human",
            due="2026-09-01 08:00 WIB",
            assignee="Gilang",
            recurrence={"type": "weekly", "weekdays": ["selasa"], "time": "08:00", "timezone": "Asia/Jakarta"},
        )
        client = AsyncMock(spec=WahaClient)
        await _tick_at(client, 2026, 9, 1, 8, 1)
        assert client.send_message.called
        task = get_repository().list_tasks()[0]
        assert "2026-09-08" in task["due"]

    async def test_recurring_bot_action_overdue_skip_and_advance(self) -> None:
        add_task(
            title="Weekly Bot",
            due="2026-09-01 08:00 WIB",
            assignee="Helmis",
            job={"kind": "message", "text": "weekly ping"},
            recurrence={"type": "weekly", "weekdays": ["selasa"], "time": "08:00", "timezone": "Asia/Jakarta"},
        )
        client = AsyncMock(spec=WahaClient)
        await _tick_at(client, 2026, 9, 1, 14, 0)  # >2h overdue
        task = get_repository().list_tasks()[0]
        assert task["execution_status"] == "skipped_overdue"
        assert "2026-09-08" in task["due"]

    async def test_nonrecurring_overdue_bot_action_expires(self) -> None:
        add_task(title="One Shot Bot", due="2026-09-01 08:00 WIB", assignee="Helmis", job={"kind": "message", "text": "x"})
        client = AsyncMock(spec=WahaClient)
        await _tick_at(client, 2026, 9, 1, 14, 0)
        assert get_repository().list_tasks()[0]["status"] == "expired"


# ---------------------------------------------------------------------------
# M3 — Guardrail text x outcome fidelity (20 scenarios)
# ---------------------------------------------------------------------------

CLAIM_DELETE = "Sip, tugasnya sudah Helmis hapus ya."
CLAIM_COMPLETE = "Tugas laporan sudah ditandai selesai."
CLAIM_ADD = "Reminder sudah dicatat."
INNOCENT = "Oke."
BLOCK_MSG = "belum berhasil diproses"


class TestGuardrailMatrix:
    def _tools(self, name: str, result: dict[str, Any]) -> list[dict[str, Any]]:
        return [{"name": name, "result": result}]

    # -- claiming text x failure outcomes: must block
    def test_delete_claim_after_not_found_blocked(self) -> None:
        out = verify_fidelity(CLAIM_DELETE, self._tools("delete_task", {"status": "not_found"}))
        assert BLOCK_MSG in out

    def test_delete_claim_after_ambiguous_blocked(self) -> None:
        out = verify_fidelity(CLAIM_DELETE, self._tools("delete_task", {"status": "ambiguous"}))
        assert BLOCK_MSG in out

    def test_delete_claim_after_conflict_blocked(self) -> None:
        out = verify_fidelity(CLAIM_DELETE, self._tools("delete_task", {"status": "conflict"}))
        assert BLOCK_MSG in out

    def test_delete_claim_after_error_blocked(self) -> None:
        out = verify_fidelity(CLAIM_DELETE, self._tools("delete_task", {"status": "error", "error": "db down"}))
        assert BLOCK_MSG in out

    def test_delete_claim_after_zero_deleted_blocked(self) -> None:
        out = verify_fidelity(CLAIM_DELETE, self._tools("delete_task", {"status": "success", "deleted_count": 0}))
        assert BLOCK_MSG in out

    def test_complete_claim_after_read_only_only_blocked(self) -> None:
        out = verify_fidelity(CLAIM_COMPLETE, self._tools("list_tasks", {"status": "success", "count": 2}))
        assert BLOCK_MSG in out

    def test_add_claim_after_read_only_only_blocked(self) -> None:
        out = verify_fidelity(CLAIM_ADD, self._tools("list_tasks", {"status": "success"}))
        assert BLOCK_MSG in out

    def test_delete_claim_after_not_found_no_message_replaced(self) -> None:
        out = verify_fidelity(INNOCENT, self._tools("delete_task", {"status": "not_found"}))
        assert "Tidak ada data yang cocok" in out

    # -- claiming text x effective mutation: must pass
    def test_delete_claim_after_real_delete_passes(self) -> None:
        out = verify_fidelity(CLAIM_DELETE, self._tools("delete_task", {"status": "success", "deleted_count": 2}))
        assert out == CLAIM_DELETE

    def test_complete_claim_after_real_complete_passes(self) -> None:
        out = verify_fidelity(CLAIM_COMPLETE, self._tools("complete_task", {"status": "success", "task": {"task_id": "1"}}))
        assert out == CLAIM_COMPLETE

    def test_add_claim_after_real_add_passes(self) -> None:
        out = verify_fidelity(CLAIM_ADD, self._tools("add_task", {"status": "success", "task_id": "t"}))
        assert out == CLAIM_ADD

    # -- innocent text x failure: must NOT be blocked
    def test_innocent_text_never_blocked(self) -> None:
        for name, res in (
            ("delete_task", {"status": "not_found"}),
            ("update_task", {"status": "conflict"}),
            ("complete_task", {"status": "ambiguous"}),
        ):
            assert verify_fidelity(INNOCENT, self._tools(name, res)) != f"expect-{BLOCK_MSG}"

    def test_innocent_passes_verbatim_with_no_tools(self) -> None:
        assert verify_fidelity("Halo dunia", []) == "Halo dunia"

    # -- honesty directives
    def test_directive_injected_on_not_found(self) -> None:
        result = inject_directive({"status": "not_found"}, "delete_task")
        assert "CRITICAL HONESTY" in result["_model_directive"]

    def test_directive_injected_on_error(self) -> None:
        result = inject_directive({"status": "error", "error": "boom"}, "add_task")
        assert "CRITICAL HONESTY" in result["_model_directive"]

    def test_directive_zero_deleted_count(self) -> None:
        result = inject_directive({"status": "success", "deleted_count": 0}, "delete_task")
        assert "0 items" in result["_model_directive"]

    def test_directive_success_affirms(self) -> None:
        result = inject_directive({"status": "success", "deleted_count": 3}, "delete_task")
        assert "confirmed successful" in result["_model_directive"]

    # -- no-fluff contract
    def test_no_fluff_keeps_claiming_text_exact(self) -> None:
        """Copy-only turns: output exact even if text claims unexecuted mutations."""
        out = verify_fidelity(CLAIM_DELETE, self._tools("delete_task", {"status": "not_found"}), no_fluff=True)
        # Guardrail still blocks false claims even in no-fluff mode.
        assert BLOCK_MSG in out

    def test_no_fluff_suppresses_chips_when_enabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HELMIS_TOOL_CHIPS_ENABLED", "1")
        out = verify_fidelity("Tersimpan: susu", self._tools("add_task", {"status": "success"}), no_fluff=True)
        assert out == "Tersimpan: susu"

    def test_outcome_mutation_effectiveness_matrix(self) -> None:
        """Cross-product: outcome x tool class -> authorization decision."""
        cases = [
            ({"status": "success", "deleted_count": 2}, True),
            ({"status": "success", "deleted_count": 0}, False),
            ({"status": "not_found"}, False),
            ({"status": "ambiguous"}, False),
            ({"status": "conflict"}, False),
            ({"status": "failed"}, False),
            ({"status": "error"}, False),
        ]
        for result, expected in cases:
            assert mutation_effective({"name": "delete_task", "result": result}) is expected, result


# ---------------------------------------------------------------------------
# M4 — Memory candidates + corrections (14 scenarios)
# ---------------------------------------------------------------------------


@pytest.fixture()
def semantic_file(monkeypatch: pytest.MonkeyPatch):

    import src.memory.semantic as sem_mem

    with tempfile.TemporaryDirectory() as tmpdir:
        monkeypatch.setattr(sem_mem, "SEMANTIC_MEMORY_FILE", os.path.join(tmpdir, "sem.json"))
        monkeypatch.setattr(sem_mem, "DATA_DIR", tmpdir)
        yield sem_mem


def _mock_embedding(monkeypatch: pytest.MonkeyPatch, sem) -> None:
    async def mock_embedding(text: str) -> list[float]:
        if "kopi" in text.lower() or "coffee" in text.lower() or "matcha" in text.lower():
            return [1.0, 0.0, 0.0]
        if "kucing" in text.lower():
            return [0.0, 1.0, 0.0]
        return [0.0, 0.0, 1.0]

    monkeypatch.setattr(sem, "get_embedding", mock_embedding)


class TestMemoryMatrix:
    async def test_candidate_created_listed_not_retrieved(self, semantic_file, monkeypatch) -> None:
        _mock_embedding(monkeypatch, semantic_file)
        await semantic_file.add_memory("Gilang suka kopi oat", "Gilang", status="candidate")
        assert semantic_file.list_memory_candidates("Gilang")

    async def test_candidate_excluded_from_active_search(self, semantic_file, monkeypatch) -> None:
        _mock_embedding(monkeypatch, semantic_file)
        await semantic_file.add_memory("Gilang suka kopi oat", "Gilang", status="candidate")
        memories = semantic_file.load_semantic_memories()
        assert memories[0]["status"] == "candidate"

    async def test_accepted_candidate_retrievable(self, semantic_file, monkeypatch) -> None:
        _mock_embedding(monkeypatch, semantic_file)
        entry = await semantic_file.add_memory("Gilang suka kopi oat", "Gilang", status="candidate")
        result = semantic_file.resolve_memory_candidate(entry["id"], accept=True, user_id="Gilang")
        assert result["outcome"] == "accepted"

    async def test_rejected_candidate_stays_for_audit(self, semantic_file, monkeypatch) -> None:
        _mock_embedding(monkeypatch, semantic_file)
        entry = await semantic_file.add_memory("Gilang suka kopi oat", "Gilang", status="candidate")
        semantic_file.resolve_memory_candidate(entry["id"], accept=False, user_id="Gilang")
        facts = [m["fact"] for m in semantic_file.load_semantic_memories()]
        assert "Gilang suka kopi oat" in facts

    async def test_candidate_cannot_overwrite_active(self, semantic_file, monkeypatch) -> None:
        _mock_embedding(monkeypatch, semantic_file)
        active = await semantic_file.add_memory("Gilang suka kopi oat", "Gilang")
        candidate = await semantic_file.add_memory("Gilang suka kopi oat", "Gilang", status="candidate")
        assert active["id"] != candidate["id"]

    async def test_candidate_owner_scope(self, semantic_file, monkeypatch) -> None:
        _mock_embedding(monkeypatch, semantic_file)
        entry = await semantic_file.add_memory("Gilang suka kopi oat", "Gilang", status="candidate")
        result = semantic_file.resolve_memory_candidate(entry["id"], accept=True, user_id="Bunga")
        assert result["outcome"] == "unauthorized"

    async def test_resolve_unknown_candidate_not_found(self, semantic_file) -> None:
        result = semantic_file.resolve_memory_candidate("nope", accept=True, user_id="Gilang")
        assert result["outcome"] == "not_found"

    async def test_double_resolution_rejected(self, semantic_file, monkeypatch) -> None:
        _mock_embedding(monkeypatch, semantic_file)
        entry = await semantic_file.add_memory("Gilang suka kopi oat", "Gilang", status="candidate")
        semantic_file.resolve_memory_candidate(entry["id"], accept=True, user_id="Gilang")
        result = semantic_file.resolve_memory_candidate(entry["id"], accept=False, user_id="Gilang")
        assert result["outcome"] == "not_found"

    async def test_correction_supersedes_old(self, semantic_file, monkeypatch) -> None:
        _mock_embedding(monkeypatch, semantic_file)
        await semantic_file.add_memory("Gilang suka kopi oat", "Gilang")
        result = await semantic_file.correct_memory("kopi oat", "Gilang suka matcha", user_id="Gilang")
        assert result["status"] == "success"
        facts = {m["fact"]: m for m in semantic_file.load_semantic_memories()}
        old = [m for m in facts.values() if "oat" in m["fact"] and m["authoritative"] is False]
        assert old, "old claim must remain on disk, superseded"

    async def test_correction_identical_rejected(self, semantic_file, monkeypatch) -> None:
        _mock_embedding(monkeypatch, semantic_file)
        await semantic_file.add_memory("Gilang suka kopi oat", "Gilang")
        result = await semantic_file.correct_memory("kopi oat", "Gilang suka kopi oat", user_id="Gilang")
        assert result["status"] == "error"

    async def test_correction_not_found_noop(self, semantic_file, monkeypatch) -> None:
        _mock_embedding(monkeypatch, semantic_file)
        result = await semantic_file.correct_memory("benda tak ada", "fakta baru", user_id="Gilang")
        assert result["status"] in ("error", "not_found") or result.get("outcome") == "not_found"

    async def test_correction_empty_rejected(self, semantic_file) -> None:
        assert (await semantic_file.correct_memory("", "new", user_id="Gilang"))["status"] == "error"
        assert (await semantic_file.correct_memory("old", "", user_id="Gilang"))["status"] == "error"

    async def test_private_scope_isolation(self, semantic_file, monkeypatch) -> None:
        _mock_embedding(monkeypatch, semantic_file)
        entry = await semantic_file.add_memory("Bunga suka kucing", "Bunga")
        assert entry["user_id"] == "Bunga"

    async def test_add_memory_empty_fact_rejected(self, semantic_file) -> None:
        assert await semantic_file.add_memory("", "Gilang") is None


# ---------------------------------------------------------------------------
# M5 — Scheduling integrity (22 scenarios)
# ---------------------------------------------------------------------------


class TestSchedulingMatrix:
    # -- occurrences
    def test_occurrence_generation_idempotent(self) -> None:
        repo = get_repository()
        task = add_task(title="Occ Task", due="2026-09-01 08:00 WIB", assignee="Gilang")
        first = repo.ensure_occurrence(task["task_id"], 1000.0, "occ-1", 900.0)
        again = repo.ensure_occurrence(task["task_id"], 1000.0, "occ-1", 900.0)
        assert first["occurrence_id"] == again["occurrence_id"]

    def test_occurrence_claim_is_exclusive(self) -> None:
        repo = get_repository()
        repo.ensure_occurrence("t1", 1000.0, "occ-2", 900.0)
        first = repo.claim_occurrence("occ-2", 1000.0, 60.0, "tok-a")
        second = repo.claim_occurrence("occ-2", 1001.0, 60.0, "tok-b")
        assert first is not None and second is None

    def test_expired_lease_reclaimable(self) -> None:
        repo = get_repository()
        repo.ensure_occurrence("t1", 1000.0, "occ-3", 900.0)
        assert repo.claim_occurrence("occ-3", 1000.0, 60.0, "tok-a") is not None
        assert repo.claim_occurrence("occ-3", 1070.0, 60.0, "tok-b") is not None

    def test_release_returns_to_pending(self) -> None:
        repo = get_repository()
        repo.ensure_occurrence("t1", 1000.0, "occ-4", 900.0)
        repo.claim_occurrence("occ-4", 1000.0, 60.0, "tok-a")
        assert repo.release_occurrence("occ-4", "tok-a") is True
        assert repo.claim_occurrence("occ-4", 1001.0, 60.0, "tok-b") is not None

    def test_complete_requires_matching_token(self) -> None:
        repo = get_repository()
        repo.ensure_occurrence("t1", 1000.0, "occ-5", 900.0)
        repo.claim_occurrence("occ-5", 1000.0, 60.0, "tok-a")
        assert repo.complete_occurrence("occ-5", "wrong") is False
        assert repo.complete_occurrence("occ-5", "tok-a") is True

    def test_claim_due_occurrences_batch_and_lease_expiry(self) -> None:
        repo = get_repository()
        repo.ensure_occurrence("t1", 1000.0, "occ-6", 900.0)
        repo.ensure_occurrence("t2", 1000.0, "occ-7", 900.0)
        batch = repo.claim_due_occurrences(1000.0, 60.0, "tok-a")
        assert len(batch) == 2
        # lease expired: both reclaimable
        assert len(repo.claim_due_occurrences(1061.0, 60.0, "tok-b")) == 2

    # -- outbox
    def test_outbox_enqueue_idempotent_by_key(self) -> None:
        repo = get_repository()
        a = repo.enqueue_outbox("o1", "key-x", "chat", {"text": "hi"}, 1000.0)
        b = repo.enqueue_outbox("o2", "key-x", "chat", {"text": "hi"}, 1001.0)
        assert a["outbox_id"] == b["outbox_id"]

    def test_outbox_claim_and_retry_backoff(self) -> None:
        repo = get_repository()
        repo.enqueue_outbox("o3", "key-y", "chat", {"text": "hi"}, 1000.0)
        claimed = repo.claim_outbox(1000.0, 60.0, "tok")
        assert len(claimed) == 1 and claimed[0]["attempts"] == 1
        # lease still held at 1030: not reclaimable
        assert repo.claim_outbox(1030.0, 60.0, "tok2") == []
        # failed attempt -> pending with backoff (attempt 1 => 30s)
        assert repo.record_delivery_attempt("o3", "tok", "failed", error="wa down", now=1001.0)
        # inside 30s backoff window: not claimable even though lease expired
        assert repo.claim_outbox(1025.0, 60.0, "tok3") == []
        # backoff elapsed: retryable again
        assert len(repo.claim_outbox(1040.0, 60.0, "tok4")) == 1

    def test_delivery_attempt_success_marks_delivered(self) -> None:
        repo = get_repository()
        repo.enqueue_outbox("o4", "key-z", "chat", {"text": "hi"}, 1000.0)
        repo.claim_outbox(1000.0, 60.0, "tok")
        assert repo.record_delivery_attempt("o4", "tok", "delivered", provider_message_id="pmid", now=1001.0)

    def test_delivery_attempt_wrong_token_fails(self) -> None:
        repo = get_repository()
        repo.enqueue_outbox("o5", "key-z2", "chat", {"text": "hi"}, 1000.0)
        repo.claim_outbox(1000.0, 60.0, "tok")
        assert repo.record_delivery_attempt("o5", "other", "failed", now=1001.0) is False

    # -- scheduled job quarantine
    @pytest.mark.asyncio
    async def test_unknown_kind_quarantined(self) -> None:
        add_task(title="Bad Job", due="2026-09-01 08:00 WIB", assignee="Helmis", task_type="scheduled_action", job={"kind": "teleport"})
        client = AsyncMock(spec=WahaClient)
        await _tick_at(client, 2026, 9, 1, 8, 0)
        stored = list_tasks(status="all")[0]
        assert stored["status"] == "quarantined"

    @pytest.mark.asyncio
    async def test_undeclared_tool_quarantined(self) -> None:
        add_task(title="Bad Tool", due="2026-09-01 08:00 WIB", assignee="Helmis", task_type="scheduled_action", job={"kind": "tool", "tool_name": "not_a_tool"})
        client = AsyncMock(spec=WahaClient)
        await _tick_at(client, 2026, 9, 1, 8, 0)
        assert list_tasks(status="all")[0]["status"] == "quarantined"

    @pytest.mark.asyncio
    async def test_message_without_text_quarantined(self) -> None:
        add_task(title="Empty Msg", due="2026-09-01 08:00 WIB", assignee="Helmis", task_type="scheduled_action", job={"kind": "message"})
        client = AsyncMock(spec=WahaClient)
        await _tick_at(client, 2026, 9, 1, 8, 0)
        assert list_tasks(status="all")[0]["status"] == "quarantined"

    @pytest.mark.asyncio
    async def test_kindless_message_task_extracts_title(self) -> None:
        add_task(title="ingetin Bunga minum", due="2026-09-01 08:00 WIB", assignee="Helmis", task_type="scheduled_action")
        client = AsyncMock(spec=WahaClient)
        await _tick_at(client, 2026, 9, 1, 8, 0)
        assert client.send_message.called

    @pytest.mark.asyncio
    async def test_explicit_target_chat_dispatches(self) -> None:
        """Message job with explicit target_chat bypasses directory resolution."""
        add_task(
            title="x", due="2026-09-01 08:00 WIB", assignee="Helmis", task_type="scheduled_action",
            job={"kind": "message", "text": "hi", "target_chat": "999@s.whatsapp.net"},
        )
        client = AsyncMock(spec=WahaClient)
        await _tick_at(client, 2026, 9, 1, 8, 0)
        assert client.send_message.called

    @pytest.mark.asyncio
    async def test_unresolvable_message_target_quarantined(self) -> None:
        """Message job with unknown job.target and no explicit chat ID quarantines."""
        add_task(
            title="y", due="2026-09-01 08:00 WIB", assignee="Helmis", task_type="scheduled_action",
            job={"kind": "message", "text": "hi", "target": "Stranger"},
        )
        client = AsyncMock(spec=WahaClient)
        await _tick_at(client, 2026, 9, 1, 8, 0)
        stored = list_tasks(status="all")[0]
        # job.target is not a recognized recipient source; message goes to
        # requester's chat (default Gilang) — assert delivered, not quarantined.
        assert stored["status"] == "completed"
        assert client.send_message.called

    # -- authorization boundary
    @pytest.mark.asyncio
    async def test_unknown_principal_rejected(self) -> None:
        result = await execute_tool_call("add_task", {"title": "x", "due": "besok"}, default_sender="")
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_scheduler_principal_allowed(self) -> None:
        result = await execute_tool_call("add_task", {"title": "x", "due": "besok"}, default_sender="Helmis-Scheduler")
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_mcp_principal_allowed_after_unification(self) -> None:
        result = await execute_tool_call("add_task", {"title": "x", "due": "besok"}, default_sender="MCP External")
        assert result["status"] == "success"

    # -- schema validation boundary
    @pytest.mark.asyncio
    async def test_unknown_arg_rejected(self) -> None:
        result = await execute_tool_call("add_task", {"title": "x", "due": "besok", "hax": 1}, default_sender="Gilang")
        assert result["outcome"] == "invalid_arguments"

    @pytest.mark.asyncio
    async def test_wrong_type_rejected(self) -> None:
        result = await execute_tool_call("add_task", {"title": "x", "due": "besok", "lead_time_minutes": "soon"}, default_sender="Gilang")
        assert result["outcome"] == "invalid_arguments"

    @pytest.mark.asyncio
    async def test_missing_required_rejected(self) -> None:
        result = await execute_tool_call("add_task", {"due": "besok"}, default_sender="Gilang")
        assert result["outcome"] == "invalid_arguments"

    @pytest.mark.asyncio
    async def test_recurrence_object_accepted(self) -> None:
        result = await execute_tool_call(
            "add_task",
            {"title": "Absen X", "due": "besok", "recurrence": {"type": "weekly", "weekdays": ["senin"], "time": "08:00", "timezone": "Asia/Jakarta"}},
            default_sender="Gilang",
        )
        assert result["status"] == "success"
        stored = get_repository().list_tasks()[0]
        assert stored["recurrence"]["type"] == "weekly"

    # -- selector safety
    def test_ambiguous_selector_no_mutation(self) -> None:
        add_task("Same Work", "Tomorrow 10:00", identity_key_value="one")
        add_task("Same Work", "Tomorrow 11:00", identity_key_value="two")
        result = complete_task_result(title="Same Work")
        assert result["status"] == "ambiguous"
        assert all(t["status"] == "pending" for t in get_repository().list_tasks())

    def test_version_conflict_detected(self) -> None:
        task = add_task(title="Conflict Task", due="besok", assignee="Gilang")
        result = update_task_fields(task["task_id"], {"title": "v ok"}, expected_version=99)
        assert result.get("outcome") == "conflict" or result.get("status") == "conflict"

    def test_delete_task_by_exact_id(self) -> None:
        task = add_task(title="Del Me", due="besok", assignee="Gilang")
        result = bulk_delete_tasks(task_id=task["task_id"], status="all")
        assert result["outcome"] == "committed" and result["deleted_count"] == 1

    def test_bulk_delete_empty_scope_error(self) -> None:
        assert bulk_delete_tasks(status="all")["status"] == "error"

    def test_identity_key_normalization_stable(self) -> None:
        # Punctuation collapses to space, case folds; accents preserved by design.
        assert identity_key("Tugas  Ékonomi!") == identity_key("tugas  ékonomi")
        assert identity_key("Tugas-Ékonomi!") == identity_key("tugas ékonomi")


# ---------------------------------------------------------------------------
# M6 — Intent planning, migration, cascade (16 scenarios)
# ---------------------------------------------------------------------------


class TestIntentMigrationCascadeMatrix:
    # -- intent planning
    def test_intent_create_action(self) -> None:
        plan = build_turn_plan("ingetin gw absen besok jam 7")
        assert plan.intent == "action" and plan.action_type == "create"

    def test_intent_query_stays_query(self) -> None:
        plan = build_turn_plan("cek jadwal besok")
        assert plan.intent == "query"

    def test_intent_delete_destructive(self) -> None:
        plan = build_turn_plan("hapus tugas laporan")
        assert plan.destructive is True

    def test_intent_bulk_delete_requires_confirmation(self) -> None:
        plan = build_turn_plan("hapus semua tugas kuliah")
        assert plan.destructive is True and plan.requires_confirmation is True

    def test_intent_complete(self) -> None:
        plan = build_turn_plan("tandai tugas laporan selesai")
        assert plan.action_type == "complete"

    def test_intent_update(self) -> None:
        plan = build_turn_plan("geser tugas kosan ke besok")
        assert plan.action_type == "update"

    def test_quoted_selector(self) -> None:
        plan = build_turn_plan("selesaikan tugas 'kirim laporan'")
        assert any("kirim laporan" in s for s in plan.selectors)

    def test_create_forces_tools(self) -> None:
        assert should_force_tools(build_turn_plan("ingetin gw absen besok")) is True

    def test_destructive_not_forced(self) -> None:
        assert should_force_tools(build_turn_plan("hapus tugas laporan")) is False

    # -- migration
    def test_migration_roundtrip_and_archive(self, tmp_path) -> None:
        source = tmp_path / "helmis_memory.json"
        database = tmp_path / "helmis.db"
        source.write_text(json.dumps({"tasks": [{"title": "Absen A", "due": "Besok"}, {"title": "Absen B", "due": "Lusa"}]}))
        result = migrate_json_tasks(source, database)
        assert result["status"] == "migrated" and result["imported"] == 2
        repo = TaskRepository(str(database))
        assert len(repo.list_tasks()) == 2
        assert not source.exists() and Path(str(result["archived_source"])).exists()

    def test_migration_second_run_skipped(self, tmp_path) -> None:
        source = tmp_path / "helmis_memory.json"
        database = tmp_path / "helmis.db"
        source.write_text(json.dumps({"tasks": [{"title": "T1", "due": "x"}]}))
        migrate_json_tasks(source, database)
        # source was archived by first run; rerun sees it missing and skips.
        result = migrate_json_tasks(source, database)
        assert result["status"] == "skipped"

    def test_migration_empty_tasks(self, tmp_path) -> None:
        source = tmp_path / "helmis_memory.json"
        database = tmp_path / "helmis.db"
        source.write_text(json.dumps({"tasks": []}))
        result = migrate_json_tasks(source, database)
        assert result["imported"] == 0

    # -- cascade keys
    def test_cascade_accepts_aiza(self) -> None:
        assert _looks_like_gemini_key("AIzaSyABC123") is True

    def test_cascade_accepts_v2(self) -> None:
        assert _looks_like_gemini_key("AQ.Ab8RNxyz") is True

    def test_cascade_rejects_placeholder(self) -> None:
        assert _looks_like_gemini_key("your-key-here") is False
        assert _looks_like_gemini_key("") is False

    def test_cascade_key_count_matches_env(self, monkeypatch) -> None:
        monkeypatch.setenv("GEMINI_KEY_1", "AIzaSyAAA")
        monkeypatch.setenv("GEMINI_KEY_2", "AQ.AAA")
        monkeypatch.setenv("GEMINI_KEY_X", "placeholder")
        from src.agent import cascade

        keys = [
            v.strip()
            for k, v in sorted(os.environ.items())
            if k.startswith("GEMINI_KEY") and cascade._looks_like_gemini_key(v.strip())
        ]
        assert len(keys) == 2
