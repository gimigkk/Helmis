"""
web.py — Tool Handlers for Live Web Search & Google Workspace / URL Reader.
"""

from typing import Any

from . import google_reader, search
from .registry import register_tool


@register_tool("web_search")
async def handle_web_search(args: dict[str, Any]) -> dict[str, Any]:
    query = str(args.get("query", "")).strip()
    if not query:
        return {"status": "error", "error": "Query pencarian tidak boleh kosong."}
    return await search.search_web(query=query)


@register_tool("read_url")
@register_tool("read_google_sheet")
@register_tool("read_google_doc")
@register_tool("read_google_slides")
@register_tool("read_web_page")
async def handle_read_url(args: dict[str, Any]) -> dict[str, Any]:
    """Read content from Google Docs, Google Sheets, Google Slides, Google Drive, or Web URLs."""
    url = str(args.get("url", "")).strip()
    if not url:
        return {"status": "error", "error": "Parameter url wajib diisi."}
    force_refresh = bool(args.get("force_refresh", False))
    force_ocr = bool(args.get("force_ocr", False))
    query = str(args.get("query", "")).strip()
    return await google_reader.read_url_content(
        url=url,
        force_refresh=force_refresh,
        query=query,
        force_ocr=force_ocr,
    )
