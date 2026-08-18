"""
tools/__init__.py — Tool registration for mcp-waha.

Exports a single register_all_tools() function that the server calls
once at startup to attach every tool to the MCPServer instance.

To add a new tool:
  1. Create tools/your_tool.py following the pattern of existing tools
  2. Import its register function here
  3. Call it inside register_all_tools()
"""

from mcp.server.mcpserver import MCPServer

from ..client import WahaClient
from .get_messages import register_get_messages
from .send_media import register_send_media
from .send_message import register_send_message

__all__ = ["register_all_tools"]


def register_all_tools(mcp: MCPServer, client: WahaClient) -> None:
    """
    Register all mcp-waha tools with the MCPServer.

    Args:
        mcp: The MCPServer instance.
        client: The shared WahaClient instance (passed to each tool via closure).
    """
    register_send_message(mcp, client)
    register_send_media(mcp, client)
    register_get_messages(mcp, client)
