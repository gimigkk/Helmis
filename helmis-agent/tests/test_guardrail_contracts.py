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


def test_no_fluff_keeps_exact_copy_output() -> None:
    """Corpus 'no-fluff-copy' contract: final text identical, no chips appended."""
    exact_output = "Halo, ini pesan yang harus bisa di-copy persis"
    tools = [{"name": "read_vault_file", "result": {"status": "success", "content": "..."}}]
    out = verify_action_fidelity(exact_output, tools, no_fluff=True)
    assert out == exact_output


def test_chips_still_appended_for_normal_turns() -> None:
    tools = [{"name": "add_task", "result": {"status": "success"}}]
    out = verify_action_fidelity("Tersimpan ya.", tools)
    assert "↳ `add_task`" in out
