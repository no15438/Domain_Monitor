"""Collect articles from Google News RSS — free, no API key, keyword-based."""

from __future__ import annotations

import logging
import feedparser
from html import unescape
from urllib.parse import quote_plus
import re

log = logging.getLogger(__name__)

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    return unescape(_TAG_RE.sub("", text)).strip()


def collect(keyword: str, max_results: int = 20, lang: str = "en") -> list[dict]:
    url = (
        f"https://news.google.com/rss/search"
        f"?q={quote_plus(keyword)}+when:7d&hl={lang}"
    )
    try:
        feed = feedparser.parse(url)
    except Exception as e:
        log.warning("parse error for '%s': %s", keyword, e)
        return []

    results: list[dict] = []
    for entry in feed.entries[:max_results]:
        title = entry.get("title", "")
        link = entry.get("link", "")
        if not link:
            continue

        summary = _strip_html(entry.get("summary", ""))
        source_name = ""
        if " - " in title:
            source_name = title.rsplit(" - ", 1)[-1].strip()

        published = entry.get("published", "")

        results.append({
            "title": title,
            "url": link,
            "content": summary,
            "source": source_name,
            "published_date": published,
        })

    return results
