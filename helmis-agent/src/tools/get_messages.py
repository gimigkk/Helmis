"""
tools/get_messages.py — MCP tool: waha_get_messages

Registers the waha_get_messages tool with an MCPServer instance.
Gives Hermes the ability to fetch recent message history from any
WhatsApp chat or DM — useful for context recall and continuity.
"""

import json

from mcp.server.mcpserver import MCPServer

from ..client import WahaClient
from ..models import GetMessagesInput


def register_get_messages(mcp: MCPServer, client: WahaClient) -> None:
    """
    Register the waha_get_messages tool with the given MCPServer.

    Args:
        mcp: The MCPServer instance to register the tool on.
        client: The shared WahaClient used to make API calls.
    """

    @mcp.tool()
    async def waha_get_messages(
        chat_id: str,
        limit: int = 20,
    ) -> str:
        """
        Fetch recent message history from a WhatsApp chat or DM.

        Use this when you need context about what was recently discussed,
        or to recall something said earlier in a conversation.
        Returns messages as a JSON array, ordered oldest-first.

        Args:
            chat_id: WhatsApp chat ID to fetch history from.
                     DM format:    "628xxxxxxxxxx@c.us"
                     Group format: "<group-id>@g.us"
            limit: Number of recent messages to return (1–100, default 20).

        Returns:
            JSON-serialised array of message objects, each with:
            id, from, text, media_url, timestamp fields.
        """
        params = GetMessagesInput(chat_id=chat_id, limit=limit)
        messages = await client.get_messages(
            chat_id=params.chat_id,
            limit=params.limit,
        )

        if not messages:
            return "No messages found in this chat."

        serialised = [
            {
                "id": msg.message_id,
                "from": msg.sender_phone,
                "text": msg.text,
                "media_url": msg.media_url,
                "timestamp": msg.timestamp,
            }
            for msg in messages
        ]
        return json.dumps(serialised, ensure_ascii=False, indent=2)
