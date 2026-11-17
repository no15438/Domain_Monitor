"""Bounded HTTP reads without changing process-wide socket timeouts."""
from urllib.request import Request, urlopen
import feedparser

MAX_FEED_BYTES = 4 * 1024 * 1024


def read_feed(url):
    if not url.startswith(("http://", "https://")):
        raise ValueError("RSS feeds must use HTTP or HTTPS.")
    request = Request(url, headers={"User-Agent": "DomainMonitor/1.0 (RSS reader)"})
    with urlopen(request, timeout=20) as response:
        body = response.read(MAX_FEED_BYTES + 1)
    if len(body) > MAX_FEED_BYTES:
        raise ValueError("RSS feed exceeds the size limit.")
    return feedparser.parse(body)
