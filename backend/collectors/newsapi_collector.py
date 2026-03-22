"""Collect news articles from NewsAPI.org."""

from __future__ import annotations

import logging
from config import settings

log = logging.getLogger(__name__)

_client = None


def _get_client():
    global _client
    if _client is None:
        from newsapi import NewsApiClient
        _client = NewsApiClient(api_key=settings.newsapi_key)
    return _client


def collect(keyword: str, max_results: int = 5, days: int = 7) -> list[dict]:
    if not settings.newsapi_key:
        return []

    from datetime import datetime, timedelta

    client = _get_client()
    from_date = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")

    try:
        resp = client.get_everything(
            q=keyword,
            from_param=from_date,
            sort_by="publishedAt",
            page_size=min(max_results, 100),
            language=None,
        )
    except Exception as e:
        log.warning("error for '%s': %s", keyword, e)
        return []

    results: list[dict] = []
    for article in resp.get("articles", []):
        url = article.get("url", "")
        if not url or url == "https://removed.com":
            continue
        title = article.get("title") or ""
        description = article.get("description") or ""
        content = article.get("content") or description
        results.append({
            "title": title,
            "url": url,
            "content": content,
            "source": (article.get("source") or {}).get("name", ""),
            "published_date": article.get("publishedAt", ""),
        })

    return results[:max_results]
