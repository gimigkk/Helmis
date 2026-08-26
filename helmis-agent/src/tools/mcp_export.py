"""
mcp_export.py — FastMCP / MCPServer Tool Registration for External MCP Clients.
"""

from typing import Any

from ..whatsapp.client import WahaClient
from ..models import (
    GetMessagesInput,
    SendMediaInput,
    SendMessageInput,
    WahaMessageResponse,
)


def register_all_tools(mcp: Any, client: WahaClient) -> None:
    """Register WAHA MCP tools with an MCPServer instance."""

    @mcp.tool(  # type: ignore[untyped-decorator]
        name="waha_send_message",
        description="Send a text message to a WhatsApp chat or group.",
    )
    async def send_message(params: SendMessageInput) -> WahaMessageResponse:
        return await client.send_message(
            chat_id=params.chat_id,
            text=params.text,
            reply_to_message_id=params.reply_to_message_id,
        )

    @mcp.tool(  # type: ignore[untyped-decorator]
        name="waha_send_media",
        description="Send media (image, audio, document) to a WhatsApp chat or group.",
    )
    async def send_media(params: SendMediaInput) -> WahaMessageResponse:
        return await client.send_media(
            chat_id=params.chat_id,
            media_url=params.media_url,
            caption=params.caption,
        )

    @mcp.tool(  # type: ignore[untyped-decorator]
        name="waha_get_messages",
        description="Fetch recent messages from a WhatsApp chat history.",
    )
    async def get_messages(params: GetMessagesInput) -> list[dict[str, Any]]:
        msgs = await client.get_messages(chat_id=params.chat_id, limit=params.limit)
        return [m.model_dump() for m in msgs]
