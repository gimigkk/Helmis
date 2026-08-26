"""
test_search.py — Unit tests for live web search module.
"""

from unittest.mock import AsyncMock, patch

import pytest

from src.tools.search import search_web


@pytest.mark.asyncio
async def test_search_web_empty_query() -> None:
    res = await search_web("   ")
    assert res["status"] == "error"
    assert "tidak boleh kosong" in res["error"]


@pytest.mark.asyncio
async def test_search_web_duckduckgo_success() -> None:
    mock_html = """
    <html>
    <body>
        <a class="result__a" href="https://example.com/sushi">Restoran Sushi Senopati Terbaik</a>
        <a class="result__snippet" href="https://example.com/sushi">Sushi enak di Senopati buka sampai jam 22.00 WIB.</a>
        <a class="result__url" href="https://example.com/sushi">https://example.com/sushi</a>
    </body>
    </html>
    """

    mock_resp = AsyncMock()
    mock_resp.status_code = 200
    mock_resp.text = mock_html

    with patch("httpx.AsyncClient.get", return_value=mock_resp):
        res = await search_web("restoran sushi senopati", max_results=3)

    assert res["status"] == "success"
    assert res["count"] >= 1
    assert "Restoran Sushi Senopati" in res["results"][0]["title"]
    assert "Sushi enak di Senopati" in res["results"][0]["snippet"]


@pytest.mark.asyncio
async def test_search_web_handles_timeout_gracefully() -> None:
    with patch("httpx.AsyncClient.get", side_effect=Exception("Network Timeout")):
        res = await search_web("cuaca bandung besok")

    assert res["status"] == "not_found"
    assert "Tidak ditemukan hasil pencarian" in res["message"]
