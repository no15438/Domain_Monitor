import json
from llm_client import llm_chat, llm_chat_stream
from vector_store import search_articles
from search_client import search as web_search
from database import get_latest_snapshot, get_topics, get_topic_global_overview

SYSTEM_PROMPT = """You are an intelligent industry monitoring assistant.
You help users understand industry trends, news, and events based on a curated knowledge base and live web searches.

Rules:
1. Use provided context to give accurate, up-to-date answers.
2. Cite sources (title + URL) when possible.
3. If the context is insufficient, clearly say so.
4. Be concise but thorough.
5. ALWAYS respond in the same language as the user's question."""

SNAPSHOT_PREAMBLE = """Below is the latest domain analysis snapshot for the current topic "{topic_name}" (generated {date}).
Use this as background knowledge when answering questions about this domain.

--- Domain Overview ---
{overview}
--- End Overview ---
"""

GLOBAL_OVERVIEW_PREAMBLE = """
--- Macro Domain Analysis (Long-term Overview) ---
{overview}
--- End Macro Analysis ---
"""


def _build_topic_context(topic_id: int) -> str | None:
    """Build a preamble string from the latest snapshot for the active topic."""
    snapshot = get_latest_snapshot(topic_id)
    if not snapshot or not snapshot.get("content"):
        return None

    topic_name = ""
    for t in get_topics():
        if t["id"] == topic_id:
            topic_name = t["name"]
            break

    stats = {}
    try:
        stats = json.loads(snapshot.get("stats_metadata") or "{}")
    except (json.JSONDecodeError, TypeError):
        pass

    entities_str = ""
    top_entities = stats.get("top_entities", [])
    if top_entities:
        entities_str = "\nKey entities recently tracked: " + ", ".join(
            e["entity"] for e in top_entities[:8]
        )

    result = SNAPSHOT_PREAMBLE.format(
        topic_name=topic_name,
        date=snapshot.get("generated_at", "unknown"),
        overview=snapshot["content"],
    ) + entities_str

    # Append Global Overview (long-term macro analysis) if available
    global_overview = get_topic_global_overview(topic_id)
    if global_overview and global_overview.strip():
        result += GLOBAL_OVERVIEW_PREAMBLE.format(overview=global_overview)

    return result


def _hybrid_search(query: str, topic_id: int | None, n_results: int = 8) -> tuple[list[dict], list[dict]]:
    """Search vector store for both articles and snapshots.
    Returns (articles, snapshots) as two separate lists."""
    where_filter = {"topic_id": str(topic_id)} if topic_id is not None else None

    all_results = search_articles(query, n_results=n_results, where_filter=where_filter)

    articles = []
    snapshots = []
    for r in all_results:
        doc_type = r.get("metadata", {}).get("doc_type", "article")
        if doc_type == "snapshot":
            snapshots.append(r)
        else:
            articles.append(r)

    return articles, snapshots


def _extract_title_from_ctx(article_context: str) -> str:
    """Extract the Title line from a formatted article_context string."""
    for line in article_context.splitlines():
        if line.startswith("Title:"):
            return line[6:].strip()
    return ""


def chat_stream_with_status(
    message: str,
    article_context: str | None = None,
    topic_id: int | None = None,
    history: list[dict] | None = None,
):
    """Yields status dicts and text chunks interleaved."""
    parts: list[str] = []

    if topic_id is not None:
        topic_ctx = _build_topic_context(topic_id)
        if topic_ctx:
            parts.append(topic_ctx)

    if article_context:
        parts.append(f"[Current article context]\n{article_context}")

    yield {"status": "searching_knowledge_base"}

    # Enrich vector search query with article title when available
    search_query = message
    if article_context:
        title = _extract_title_from_ctx(article_context)
        if title:
            search_query = f"{title} {message}"

    articles, snapshots = _hybrid_search(search_query, topic_id)

    if articles:
        parts.append("[Related articles from knowledge base]")
        for i, r in enumerate(articles, 1):
            meta = r.get("metadata", {})
            parts.append(
                f"  [{i}] {meta.get('title', 'Untitled')} "
                f"(source: {meta.get('source', '?')}, url: {meta.get('url', '')})\n"
                f"  {r['document'][:500]}"
            )

    if snapshots:
        parts.append("[Historical domain analysis snapshots]")
        for i, r in enumerate(snapshots, 1):
            meta = r.get("metadata", {})
            parts.append(
                f"  [Snapshot-{i}] {meta.get('topic_name', '?')} ({meta.get('date', '?')})\n"
                f"  {r['document'][:600]}"
            )

    need_web = (not articles and not snapshots) or (
        articles and articles[0].get("distance", 1) > 0.5
    )
    if need_web:
        yield {"status": "searching_web"}
        try:
            web = web_search(message, max_results=3)
            if web:
                parts.append("[Live web search results]")
                for i, r in enumerate(web, 1):
                    parts.append(
                        f"  [Web-{i}] {r['title']} ({r['url']})\n  {r['content'][:300]}"
                    )
        except Exception:
            pass

    yield {"status": "generating"}

    ctx = "\n\n".join(parts)

    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    # Inject prior conversation turns (max 20 messages to avoid token overflow)
    if history:
        # Only keep roles the LLM understands; strip any empty assistant placeholders
        valid_history = [
            h for h in history[-20:]
            if h.get("role") in ("user", "assistant") and h.get("content", "").strip()
        ]
        messages.extend(valid_history)
    messages.append({"role": "user", "content": f"Context:\n{ctx}\n\nQuestion: {message}"})
    yield from llm_chat_stream(messages, temperature=0.5)
