"""
mcp_export.py — MCP Tool Registration for External MCP Clients.

External MCP tools delegate to the same TOOL_REGISTRY handlers the agent uses,
so authorization, schema validation, and logging apply identically. There is no
parallel namespace of raw-client wrappers.
"""

from typing import Any

from ..whatsapp.client import WahaClient
from .registry import execute_tool_call


def register_all_tools(mcp: Any, client: WahaClient) -> None:
    """Register MCP tools that delegate to the internal TOOL_REGISTRY."""
    internal_caller = "MCP External"

    @mcp.tool(  # type: ignore[untyped-decorator]
        name="waha_send_message",
        description="Send a text message to a WhatsApp chat or group.",
    )
    async def send_message(chat_id: str, text: str, reply_to_message_id: str | None = None) -> dict[str, Any]:
        args: dict[str, Any] = {"recipient": chat_id, "text": text}
        if reply_to_message_id:
            args["quote_message_id"] = reply_to_message_id
        return await execute_tool_call(
            func_name="send_whatsapp_message",
            args=args,
            default_sender=internal_caller,
            client=client,
        )

    @mcp.tool(  # type: ignore[untyped-decorator]
        name="waha_send_media",
        description="Send media (image, audio, document) to a WhatsApp chat or group.",
    )
    async def send_media(chat_id: str, media_url: str, caption: str | None = None) -> dict[str, Any]:
        args: dict[str, Any] = {"recipient": chat_id, "media_url": media_url}
        if caption:
            args["caption"] = caption
        return await execute_tool_call(
            func_name="send_whatsapp_media",
            args=args,
            default_sender=internal_caller,
            client=client,
        )

    @mcp.tool(  # type: ignore[untyped-decorator]
        name="waha_get_messages",
        description="Fetch recent messages from a WhatsApp chat history.",
    )
    async def get_messages(chat_id: str, limit: int = 20) -> dict[str, Any]:
        return await execute_tool_call(
            func_name="get_whatsapp_messages",
            args={"target": chat_id, "limit": limit},
            default_sender=internal_caller,
            client=client,
        )
