"""
search.py — Live web search provider for Helmis agent tools.

Supports DuckDuckGo (zero-dependency default) and Tavily (if TAVILY_API_KEY is configured).
Designed with strict timeouts, structured output, and zero external binary dependencies.
"""

import html
import logging
import os
import re
from typing import Any
from urllib.parse import quote_plus

import httpx

log = logging.getLogger("helmis-search")

TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "")


async def search_web(query: str, max_results: int = 5) -> dict[str, Any]:
    """
    Search the live web for a given query.
    Returns structured results with title, snippet, and url.
    """
    clean_query = query.strip()
    if not clean_query:
        return {"status": "error", "error": "Query pencarian tidak boleh kosong."}

    # 1. If Tavily API key is available, use official Tavily Search
    if TAVILY_API_KEY:
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                resp = await client.post(
                    "https://api.tavily.com/search",
                    json={
                        "api_key": TAVILY_API_KEY,
                        "query": clean_query,
                        "max_results": max_results,
                        "search_depth": "basic",
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    raw_results = data.get("results", [])
                    results = [
                        {
                            "title": r.get("title", ""),
                            "snippet": r.get("content", ""),
                            "url": r.get("url", ""),
                        }
                        for r in raw_results[:max_results]
                    ]
                    if results:
                        return {
                            "status": "success",
                            "query": clean_query,
                            "count": len(results),
                            "results": results,
                        }
        except Exception as e:
            log.warning("Tavily search failed for %r (%s), falling back to DuckDuckGo...", clean_query, e)

    # 2. Zero-dependency DuckDuckGo HTML Lite search
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
    }

    try:
        url = f"https://html.duckduckgo.com/html/?q={quote_plus(clean_query)}"
        async with httpx.AsyncClient(timeout=4.0, headers=headers, follow_redirects=True) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                html_text = resp.text
                results = []

                # Extract result blocks from DDG HTML
                snippets = re.findall(
                    r'<a[^>]*class="result__snippet"[^>]*>(.*?)</a>',
                    html_text,
                    re.DOTALL,
                )
                titles = re.findall(
                    r'<a[^>]*class="result__a"[^>]*>(.*?)</a>',
                    html_text,
                    re.DOTALL,
                )
                urls = re.findall(
                    r'<a[^>]*class="result__url"[^>]*>(.*?)</a>',
                    html_text,
                    re.DOTALL,
                )

                for i in range(min(len(titles), len(snippets), max_results)):
                    raw_title = re.sub(r"<[^>]+>", "", titles[i]).strip()
                    raw_snippet = re.sub(r"<[^>]+>", "", snippets[i]).strip()
                    raw_url = re.sub(r"<[^>]+>", "", urls[i]).strip() if i < len(urls) else ""
                    results.append({
                        "title": html.unescape(raw_title),
                        "snippet": html.unescape(raw_snippet),
                        "url": f"https://{raw_url}" if raw_url and not raw_url.startswith("http") else raw_url,
                    })

                if results:
                    return {
                        "status": "success",
                        "query": clean_query,
                        "count": len(results),
                        "results": results,
                    }
    except Exception as e:
        log.warning("DuckDuckGo HTML search error for %r: %s", clean_query, e)

    # 3. DuckDuckGo Instant Answer API fallback
    try:
        api_url = f"https://api.duckduckgo.com/?q={quote_plus(clean_query)}&format=json&no_html=1&skip_disambig=1"
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(api_url)
            if resp.status_code == 200:
                data = resp.json()
                abstract = data.get("AbstractText", "").strip()
                heading = data.get("Heading", "").strip()
                source_url = data.get("AbstractURL", "").strip()
                if abstract:
                    return {
                        "status": "success",
                        "query": clean_query,
                        "count": 1,
                        "results": [
                            {
                                "title": heading or clean_query,
                                "snippet": abstract,
                                "url": source_url,
                            }
                        ],
                    }
    except Exception as e:
        log.warning("DuckDuckGo Instant Answer search error for %r: %s", clean_query, e)

    return {
        "status": "not_found",
        "query": clean_query,
        "results": [],
        "message": f"Tidak ditemukan hasil pencarian di web untuk '{clean_query}'.",
    }
