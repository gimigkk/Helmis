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
    bunga_phone = os.environ.get("BUNGA_PHONE", "").replace("+", "").replace(" ", "").replace("-", "")
    expected_chat = f"{bunga_phone}@c.us" if bunga_phone else "628222222222@c.us"
    if bunga_phone:
        mock_client.send_message.assert_called_once_with(
            chat_id=expected_chat,
            text="Halo Bunga!",
            reply_to_message_id="wamid_999",
        )


async def test_execute_tool_call_get_whatsapp_messages() -> None:
    from unittest.mock import AsyncMock, MagicMock

    from src.models import WahaHistoryMessage

    mock_client = MagicMock()
    mock_client.get_messages = AsyncMock(
        return_value=[
            WahaHistoryMessage(
                message_id="msg_1",
                sender_phone="628222222222@c.us",
                text="Halo",
                media_url=None,
                timestamp=1700000000,
            )
        ]
    )

    res = await agent.execute_tool_call(
        func_name="get_whatsapp_messages",
        args={"target": "Bunga", "limit": 5},
        default_sender="Gilang",
        client=mock_client,
    )
    assert res["status"] == "success"
    assert res["count"] == 1
    assert res["messages"][0]["text"] == "Halo"
    assert "time" in res["messages"][0]
    mock_client.get_messages.assert_called_once()


async def test_execute_tool_call_save_and_delete_note() -> None:
    res_save = await agent.execute_tool_call(
        func_name="save_note",
        args={"title": "WiFi Password", "content": "secret123"},
        default_sender="Gilang",
    )
    assert res_save["status"] == "success"

    res_del = await agent.execute_tool_call(
        func_name="delete_note",
        args={"title": "WiFi"},
        default_sender="Gilang",
    )
    assert res_del["status"] == "success"


async def test_execute_tool_call_delete_memory() -> None:
    from unittest.mock import patch

    with patch("src.semantic_memory.delete_memory", return_value={"status": "success", "deleted_count": 1}):
        res = await agent.execute_tool_call(
            func_name="delete_memory",
            args={"query": "kopi manis"},
            default_sender="Gilang",
        )
        assert res["status"] == "success"


def test_verify_action_fidelity_catches_false_delete() -> None:
    # Model claims it deleted, but tools returned not_found (0 deleted)
    tools_failed = [{"name": "delete_memory", "result": {"status": "not_found", "deleted_count": 0}}]
    corrected = agent.verify_action_fidelity("Sip, memori tersebut sudah saya hapus.", tools_failed)
    assert "tidak ditemukan" in corrected.lower()

    # Model claims it deleted, but 0 tools were executed
    corrected_no_tools = agent.verify_action_fidelity("Sip, memori tersebut sudah saya hapus.", [])
    assert "tidak ditemukan" in corrected_no_tools.lower()

    # Model claims it deleted, and delete succeeded
    tools_success = [{"name": "delete_memory", "result": {"status": "success", "deleted_count": 1}}]
    verified = agent.verify_action_fidelity("Sip, memori tersebut sudah saya hapus.", tools_success)
    assert verified == "Sip, memori tersebut sudah saya hapus."


def test_verify_action_fidelity_catches_false_save() -> None:
    # Model claims it saved to memory during photo analysis, but never called remember_fact
    false_claim = "Gambar ini menunjukkan sepiring makanan. Sudah saya simpan ke memori."
    cleaned = agent.verify_action_fidelity(false_claim, [])
    assert "Sudah saya simpan ke memori" not in cleaned
    assert "Gambar ini menunjukkan sepiring makanan" in cleaned

