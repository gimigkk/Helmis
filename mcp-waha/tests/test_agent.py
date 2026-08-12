"""
test_agent.py — Tests for tool dispatching and tool schema declarations.
"""

import os
import tempfile
from collections.abc import Generator

import pytest

import src.agent as agent
import src.memory as memory


@pytest.fixture(autouse=True)
def temp_memory_file(monkeypatch: pytest.MonkeyPatch) -> Generator[str, None, None]:
    """Use temporary file for memory testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_file = os.path.join(tmpdir, "test_memory.json")
        monkeypatch.setattr(memory, "MEMORY_FILE", tmp_file)
        monkeypatch.setattr(memory, "DATA_DIR", tmpdir)
        yield tmp_file


def test_gemini_tools_schema_valid() -> None:
    assert len(agent.GEMINI_TOOLS) > 0
    func_decls = agent.GEMINI_TOOLS[0]["function_declarations"]
    tool_names = [f["name"] for f in func_decls]
    assert "add_task" in tool_names
    assert "list_tasks" in tool_names
    assert "delete_task" in tool_names
    assert "add_person" in tool_names
    assert "search_memory" in tool_names


async def test_execute_tool_call_add_and_list_task() -> None:
    res = await agent.execute_tool_call(
        func_name="add_task",
        args={"title": "Buy milk", "due": "Today 19:00 WIB", "assignee": "Gilang"},
        default_sender="Gilang",
    )
    assert res["status"] == "success"

    res_complete = await agent.execute_tool_call(
        func_name="complete_task",
        args={"title": "Buy milk"},
        default_sender="Gilang",
    )
    assert res_complete["status"] == "success"
    assert res_complete["task"]["status"] == "completed"

    res_list = await agent.execute_tool_call(
        func_name="list_tasks",
        args={"status": "pending"},
        default_sender="Gilang",
    )
    assert res_list["status"] == "success"
    assert res_list["count"] == 0


async def test_execute_tool_call_empty_title_error() -> None:
    res = await agent.execute_tool_call(
        func_name="add_task",
        args={"title": "", "due": "Today 19:00 WIB"},
        default_sender="Gilang",
    )
    assert res["status"] == "error"
    assert "Judul task tidak boleh kosong" in res["error"]


async def test_execute_tool_call_send_whatsapp_message() -> None:
    from unittest.mock import AsyncMock, MagicMock

    mock_client = MagicMock()
    mock_client.send_message = AsyncMock(return_value="msg_123")

    res = await agent.execute_tool_call(
        func_name="send_whatsapp_message",
        args={"recipient": "Bunga", "text": "Halo Bunga!", "quote_message_id": "wamid_999"},
        default_sender="Gilang",
        client=mock_client,
    )
    assert res["status"] == "success"
    mock_client.send_message.assert_called_once_with(
        chat_id="6281398971445@c.us",
        text="Halo Bunga!",
        reply_to_message_id="wamid_999",
    )
