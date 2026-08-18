"""
tools/send_message.py — MCP tool: waha_send_message

Registers the waha_send_message tool with an MCPServer instance.
Gives Hermes (or any MCP client) the ability to send a plain text
WhatsApp message to any chat ID — group chat or individual DM.
"""

from mcp.server.mcpserver import MCPServer

from ..client import WahaClient
from ..models import SendMessageInput


def register_send_message(mcp: MCPServer, client: WahaClient) -> None:
    """
    Register the waha_send_message tool with the given MCPServer.

    The tool is defined as an inner function decorated with @mcp.tool()
    so that it captures the shared client instance via closure — no global
    state, no singletons.

    Args:
        mcp: The MCPServer instance to register the tool on.
        client: The shared WahaClient used to make API calls.
    """

    @mcp.tool()
    async def waha_send_message(
        chat_id: str,
        text: str,
        reply_to_message_id: str | None = None,
    ) -> str:
        """
        Send a plain text WhatsApp message to a chat or DM.

        Use this to reply to users or send proactive messages as Helmis.
        WhatsApp does not render markdown — send plain text only.

        Args:
            chat_id: WhatsApp chat ID to send to.
                     DM format:    "628xxxxxxxxxx@c.us"
                     Group format: "<group-id>@g.us"
            text: The message body to send.
            reply_to_message_id: Optional message ID to quote in the reply.

        Returns:
            Confirmation string with the sent message's ID.
        """
        params = SendMessageInput(
            chat_id=chat_id,
            text=text,
            reply_to_message_id=reply_to_message_id,
        )
        result = await client.send_message(
            chat_id=params.chat_id,
            text=params.text,
            reply_to_message_id=params.reply_to_message_id,
        )
        return f"Message sent successfully. ID: {result.message_id}"
