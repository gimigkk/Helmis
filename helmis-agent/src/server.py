"""
server.py — MCP server and Webhook listener entry point for Helmis.

Responsibilities:
  - Exposes WhatsApp MCP tools over SSE on port 8765
  - Exposes Webhook receiver (/webhooks/waha, /health) on port 8644
  - Coordinates with WahaClient to receive and send WhatsApp messages
"""

import asyncio
import logging
import os
from threading import Thread

import uvicorn
from mcp.server.mcpserver import MCPServer

from .tools import register_all_tools
from .whatsapp.client import WahaClient
from .whatsapp.webhook import create_webhook_app

log = logging.getLogger("mcp-waha")


# ============================================================
# Server factory
# ============================================================


def create_server() -> tuple[MCPServer, WahaClient]:
    """
    Build and return a configured MCPServer instance and client.
    """
    client = WahaClient.from_env_sync()
    mcp = MCPServer(name="mcp-waha")
    register_all_tools(mcp, client)
    log.info("Registered tools: waha_send_message, waha_send_media, waha_get_messages")
    return mcp, client


# ============================================================
# Webhook server background runner
# ============================================================


def _run_webhook_server(client: WahaClient, webhook_port: int) -> None:
    """Run Starlette webhook & health app on webhook_port."""
    app = create_webhook_app(client)
    log.info(
        "Webhook & health server listening on 0.0.0.0:%d (routes: /health, /webhooks/waha)",
        webhook_port,
    )
    uvicorn.run(app, host="0.0.0.0", port=webhook_port, log_level="warning", access_log=False)


# ============================================================
# Entry point
# ============================================================


def main() -> None:
    """Start the MCP server and webhook listener."""
    mcp_port = int(os.environ.get("MCP_WAHA_PORT", "8765"))
    webhook_port = int(os.environ.get("AGENT_WEBHOOK_PORT") or os.environ.get("HERMES_WEBHOOK_PORT") or "8644")

    mcp, client = create_server()

    # Start webhook receiver on port 8644 in background thread
    webhook_thread = Thread(
        target=_run_webhook_server,
        args=(client, webhook_port),
        daemon=True,
        name="webhook-server",
    )
    webhook_thread.start()

    log.info("Starting mcp-waha SSE server on 0.0.0.0:%d/sse ...", mcp_port)
    asyncio.run(mcp.run_sse_async(host="0.0.0.0", port=mcp_port))


if __name__ == "__main__":
    main()
