"""Collect articles from RSS / Atom feeds."""

from __future__ import annotations

import logging
import feedparser
from html import unescape
import re

log = logging.getLogger(__name__)

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    return unescape(_TAG_RE.sub("", text)).strip()


def collect_feed(feed_url: str, max_items: int = 20) -> list[dict]:
    try:
        feed = feedparser.parse(feed_url)
    except Exception as e:
        log.warning("parse error for '%s': %s", feed_url, e)
        return []

    results: list[dict] = []
    for entry in feed.entries[:max_items]:
        title = entry.get("title", "")
        link = entry.get("link", "")
        if not link:
            continue

        summary = _strip_html(entry.get("summary", ""))
        content_detail = entry.get("content", [{}])
        content_text = ""
        if content_detail and isinstance(content_detail, list):
            content_text = _strip_html(content_detail[0].get("value", ""))

        full_text = content_text or summary

        published = entry.get("published", entry.get("updated", ""))

        source = feed.feed.get("title", "")

        results.append({
            "title": title,
            "url": link,
            "content": full_text,
            "source": source,
            "published_date": published,
        })

    return results


def collect_multiple(feed_urls: list[str], max_per_feed: int = 20) -> list[dict]:
    all_items: list[dict] = []
    for url in feed_urls:
        url = url.strip()
        if not url:
            continue
        all_items.extend(collect_feed(url, max_per_feed))
    return all_items
