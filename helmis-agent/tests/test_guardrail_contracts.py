"""
test_guardrail_contracts.py — Phase 2 guardrail fidelity contracts.

Covers:
- Read-only tool success never authorizes mutation claims in final text.
- Zero-count mutation results (deleted_count=0) never authorize success claims.
- not_found / ambiguous / conflict / failed outcomes preserved as failure language.
- No-fluff/copy-only turns suppress tool chips and keep output exact.
"""

import pytest

from src.agent.guardrails import (
    detect_unexecuted_mutation_claims,
    is_no_fluff_request,
    mutation_was_effective,
    verify_action_fidelity,
)

CLAIM = "Sip, tugas belanja sudah Helmis tandai selesai ya."


def test_read_only_success_does_not_authorize_mutation_claim() -> None:
    """list_tasks success + completed-claim text must still be flagged."""
    tools = [{"name": "list_tasks", "result": {"status": "success", "count": 3}}]
    assert detect_unexecuted_mutation_claims(CLAIM, tools) == "complete_task"


def test_mutation_with_deleted_count_zero_does_not_authorize() -> None:
    tools = [{"name": "delete_task", "result": {"status": "success", "deleted_count": 0}}]
    assert mutation_was_effective(tools[0]) is False
    text = "Sip, tugas belanja sudah Helmis hapus ya."
    assert detect_unexecuted_mutation_claims(text, tools) == "delete_action"


def test_effective_mutation_authorizes_claim() -> None:
    tools = [
        {"name": "complete_task", "result": {"status": "success", "task": {"task_id": "t1"}}},
        {"name": "delete_task", "result": {"status": "success", "deleted_count": 2}},
    ]
    assert mutation_was_effective(tools[0]) is True
    assert mutation_was_effective(tools[1]) is True
    assert detect_unexecuted_mutation_claims(CLAIM, tools[:1]) is None


@pytest.mark.parametrize("outcome", ["ambiguous", "conflict", "failed", "not_found"])
def test_structured_non_success_outcomes_do_not_authorize(outcome: str) -> None:
    tools = [{"name": "update_task", "result": {"status": "success", "outcome": outcome}}]
    assert mutation_was_effective(tools[0]) is False


def test_not_found_override_replaces_false_success_text() -> None:
    tools = [{"name": "delete_memory", "result": {"status": "not_found", "message": "Memori tidak ditemukan."}}]
    out = verify_action_fidelity("Sudah terhapus semua.", tools)
    assert "Memori tidak ditemukan." in out


def test_ambiguous_outcome_blocks_success_language() -> None:
    """Ambiguous update with completed-claim text must be blocked, not passed."""
    tools = [
        {
            "name": "complete_task",
            "result": {"status": "ambiguous", "candidates": [{"task_id": "a"}, {"task_id": "b"}]},
        }
    ]
    assert mutation_was_effective(tools[0]) is False
    out = verify_action_fidelity(CLAIM, tools)
    assert "belum berhasil diproses" in out


# ---------------------------------------------------------------------------
# No-fluff / copy-only suppression
# ---------------------------------------------------------------------------


def test_no_fluff_detection_matches_corpus_variants() -> None:
    assert is_no_fluff_request("No fluff biar bisa di copy")
    assert is_no_fluff_request("Kirim no fluff")
    assert is_no_fluff_request("Gausah tool call, kirim no fluff")
    assert is_no_fluff_request("Tanpa basa-basi ya")
    assert not is_no_fluff_request("Cek jadwal besok")
    assert not is_no_fluff_request("")


def test_no_fluff_suppresses_tool_chips() -> None:
    tools = [{"name": "add_task", "result": {"status": "success"}}]
    out = verify_action_fidelity("Tersimpan: belanja susu", tools, no_fluff=True)
    assert out == "Tersimpan: belanja susu"
    assert "↳" not in out


def test_chips_opt_out_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default: chips ON; explicit opt-out via env."""
    monkeypatch.delenv("HELMIS_TOOL_CHIPS_ENABLED", raising=False)
    tools = [{"name": "add_task", "result": {"status": "success"}}]
    out = verify_action_fidelity("Tersimpan ya.", tools)
    assert "↳ `add_task`" in out  # default on
    monkeypatch.setenv("HELMIS_TOOL_CHIPS_ENABLED", "0")
    out_off = verify_action_fidelity("Tersimpan ya.", tools)
    assert "↳" not in out_off


def test_chips_opt_in_enabled_for_normal_turns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HELMIS_TOOL_CHIPS_ENABLED", "1")
    tools = [{"name": "add_task", "result": {"status": "success"}}]
    out = verify_action_fidelity("Tersimpan ya.", tools)
    assert "↳ `add_task`" in out


def test_chips_opt_in_never_applies_to_no_fluff(monkeypatch: pytest.MonkeyPatch) -> None:
    """Even when chips enabled, no-fluff turns stay exact."""
    monkeypatch.setenv("HELMIS_TOOL_CHIPS_ENABLED", "1")
    tools = [{"name": "add_task", "result": {"status": "success"}}]
    out = verify_action_fidelity("Tersimpan: belanja susu", tools, no_fluff=True)
    assert out == "Tersimpan: belanja susu"
    assert "↳" not in out


def test_not_found_without_message_never_passes_model_success_claim() -> None:
    """not_found result carrying no message must still block success language."""
    tools = [{"name": "delete_task", "result": {"status": "not_found", "outcome": "not_found"}}]
    # Claiming language gets blocked outright by the mutation-claim detector.
    out = verify_action_fidelity("Sip, 3 task sudah Helmis hapus ya.", tools)
    assert "belum berhasil diproses" in out
    # Innocent text still gets replaced by the ground-truth no-match message.
    out = verify_action_fidelity("Oke, sudah kucek datanya.", tools)
    assert "Tidak ada data yang cocok" in out


def test_not_found_delete_task_handler_message_used_verbatim(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tool-supplied not_found message is enforced verbatim (override path, no chips)."""
    monkeypatch.setenv("HELMIS_TOOL_CHIPS_ENABLED", "0")
    tools = [
        {
            "name": "delete_task",
            "result": {"status": "not_found", "outcome": "not_found", "message": "Tidak ditemukan task dengan nama 'X'."},
        }
    ]
    out = verify_action_fidelity("Sudah terhapus semua.", tools)
    assert out == "Tidak ditemukan task dengan nama 'X'."
