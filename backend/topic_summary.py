"""Generate, persist, and vectorize AI narrative summaries for topics."""

import json
import uuid
from datetime import datetime, timezone

from database import (
    get_insight_summary,
    get_topic_insights,
    get_articles,
    get_topics,
    save_snapshot,
    get_latest_snapshot,
    get_trending_data,
    get_snapshot_history,
    get_kept_articles,
    update_topic_global_overview,
)
from vector_store import add_article
from llm_client import llm_chat_stream, llm_chat

SUMMARY_SYSTEM = """You are an expert industry analyst writing a concise executive briefing.

Your task: Given a set of recent articles and stats about a monitored topic, produce a clear, actionable overview.

Structure your response as:
## Key Developments
A 2-3 paragraph narrative of what happened recently — the most important events, why they matter, and how they connect.

## Notable Signals
- 3-5 bullet points highlighting specific noteworthy items (emerging trends, sentiment shifts, key players, risks or opportunities).

## Outlook
1-2 sentences on what to watch for next.

Rules:
- Be specific: cite article titles or sources when relevant.
- Prioritize significance over completeness — pick what matters most.
- Use clear, direct language. No filler.
- Write in the same language as the article titles (if titles are in Chinese, write in Chinese; if English, write in English).
- If there are very few or no articles, say so honestly and keep it short."""


def _collect_stats_metadata(topic_id: int, hours: int = 24) -> dict:
    """Gather all stats metadata into a serializable dict for snapshot storage."""
    summary = get_insight_summary(topic_id, hours)
    insight = get_topic_insights(topic_id, hours)
    trending = get_trending_data(topic_id, days=7)

    return {
        "hours": hours,
        "total_articles": summary["total_articles"],
        "important_count": summary["important_count"],
        "sentiment_distribution": summary["sentiment_distribution"],
        "source_distribution": summary["source_distribution"],
        "trend_delta": insight["trend_delta"],
        "top_tags": insight["top_tags"],
        "top_entities": trending["top_entities"],
        "avg_topic_relevance": trending["avg_topic_relevance"],
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }


def _get_topic_research_context(topic_id: int) -> dict:
    """Fetch topic name, brief, and config from database."""
    for t in get_topics():
        if t["id"] == topic_id:
            cfg = {}
            try:
                raw = t.get("research_config") or "{}"
                cfg = json.loads(raw) if isinstance(raw, str) else (raw or {})
            except Exception:
                pass
            return {
                "name": t.get("name", ""),
                "brief": t.get("research_brief") or "",
                "angles": cfg.get("angles", []),
                "entities": cfg.get("entities", []),
                "geographic_scope": cfg.get("geographic_scope", []),
                "sector_scope": cfg.get("sector_scope", []),
            }
    return {"name": "", "brief": "", "angles": [], "entities": [], "geographic_scope": [], "sector_scope": []}


def _build_context(topic_id: int, hours: int = 24) -> str | None:
    """Build LLM context from recent articles and research config. Returns None if no articles."""
    summary_data = get_insight_summary(topic_id, hours)
    topic_insight = get_topic_insights(topic_id, hours)
    articles = get_articles(30, 0, topic_id)
    rc = _get_topic_research_context(topic_id)

    if not articles:
        return None

    parts = []

    # Inject research context at the top
    if rc["brief"]:
        parts.append(f"[Research Direction] {rc['brief']}")
    if rc["angles"]:
        parts.append("[Research Angles]\n" + "\n".join(f"  • {a}" for a in rc["angles"]))
    if rc["entities"]:
        parts.append(f"[Key Entities to Watch] {', '.join(rc['entities'])}")
    if rc["geographic_scope"]:
        parts.append(f"[Geographic Scope] {', '.join(rc['geographic_scope'])}")
    if rc["sector_scope"]:
        parts.append(f"[Sector Scope] {', '.join(rc['sector_scope'])}")

    parts.append(
        f"\n[Stats for last {hours}h] "
        f"Total articles: {summary_data['total_articles']}, "
        f"Important: {summary_data['important_count']}, "
        f"Sentiment: {json.dumps(summary_data['sentiment_distribution'])}, "
        f"Sources: {json.dumps(summary_data['source_distribution'])}, "
        f"Trend delta: {topic_insight['trend_delta']:+d} vs previous period"
    )

    if topic_insight["top_tags"]:
        tags_str = ", ".join(
            f"{t['tag']}({t['count']})" for t in topic_insight["top_tags"][:10]
        )
        parts.append(f"[Top tags] {tags_str}")

    parts.append("\n[Recent articles — most recent first]")
    for i, art in enumerate(articles[:20], 1):
        parts.append(
            f"  [{i}] {art['title']} "
            f"(source: {art.get('source', '?')}, "
            f"importance: {art.get('importance', '?')}/10, "
            f"sentiment: {art.get('sentiment', '?')}, "
            f"event_size: {art.get('event_size', 1)}, "
            f"analysis: {(art.get('topic_analysis') or '')[:100]})\n"
            f"      {(art.get('summary') or '')[:200]}"
        )

    return "\n".join(parts)


def _persist_and_vectorize(topic_id: int, overview_text: str, stats: dict):
    """Save snapshot to database and index it in the vector store."""
    stats_json = json.dumps(stats, ensure_ascii=False)
    snapshot_id = save_snapshot(topic_id, overview_text, stats_json)

    topic_name = ""
    for t in get_topics():
        if t["id"] == topic_id:
            topic_name = t["name"]
            break

    date_str = stats.get("generated_utc", "")[:10]
    tags = [t["tag"] for t in stats.get("top_tags", [])[:5]]
    entities = [e["entity"] for e in stats.get("top_entities", [])[:5]]

    vector_text = (
        f"Domain analysis snapshot for '{topic_name}' on {date_str}. "
        f"Articles: {stats.get('total_articles', 0)}, "
        f"Important: {stats.get('important_count', 0)}, "
        f"Trend: {stats.get('trend_delta', 0):+d}. "
        f"Tags: {', '.join(tags)}. "
        f"Entities: {', '.join(entities)}.\n\n"
        f"{overview_text}"
    )

    vector_id = f"snapshot-{topic_id}-{snapshot_id}"
    add_article(
        vector_id,
        vector_text,
        {
            "doc_type": "snapshot",
            "topic_id": str(topic_id),
            "topic_name": topic_name,
            "snapshot_id": str(snapshot_id),
            "date": date_str,
        },
    )
    print(f"[summary] snapshot {snapshot_id} saved and vectorized for topic {topic_id}")


def generate_topic_summary(topic_id: int, hours: int = 24):
    """Yields status dicts and text chunks for a streaming AI topic summary.
    Persists snapshot and vectorizes it after generation completes."""

    yield {"status": "analyzing"}

    ctx = _build_context(topic_id, hours)
    if not ctx:
        msg = "No articles collected for this topic yet. Add keywords and fetch to start monitoring."
        yield msg
        return

    stats = _collect_stats_metadata(topic_id, hours)

    yield {"status": "generating"}

    messages = [
        {"role": "system", "content": SUMMARY_SYSTEM},
        {"role": "user", "content": ctx + "\n\nWrite the executive briefing based on the above data."},
    ]

    collected = []
    for chunk in llm_chat_stream(messages, temperature=0.4):
        collected.append(chunk)
        yield chunk

    overview_text = "".join(collected)
    _persist_and_vectorize(topic_id, overview_text, stats)


def generate_summary_sync(topic_id: int, hours: int = 24) -> str:
    """Non-streaming version for scheduled background generation."""
    ctx = _build_context(topic_id, hours)
    if not ctx:
        return ""

    from llm_client import llm_chat

    stats = _collect_stats_metadata(topic_id, hours)

    messages = [
        {"role": "system", "content": SUMMARY_SYSTEM},
        {"role": "user", "content": ctx + "\n\nWrite the executive briefing based on the above data."},
    ]
    result = llm_chat(messages, temperature=0.4)
    _persist_and_vectorize(topic_id, result, stats)
    return result


GLOBAL_OVERVIEW_SYSTEM = """You are a senior industry analyst writing a definitive 'Global Knowledge Base Overview' for a specific topic.

Your task: You will be provided with a historical sequence of AI-generated snapshots and a list of the most important articles for this topic. Use these to write a comprehensive, macro-level guide to this domain.

Structure your response as:
## 1. Domain Definition & Scope
What is this topic really about? Based on the articles, what are the core sub-fields or themes?

## 2. Historical Evolution (The Story So Far)
Synthesize the timeline of events. How has the sentiment, focus, or general narrative evolved across the provided snapshots? Mention key turning points.

## 3. Key Entities & Power Dynamics
Who are the major players (companies, people, products)? What are their roles and how do they interact or compete?

## 4. Persistent Themes & Long-Term Trends
What are the underlying currents that keep appearing in the high-importance articles?

Rules:
- This is NOT a daily news briefing; this is a permanent 'Wikipedia-style' macro analysis.
- Connect the dots between isolated events to show the bigger picture.
- Write in the same language as the provided titles/snapshots.
- If data is sparse, write a shorter but still macro-level overview."""


def _build_global_overview_context(topic_id: int) -> tuple[str | None, str | None]:
    """Returns (context_string, error_message_if_skip). If skip, context is None."""
    snapshots = get_snapshot_history(topic_id, limit=5)
    kept_articles = get_kept_articles(topic_id)[:20]
    rc = _get_topic_research_context(topic_id)

    if not snapshots and not kept_articles:
        return None, (
            "Not enough historical data or saved articles to generate a global overview yet. "
            "Let the system collect more data."
        )

    ctx_parts = []

    # Research context header
    if rc["brief"] or rc["angles"]:
        ctx_parts.append("=== Research Context ===")
        if rc["brief"]:
            ctx_parts.append(f"Research Direction: {rc['brief']}")
        if rc["angles"]:
            ctx_parts.append("Research Angles:\n" + "\n".join(f"  • {a}" for a in rc["angles"]))
        if rc["entities"]:
            ctx_parts.append(f"Key Entities: {', '.join(rc['entities'])}")
        if rc["geographic_scope"]:
            ctx_parts.append(f"Geographic Scope: {', '.join(rc['geographic_scope'])}")
        if rc["sector_scope"]:
            ctx_parts.append(f"Sector Scope: {', '.join(rc['sector_scope'])}")

    if snapshots:
        ctx_parts.append("=== Historical Snapshots (Recent to Old) ===")
        for s in snapshots:
            ctx_parts.append(f"Date: {s['created_at']}\nContent: {s['overview_content']}\n")

    if kept_articles:
        ctx_parts.append("=== Core Articles (Highest Importance / Saved) ===")
        for i, a in enumerate(kept_articles, 1):
            ctx_parts.append(
                f"[{i}] {a['title']} (Score: {a['importance']}, "
                f"sentiment: {a.get('sentiment','?')})\n"
                f"Analysis: {a.get('topic_analysis','')}\n"
                f"Summary: {a.get('summary', '')}"
            )

    return "\n\n".join(ctx_parts), None


def generate_global_overview_sync(topic_id: int) -> str:
    """Run global overview in a background thread: full LLM call + persist. Survives client disconnect."""
    ctx, err = _build_global_overview_context(topic_id)
    if err:
        update_topic_global_overview(topic_id, err)
        return err

    messages = [
        {"role": "system", "content": GLOBAL_OVERVIEW_SYSTEM},
        {"role": "user", "content": f"Context:\n{ctx}\n\nWrite the comprehensive global overview."},
    ]
    result = llm_chat(messages, temperature=0.5)
    update_topic_global_overview(topic_id, result)
    return result


def generate_global_overview(topic_id: int):
    """Legacy streaming generator (unused by API; kept for tests)."""
    yield {"status": "analyzing_history"}

    ctx, err = _build_global_overview_context(topic_id)
    if err:
        yield err
        update_topic_global_overview(topic_id, err)
        return

    yield {"status": "generating_global"}

    messages = [
        {"role": "system", "content": GLOBAL_OVERVIEW_SYSTEM},
        {"role": "user", "content": f"Context:\n{ctx}\n\nWrite the comprehensive global overview."},
    ]

    collected = []
    for chunk in llm_chat_stream(messages, temperature=0.5):
        collected.append(chunk)
        yield chunk

    final_text = "".join(collected)
    update_topic_global_overview(topic_id, final_text)


def refresh_all_summaries(hours: int = 24):
    """Regenerate summaries for all active topics. Called by scheduler."""
    topics = get_topics()
    for t in topics:
        if not t.get("is_active", 1):
            continue
        tid = t["id"]
        try:
            generate_summary_sync(tid, hours)
            print(f"[summary] refreshed topic {tid} ({t['name']})")
        except Exception as e:
            print(f"[summary] error for topic {tid}: {e}")
