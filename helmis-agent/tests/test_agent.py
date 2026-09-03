"""
test_agent.py — Tests for tool dispatching and tool schema declarations.
"""

import os

import src.agent as agent
import src.memory as memory


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


async def test_execute_tool_call_add_and_update_shared_task() -> None:
    res = await agent.execute_tool_call(
        func_name="add_task",
        args={
            "title": "Bayar sewa apartemen",
            "due": "Tomorrow 10:00 WIB",
            "assignee": "Both",
        },
        default_sender="Gilang",
    )
    assert res["status"] == "success"
    assert res["task"]["assignee"] == "Both"

    # Update to individual and back to Both
    res_up = await agent.execute_tool_call(
        func_name="update_task",
        args={"title": "Bayar sewa", "new_assignee": "Bunga"},
        default_sender="Gilang",
    )
    assert res_up["status"] == "success"
    assert res_up["task"]["assignee"] == "Bunga"

    res_clean = await agent.execute_tool_call(
        func_name="delete_task",
        args={"title": "Bayar sewa"},
        default_sender="Gilang",
    )
    assert res_clean["status"] == "success"


async def test_execute_tool_call_add_urgent_task_with_lead_time() -> None:
    res = await agent.execute_tool_call(
        func_name="add_task",
        args={
            "title": "Submit Proposal Hibah",
            "due": "Tomorrow 17:00 WIB",
            "assignee": "Gilang",
            "priority": "urgent",
            "lead_time_minutes": 120,
        },
        default_sender="Gilang",
    )
    assert res["status"] == "success"
    assert res["task"]["priority"] == "urgent"
    assert res["task"]["lead_time_minutes"] == 120

    # Update priority and lead time
    res_up = await agent.execute_tool_call(
        func_name="update_task",
        args={
            "title": "Submit Proposal",
            "new_priority": "normal",
            "new_lead_time_minutes": 60,
        },
        default_sender="Gilang",
    )
    assert res_up["status"] == "success"
    assert res_up["task"]["priority"] == "normal"
    assert res_up["task"]["lead_time_minutes"] == 60


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


async def test_execute_tool_call_send_whatsapp_message_cross_party() -> None:
    import os
    from unittest.mock import AsyncMock, patch

    mock_client = AsyncMock()
    mock_client.send_message = AsyncMock(return_value="sent_msg_id")

    with patch.dict(
        os.environ,
        {
            "GILANG_PHONE": "628111111111",
            "BUNGA_PHONE": "628222222222",
            "TRIO_GROUP_JID": "120363000000000000@g.us",
        },
    ):
        # 1. Message to Bunga
        res_bunga = await agent.execute_tool_call(
            func_name="send_whatsapp_message",
            args={"recipient": "Bunga", "text": "Halo Bunga dari Helmis"},
            default_sender="Gilang",
            client=mock_client,
        )
        assert res_bunga["status"] == "success"
        mock_client.send_message.assert_called_with(
            chat_id="628222222222@c.us",
            text="Halo Bunga dari Helmis",
            reply_to_message_id=None,
        )

        # 2. Message to Group
        res_group = await agent.execute_tool_call(
            func_name="send_whatsapp_message",
            args={"recipient": "group", "text": "Pengumuman ke grup"},
            default_sender="Gilang",
            client=mock_client,
        )
        assert res_group["status"] == "success"
        mock_client.send_message.assert_called_with(
            chat_id="120363000000000000@g.us",
            text="Pengumuman ke grup",
            reply_to_message_id=None,
        )

        # 3. Message to current / sender
        res_current = await agent.execute_tool_call(
            func_name="send_whatsapp_message",
            args={"recipient": "current", "text": "Sedang saya proses ya..."},
            default_sender="Gilang",
            client=mock_client,
        )
        assert res_current["status"] == "success"
        mock_client.send_message.assert_called_with(
            chat_id="628111111111@c.us",
            text="Sedang saya proses ya...",
            reply_to_message_id=None,
        )


async def test_execute_tool_call_get_whatsapp_messages() -> None:
    from unittest.mock import AsyncMock, MagicMock

    from src.whatsapp.models import WahaHistoryMessage

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

    res_get = await agent.execute_tool_call(
        func_name="get_note",
        args={"title": "WiFi"},
        default_sender="Gilang",
    )
    assert res_get["status"] == "success"
    assert res_get["note"]["content"] == "secret123"

    res_list = await agent.execute_tool_call(
        func_name="list_notes",
        args={},
        default_sender="Gilang",
    )
    assert res_list["status"] == "success"
    assert res_list["count"] >= 1

    res_append = await agent.execute_tool_call(
        func_name="append_to_note",
        args={"title": "WiFi", "text": "SSID: Home_5G"},
        default_sender="Gilang",
    )
    assert res_append["status"] == "success"
    assert "SSID: Home_5G" in res_append["note"]["content"]

    res_del = await agent.execute_tool_call(
        func_name="delete_note",
        args={"title": "WiFi"},
        default_sender="Gilang",
    )
    assert res_del["status"] == "success"


async def test_execute_tool_call_send_whatsapp_media() -> None:
    from unittest.mock import AsyncMock

    mock_client = AsyncMock()
    mock_client.send_media = AsyncMock(return_value="sent_media_id")

    res = await agent.execute_tool_call(
        func_name="send_whatsapp_media",
        args={
            "recipient": "Bunga",
            "media_url": "https://example.com/invoice.pdf",
            "caption": "Ini invoice kemarin",
        },
        default_sender="Gilang",
        client=mock_client,
    )
    assert res["status"] == "success"
    mock_client.send_media.assert_called_once()


async def test_execute_tool_call_web_search() -> None:
    from unittest.mock import AsyncMock, patch

    mock_res = {
        "status": "success",
        "query": "restoran sunda",
        "count": 1,
        "results": [{"title": "Restoran Sunda", "snippet": "Buka jam 10", "url": "https://example.com"}],
    }
    with patch("src.tools.search.search_web", new=AsyncMock(return_value=mock_res)):
        res = await agent.execute_tool_call(
            func_name="web_search",
            args={"query": "restoran sunda"},
            default_sender="Gilang",
        )
    assert res["status"] == "success"
    assert res["count"] == 1


async def test_execute_tool_call_delete_memory() -> None:
    from unittest.mock import patch

    with patch("src.memory.semantic.delete_memory", return_value={"status": "success", "deleted_count": 1}):
        res = await agent.execute_tool_call(
            func_name="delete_memory",
            args={"query": "kopi manis"},
            default_sender="Gilang",
        )
        assert res["status"] == "success"


def test_verify_action_fidelity_enforces_not_found_message() -> None:
    # When all mutation tools return not_found, verify the factual database outcome is enforced
    tools_failed = [
        {
            "name": "delete_memory",
            "result": {
                "status": "not_found",
                "message": "Tidak ditemukan memori yang cocok di database.",
            },
        }
    ]
    corrected = agent.verify_action_fidelity("Sip, sudah saya hapus.", tools_failed)
    assert "↳ `delete_memory`" not in corrected  # chips are opt-in (default off)
    assert "Tidak ditemukan memori yang cocok di database." in corrected


def test_verify_action_fidelity_passes_successful_turns() -> None:
    # When mutation tool succeeded, verify footnote is appended to the bottom
    tools_success = [
        {
            "name": "delete_memory",
            "result": {"status": "success", "deleted_count": 1},
        }
    ]
    verified = agent.verify_action_fidelity("Sip, sudah saya hapus ya.", tools_success)
    assert verified == "Sip, sudah saya hapus ya."  # chips opt-in: default off


def test_format_tool_chips_deduplicates_and_orders() -> None:
    from src.agent.guardrails import format_tool_chips

    assert format_tool_chips([]) is None
    chips = format_tool_chips([
        {"name": "search_vault_files"},
        {"name": "read_vault_file"},
        {"name": "search_vault_files"},  # duplicate
    ])
    assert chips == "↳ `search_vault_files`, `read_vault_file`"


async def test_execute_tool_call_send_status_update() -> None:
    import os
    from unittest.mock import AsyncMock, patch

    mock_client = AsyncMock()
    mock_client.send_message = AsyncMock(return_value="msg_status_123")
    mock_client.start_typing = AsyncMock()

    with patch.dict(os.environ, {"GILANG_PHONE": "628111111111"}):
        res = await agent.execute_tool_call(
            func_name="send_status_update",
            args={"text": "Siap Gilang, sedang saya kumpulkan 3 opsi venue di Bogor ya..."},
            default_sender="Gilang",
            client=mock_client,
        )
        assert res["status"] == "success"
        mock_client.send_message.assert_called_once_with(
            chat_id="628111111111@c.us",
            text="Siap Gilang, sedang saya kumpulkan 3 opsi venue di Bogor ya...",
        )
        mock_client.start_typing.assert_called_once_with(chat_id="628111111111@c.us")


async def test_execute_tool_call_send_status_update_empty_error() -> None:
    res = await agent.execute_tool_call(
        func_name="send_status_update",
        args={"text": ""},
        default_sender="Gilang",
    )
    assert res["status"] == "error"
    assert "tidak boleh kosong" in res["error"]


async def test_multistep_react_loop_with_status_update() -> None:
    import os
    from unittest.mock import AsyncMock, MagicMock, patch

    mock_client = AsyncMock()
    mock_client.get_messages = AsyncMock(return_value=[])
    mock_client.send_message = AsyncMock(return_value="msg_sent_ok")
    mock_client.start_typing = AsyncMock()

    # Mock Gemini HTTP cascading responses:
    # Step 1: Model calls send_status_update
    # Step 2: Model calls add_task
    # Step 3: Model emits final answer
    step1_response = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "functionCall": {
                                "name": "send_status_update",
                                "args": {"text": "Siap Gilang, sedang saya hitung pembagiannya ya..."},
                            }
                        }
                    ]
                }
            }
        ]
    }
    step2_response = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "functionCall": {
                                "name": "add_task",
                                "args": {
                                    "title": "Bayar tagihan listrik",
                                    "due": "Besok 12:00 WIB",
                                    "assignee": "Gilang",
                                },
                            }
                        }
                    ]
                }
            }
        ]
    }
    step3_response = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": "Tagihan listrik berhasil dihitung dan task *Bayar tagihan listrik* sudah dicatat besok pukul 12:00 WIB."
                        }
                    ]
                }
            }
        ]
    }

    mock_post = AsyncMock()
    # Return step1, step2, step3 responses
    mock_resp1 = MagicMock(status_code=200, json=lambda: step1_response)
    mock_resp2 = MagicMock(status_code=200, json=lambda: step2_response)
    mock_resp3 = MagicMock(status_code=200, json=lambda: step3_response)
    mock_post.side_effect = [mock_resp1, mock_resp2, mock_resp3]

    with patch("httpx.AsyncClient.post", mock_post):
        with patch("src.agent.cascade.GEMINI_KEYS", ["test_key"]):
            with patch.dict(
                os.environ,
                {
                    "GEMINI_KEY_1": "test_key",
                    "GILANG_PHONE": "628111111111",
                },
            ):
                final_reply = await agent.run_agentic_react_loop(
                    client=mock_client,
                    sender_name="Gilang",
                    chat_id="628111111111@c.us",
                    message_text="Tolong rekap tagihan listrik dan catat tasknya.",
                    max_steps=5,
                )

            # Assert intermediate status update was sent
            mock_client.send_message.assert_called_once_with(
                chat_id="628111111111@c.us",
                text="Siap Gilang, sedang saya hitung pembagiannya ya...",
            )
            # Assert task was created in memory
            tasks = memory.list_tasks(status="pending")
            assert len(tasks) == 1
            assert tasks[0]["title"] == "Bayar tagihan listrik"

            # Assert final response was correctly returned
            assert final_reply is not None
            assert "Tagihan listrik berhasil dihitung" in final_reply




