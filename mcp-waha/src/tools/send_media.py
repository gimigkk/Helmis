"""
tools/send_media.py — MCP tool: waha_send_media

Registers the waha_send_media tool with an MCPServer instance.
Gives Hermes the ability to send a media file (image, PDF, audio, etc.)
to any WhatsApp chat or DM, with an optional caption.
"""

from mcp.server.mcpserver import MCPServer

from ..client import WahaClient
from ..models import SendMediaInput


def register_send_media(mcp: MCPServer, client: WahaClient) -> None:
    """
    Register the waha_send_media tool with the given MCPServer.

    Args:
        mcp: The MCPServer instance to register the tool on.
        client: The shared WahaClient used to make API calls.
    """

    @mcp.tool()
    async def waha_send_media(
        chat_id: str,
        media_url: str,
        caption: str | None = None,
        reply_to_message_id: str | None = None,
    ) -> str:
        """
        Send a media file (image, PDF, document, etc.) to a WhatsApp chat or DM.

        The media file must be accessible via a publicly reachable URL.
        Use this when Helmis needs to share an image, file, or document.

        Args:
            chat_id: WhatsApp chat ID to send to.
                     DM format:    "628xxxxxxxxxx@c.us"
                     Group format: "<group-id>@g.us"
            media_url: Publicly accessible URL of the media file to send.
            caption: Optional text caption displayed below the media.
            reply_to_message_id: Optional message ID to quote in the reply.

        Returns:
            Confirmation string with the sent message's ID.
        """
        params = SendMediaInput(
            chat_id=chat_id,
            media_url=media_url,
            caption=caption,
            reply_to_message_id=reply_to_message_id,
        )
        result = await client.send_media(
            chat_id=params.chat_id,
            media_url=params.media_url,
            caption=params.caption,
            reply_to_message_id=params.reply_to_message_id,
        )
        return f"Media sent successfully. ID: {result.message_id}"
