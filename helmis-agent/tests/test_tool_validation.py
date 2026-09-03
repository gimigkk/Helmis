"""
test_tool_validation.py — Schema validation boundary and parallel function-call handling.

Covers the Phase 2 gate: tool arguments are validated against the declared
Gemini schema at dispatch, and the agent loop handles full content-part lists
including multiple parallel functionCalls in a single model response.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agent.loop import run_agentic_react_loop
from src.tools.registry import execute_tool_call

# ---------------------------------------------------------------------------
# 1. Schema validation boundary (registry dispatch)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_argument_is_rejected_before_handler() -> None:
    result = await execute_tool_call(
        "add_task",
        {"title": "X", "due": "besok", "task_id_or_title": "alias-key"},
        default_sender="Gilang",
    )
    assert result["status"] == "error"
    assert result["outcome"] == "invalid_arguments"
    assert "task_id_or_title" in result["error"]


@pytest.mark.asyncio
async def test_wrong_type_argument_is_rejected() -> None:
    result = await execute_tool_call(
        "add_task",
        {"title": "X", "due": "besok", "lead_time_minutes": "dua jam"},
        default_sender="Gilang",
    )
    assert result["outcome"] == "invalid_arguments"
    assert "lead_time_minutes" in result["error"]


@pytest.mark.asyncio
async def test_missing_required_argument_is_rejected() -> None:
    result = await execute_tool_call("add_task", {"due": "besok"}, default_sender="Gilang")
    assert result["outcome"] == "invalid_arguments"
    assert "title" in result["error"]


@pytest.mark.asyncio
async def test_rejected_arguments_never_reach_repository() -> None:
    from src.memory.store import list_tasks

    before = len(list_tasks(status="all"))
    await execute_tool_call(
        "add_task",
        {"title": "Must not exist", "due": "besok", "nonsense": 1},
        default_sender="Gilang",
    )
    assert len(list_tasks(status="all")) == before


@pytest.mark.asyncio
async def test_valid_arguments_pass_through() -> None:
    result = await execute_tool_call(
        "add_task",
        {"title": "Valid task", "due": "besok 09:00", "assignee": "Gilang"},
        default_sender="Gilang",
    )
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_undeclared_tool_bypasses_validation() -> None:
    # Internal tools without schema declarations must not be blocked.
    result = await execute_tool_call("totally_unknown_tool", {"anything": 1}, default_sender="Helmis-Scheduler")
    assert result["status"] == "error"  # unknown tool error, not invalid_arguments
    assert result.get("outcome") != "invalid_arguments"


def test_update_task_schema_now_declares_status_and_policy_args() -> None:
    from src.tools.schema import GEMINI_TOOLS

    decls = {d["name"]: d for d in GEMINI_TOOLS[0]["function_declarations"]}
    update_props = decls["update_task"]["parameters"]["properties"]
    for key in ("new_status", "recurrence", "nag_interval_minutes", "max_nags"):
        assert key in update_props
    remember_props = decls["remember_fact"]["parameters"]["properties"]
    assert "scope" in remember_props and "source_turn_id" in remember_props


# ---------------------------------------------------------------------------
# 2. Parallel function-call + full content-part handling (agent loop)
# ---------------------------------------------------------------------------


def _resp(parts: list[dict[str, Any]]) -> MagicMock:
    m = MagicMock()
    m.status_code = 200
    m.json.return_value = {"candidates": [{"content": {"parts": parts}}]}
    return m


@pytest.mark.asyncio
async def test_multiple_function_calls_in_one_response_all_execute() -> None:
    """Gemini may emit parallel functionCalls; every call must execute."""
    mock_client = AsyncMock()
    mock_client.get_messages = AsyncMock(return_value=[])

    parallel_response = _resp(
        [
            {"text": "Saya catat dua tugas ini ya."},
            {
                "functionCall": {
                    "name": "add_task",
                    "args": {"title": "Tugas A", "due": "besok 10:00", "assignee": "Gilang"},
                }
            },
            {
                "functionCall": {
                    "name": "add_task",
                    "args": {"title": "Tugas B", "due": "besok 11:00", "assignee": "Bunga"},
                }
            },
        ]
    )
    final_response = _resp([{"text": "Dua tugas sudah dicatat."}])

    mock_post = AsyncMock(side_effect=[parallel_response, final_response])

    with patch("httpx.AsyncClient.post", mock_post), \
         patch("src.agent.cascade.GEMINI_KEYS", ["test_key"]), \
         patch("src.agent.loop.get_cascade_models", return_value=["gemini-test-model"]):
        reply = await run_agentic_react_loop(
            client=mock_client,
            sender_name="Gilang",
            chat_id="628111111111@c.us",
            message_text="Catat tugas A dan B",
            max_steps=5,
        )

    assert reply is not None
    assert "Dua tugas sudah dicatat" in reply

    from src.memory.store import list_tasks

    titles = {t["title"] for t in list_tasks(status="all")}
    assert "Tugas A" in titles and "Tugas B" in titles

    # Model turn preserved all parts; function responses appended in one user turn
    sent_payload = mock_post.call_args_list[1].kwargs["json"] if mock_post.call_args_list[1].kwargs else mock_post.call_args_list[1].args[1]
    contents = sent_payload["contents"]
    model_turns = [c for c in contents if c["role"] == "model"]
    assert model_turns, "model turn must be appended to contents"
    model_turn = model_turns[-1]
    assert len(model_turn["parts"]) == 3
    response_turn = contents[contents.index(model_turn) + 1]
    assert response_turn["role"] == "user"
    assert len(response_turn["parts"]) == 2
    assert all("functionResponse" in p for p in response_turn["parts"])


@pytest.mark.asyncio
async def test_text_and_function_call_same_turn_preserves_text() -> None:
    """Interleaved text part before a functionCall survives into conversation history."""
    mock_client = AsyncMock()
    mock_client.get_messages = AsyncMock(return_value=[])

    mixed = _resp(
        [
            {"text": "Cek dulu ya."},
            {"functionCall": {"name": "list_tasks", "args": {"status": "pending"}}},
        ]
    )
    final = _resp([{"text": "Tidak ada tugas pending."}])
    mock_post = AsyncMock(side_effect=[mixed, final])

    with patch("httpx.AsyncClient.post", mock_post), \
         patch("src.agent.cascade.GEMINI_KEYS", ["test_key"]), \
         patch("src.agent.loop.get_cascade_models", return_value=["gemini-test-model"]):
        reply = await run_agentic_react_loop(
            client=mock_client,
            sender_name="Gilang",
            chat_id="628111111111@c.us",
            message_text="Ada tugas apa saja?",
            max_steps=5,
        )

    assert reply is not None
    sent_payload = mock_post.call_args_list[1].kwargs["json"] if mock_post.call_args_list[1].kwargs else mock_post.call_args_list[1].args[1]
    contents = sent_payload["contents"]
    model_turns = [c for c in contents if c["role"] == "model"]
    model_turn = model_turns[-1]
    assert model_turn["parts"][0]["text"] == "Cek dulu ya."
    assert "functionCall" in model_turn["parts"][1]


@pytest.mark.asyncio
async def test_empty_parts_list_does_not_crash() -> None:
    """A candidate with no usable parts falls through to final synthesis instead of raising."""
    mock_client = AsyncMock()
    mock_client.get_messages = AsyncMock(return_value=[])

    empty = _resp([])
    calls: list[Any] = []

    async def always_empty(self: Any, *args: Any, **kwargs: Any) -> Any:
        calls.append(args)
        return empty

    with patch("httpx.AsyncClient.post", always_empty), \
         patch("src.agent.cascade.GEMINI_KEYS", ["test_key"]), \
         patch("src.agent.loop.get_cascade_models", return_value=["gemini-test-model"]):
        reply = await run_agentic_react_loop(
            client=mock_client,
            sender_name="Gilang",
            chat_id="628111111111@c.us",
            message_text="halo",
            max_steps=3,
        )

    # No tools ran and no text arrived -> silent turn
    assert reply is None
