import json
from pathlib import Path

from src.agent.guardrails import classify_turn_intent, verify_action_fidelity

CORPUS = Path(__file__).parents[2] / "docs" / "production-evidence" / "regression_cases.json"


def _cases() -> list[dict[str, object]]:
    payload = json.loads(CORPUS.read_text(encoding="utf-8"))
    return payload["cases"]


def test_production_corpus_is_complete_and_sanitized() -> None:
    cases = _cases()
    assert len(cases) == 14
    assert all(case.get("id") and case.get("expected_invariants") for case in cases)


def test_no_fluff_cases_are_read_only_and_have_no_fake_chips() -> None:
    cases = {case["id"]: case for case in _cases()}
    for case_id in ("no-fluff-copy", "no-fluff-mutation", "explicit-no-tool"):
        case = cases[case_id]
        assert classify_turn_intent(str(case["input_text"])) != "action"
        assert verify_action_fidelity(str(case["final_reply"]), []) == str(case["final_reply"]).split("\n\n↳")[0]


def test_unexecuted_mutation_claims_are_blocked() -> None:
    cases = {case["id"]: case for case in _cases()}
    preference = str(cases["preference-without-mutation"]["final_reply"])
    # A preference acknowledgement is not itself a durable mutation claim.
    assert verify_action_fidelity(preference, []) == preference

    vision_reply = str(cases["vision-recheck-confirmation"]["final_reply"])
    assert verify_action_fidelity(vision_reply, []) != vision_reply


def test_corpus_preserves_required_tool_order_contracts() -> None:
    cases = {case["id"]: case for case in _cases()}
    duplicate = cases["duplicate-create-update"]
    assert [step["name"] for step in duplicate["tools"]] == ["add_task", "update_task"]
    bulk_delete = cases["scoped-bulk-delete"]
    assert all(step["name"] != "delete_task" or step["args"].get("title") for step in bulk_delete["tools"])
