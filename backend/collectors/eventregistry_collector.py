"""Collect events from Event Registry (newsapi.ai).

Provides two capabilities:
  1. collect()    — fetch top articles per event (adds to recall pool)
  2. enrich_coverage() — query coverage counts for existing items

Graceful degradation: all functions return empty results when the API key
is missing or the service is unreachable.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from config import settings

log = logging.getLogger(__name__)

_er = None


def _get_er():
    global _er
    if _er is not None:
        return _er
    key = settings.event_registry_api_key
    if not key:
        return None
    try:
        from eventregistry import EventRegistry
        _er = EventRegistry(apiKey=key)
        return _er
    except Exception as e:
        log.error("init failed: %s", e)
        return None


def collect(keyword: str, max_events: int = 10, days: int = 7) -> list[dict]:
    """Search events by keyword. Returns one article per event."""
    er = _get_er()
    if er is None:
        return []

    try:
        from eventregistry import (
            QueryEventsIter, ReturnInfo, ArticleInfoFlags, EventInfoFlags,
        )

        date_start = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
        date_end = datetime.utcnow().strftime("%Y-%m-%d")

        q = QueryEventsIter(
            keywords=keyword,
            keywordsLoc="title,body",
            dateStart=date_start,
            dateEnd=date_end,
            minArticlesInEvent=3,
        )

        results: list[dict] = []
        for event in q.execQuery(
            er,
            sortBy="rel",
            maxItems=max_events,
            returnInfo=ReturnInfo(
                eventInfo=EventInfoFlags(
                    title=True,
                    summary=True,
                    articleCounts=True,
                    concepts=False,
                    categories=False,
                    location=False,
                    stories=False,
                ),
            ),
        ):
            title_obj = event.get("title", {})
            title = title_obj.get("eng") or next(iter(title_obj.values()), "")
            summary_obj = event.get("summary", {})
            summary = summary_obj.get("eng") or next(iter(summary_obj.values()), "")

            article_count = event.get("totalArticleCount", 0)
            if isinstance(event.get("articleCounts"), dict):
                article_count = sum(event["articleCounts"].values())

            event_uri = event.get("uri", "")
            event_url = f"https://eventregistry.org/event/{event_uri}" if event_uri else ""

            results.append({
                "title": title,
                "url": event_url,
                "content": summary,
                "source": "Event Registry",
                "published_date": event.get("eventDate", ""),
                "_er_event_uri": event_uri,
                "_er_article_count": article_count,
            })

        log.info("'%s': %d events", keyword, len(results))
        return results

    except Exception as e:
        log.warning("error for '%s': %s", keyword, e)
        return []


def enrich_coverage(items: list[dict], keywords: list[str]) -> dict[str, int]:
    """Query ER for article counts matching the given keywords.

    Returns a mapping of keyword -> total article count, which can be used
    to boost coverage scores for clusters containing those keywords.
    Falls back to empty dict if ER is unavailable.
    """
    er = _get_er()
    if er is None:
        return {}

    try:
        from eventregistry import QueryEventsIter
        date_start = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")
        counts: dict[str, int] = {}

        for kw in keywords[:5]:
            q = QueryEventsIter(keywords=kw, dateStart=date_start)
            total = 0
            for event in q.execQuery(er, sortBy="rel", maxItems=3):
                total += event.get("totalArticleCount", 0)
            counts[kw] = total

        return counts
    except Exception as e:
        log.warning("enrich_coverage error: %s", e)
        return {}
