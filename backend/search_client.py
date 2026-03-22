"""Tavily search client — used ONLY by the chatbot for real-time web search.
Pipeline data collection uses dedicated collectors instead."""

from tavily import TavilyClient
from config import settings

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = TavilyClient(api_key=settings.tavily_api_key)
    return _client


def search(query: str, max_results: int = 5) -> list[dict]:
    client = _get_client()
    exclude = [d.strip() for d in settings.tavily_exclude_domains.split(",") if d.strip()]

    response = client.search(
        query=query,
        max_results=max_results,
        exclude_domains=exclude or None,
    )
    results = []
    for item in response.get("results", []):
        results.append(
            {
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "content": item.get("content", ""),
                "source": item.get("source", ""),
                "published_date": item.get("published_date", ""),
            }
        )
    return results
