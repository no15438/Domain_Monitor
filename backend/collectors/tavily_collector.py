"""Collect articles from Tavily Search API (news mode, exclude encyclopedias)."""

from __future__ import annotations

import logging
from config import settings

log = logging.getLogger(__name__)

_client = None


def _get_client():
    global _client
    if _client is None:
        from tavily import TavilyClient
        _client = TavilyClient(api_key=settings.tavily_api_key)
    return _client


def collect(keyword: str, max_results: int = 5) -> list[dict]:
    if not settings.tavily_api_key:
        return []

    client = _get_client()
    exclude = [d.strip() for d in settings.tavily_exclude_domains.split(",") if d.strip()]

    try:
        response = client.search(
            query=keyword,
            max_results=max_results,
            topic="news",
            days=7,
            exclude_domains=exclude or None,
        )
    except Exception as e:
        log.warning("search error for '%s': %s", keyword, e)
        return []

    results: list[dict] = []
    for item in response.get("results", []):
        results.append({
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "content": item.get("content", ""),
            "source": item.get("source", ""),
            "published_date": item.get("published_date", ""),
        })
    return results
