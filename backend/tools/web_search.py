"""Optional Tavily-backed web search (salary lookups)."""

from __future__ import annotations

import logging
import os

log = logging.getLogger("assistant.web_search")


def tavily_search(query: str, max_results: int = 5) -> list[dict]:
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        log.info("TAVILY_API_KEY not set — skipping web search")
        return []
    try:
        from tavily import TavilyClient
    except ImportError:
        log.warning("tavily-python not installed")
        return []
    client = TavilyClient(api_key=api_key)
    resp = client.search(query=query, max_results=max_results, search_depth="basic")
    return resp.get("results", [])
