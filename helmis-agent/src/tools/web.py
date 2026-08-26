"""
web.py — Tool Handlers for Live Web Search.
"""

from typing import Any

from ..whatsapp import search
from .registry import register_tool


@register_tool("web_search")
async def handle_web_search(args: dict[str, Any]) -> dict[str, Any]:
    query = str(args.get("query", "")).strip()
    if not query:
        return {"status": "error", "error": "Query pencarian tidak boleh kosong."}
    return await search.search_web(query=query)
