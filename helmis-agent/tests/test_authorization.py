from unittest.mock import AsyncMock

import pytest

from src.tools.registry import execute_tool_call
from src.whatsapp.client import WahaClient


@pytest.mark.asyncio
async def test_unknown_principal_is_rejected_before_mutation() -> None:
    result = await execute_tool_call(
        "add_task",
        {"title": "Must not be stored", "due": "tomorrow"},
        default_sender="Unknown Caller",
    )

    assert result["status"] == "error"
    assert result["outcome"] == "unauthorized"


@pytest.mark.asyncio
async def test_unknown_principal_is_rejected_before_outbound_send() -> None:
    client = AsyncMock(spec=WahaClient)
    result = await execute_tool_call(
        "send_whatsapp_message",
        {"recipient": "Gilang", "text": "must not send"},
        default_sender="Unknown Caller",
        client=client,
    )

    assert result["outcome"] == "unauthorized"
    client.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_authorized_chat_scope_rejects_wrong_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HELMIS_AUTHORIZED_CHATS", "owner@c.us")
    result = await execute_tool_call(
        "list_tasks",
        {},
        default_sender="Gilang",
        chat_id="other@c.us",
    )

    assert result["outcome"] == "unauthorized"


@pytest.mark.asyncio
async def test_internal_scheduler_principal_is_allowed() -> None:
    result = await execute_tool_call(
        "list_tasks", {}, default_sender="Helmis-Proactive"
    )

    assert result["status"] == "success"
