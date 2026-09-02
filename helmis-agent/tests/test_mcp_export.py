"""Tests for MCP tool export: external tools delegate to the internal registry."""

from unittest.mock import AsyncMock

import pytest

from src.tools import register_all_tools
from src.whatsapp.client import WahaClient


class FakeMCP:
    """Minimal MCPServer stub capturing tool registrations."""

    def __init__(self) -> None:
        self.tools: dict[str, object] = {}

    def tool(self, name: str, description: str):  # noqa: ARG002
        def decorator(fn):
            self.tools[name] = fn
            return fn

        return decorator


@pytest.fixture
def mcp_tools() -> FakeMCP:
    fake = FakeMCP()
    register_all_tools(fake, AsyncMock(spec=WahaClient))
    return fake


@pytest.mark.asyncio
async def test_mcp_send_message_delegates_to_registry(mcp_tools: FakeMCP) -> None:
    result = await mcp_tools.tools["waha_send_message"](chat_id="123@c.us", text="halo")  # type: ignore[operator]
    assert result["status"] == "success"
    assert "berhasil dikirim" in result["message"]


@pytest.mark.asyncio
async def test_mcp_send_message_optional_quote_omitted(mcp_tools: FakeMCP) -> None:
    result = await mcp_tools.tools["waha_send_message"](chat_id="123@c.us", text="halo", reply_to_message_id=None)  # type: ignore[operator]
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_mcp_send_media_delegates_to_registry(mcp_tools: FakeMCP) -> None:
    result = await mcp_tools.tools["waha_send_media"](chat_id="123@c.us", media_url="https://example.com/x.png")  # type: ignore[operator]
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_mcp_get_messages_delegates_to_registry(mcp_tools: FakeMCP) -> None:
    result = await mcp_tools.tools["waha_get_messages"](chat_id="123@c.us", limit=5)  # type: ignore[operator]
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_mcp_invalid_args_rejected_by_schema_validation(mcp_tools: FakeMCP) -> None:
    """Empty text must fail through the same schema boundary as agent calls."""
    result = await mcp_tools.tools["waha_send_message"](chat_id="123@c.us", text="")  # type: ignore[operator]
    assert result["status"] == "error"
