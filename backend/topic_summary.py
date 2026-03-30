"""Generate, persist, and vectorize AI narrative summaries for topics."""

import json
import uuid
from datetime import datetime, timezone, timedelta

from database import (
    get_articles,
    get_current_claims,
    get_events_v2,
    get_insight_summary,
    get_topic_insights,
    get_claims_v2,
    get_claim_evolution,
    get_snapshot_deltas,
    get_snapshot_events,
    get_snapshot_claims,
    get_topics,
    get_trending_data,
    get_synthesis_artifact,
    get_temporal_snapshots,
    list_evidence_sets,
    replace_synthesis_artifact,
    save_snapshot_delta,
    save_temporal_snapshot,
)
from vector_store import add_artifact_document, add_snapshot_document
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

## Timeliness Assessment
Classify key conclusions into: Fresh / Possibly stale / Needs verification.
For each non-fresh item, briefly state why (timestamp gap, conflicting newer signal, weak recency evidence) and what to verify next.

Rules:
- Be specific: cite article titles or sources when relevant.
- Prioritize significance over completeness — pick what matters most.
- Use clear, direct language. No filler.
- Write in the same language as the article titles (if titles are in Chinese, write in Chinese; if English, write in English).
- If there are very few or no articles, say so honestly and keep it short.
- Perform an internal freshness reasoning pass before writing (recency, consistency, corroboration), but do NOT reveal hidden reasoning steps.
- If information appears old or uncertain, lower confidence in wording and place it in Timeliness Assessment."""


def _coerce_dt(raw: str | None) -> datetime | None:
    if not raw:
        return None
    value = str(raw).strip()
    if not value:
        return None
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                parsed = datetime.strptime(value, fmt)
                break
            except ValueError:
                parsed = None
        if parsed is None:
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


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


def _build_context(topic_id: int, hours: int = 24) -> tuple[str | None, list[dict], list[dict]]:
    """Build LLM context from the lineage model only."""
    summary_data = get_insight_summary(topic_id, hours)
    topic_insight = get_topic_insights(topic_id, hours)
    trending = get_trending_data(topic_id, days=7)
    rc = _get_topic_research_context(topic_id)
    events = get_events_v2(topic_id, status=None, limit=20)
    claims = get_current_claims(topic_id, limit=20)

    parts = []
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
        tags_str = ", ".join(f"{t['tag']}({t['count']})" for t in topic_insight["top_tags"][:10])
        parts.append(f"[Top tags] {tags_str}")
    if trending["top_entities"]:
        ent_str = ", ".join(f"{e['entity']}({e['count']})" for e in trending["top_entities"][:10])
        parts.append(f"[Top entities] {ent_str}")

    if events or claims:
        if events:
            parts.append("\n[Active events]")
            for i, event in enumerate(events[:15], 1):
                parts.append(
                    f"  [Event-{i}] {event['title']} "
                    f"(status: {event.get('status', '?')}, "
                    f"lifecycle: {event.get('event_status', '?')}, "
                    f"first_seen: {event.get('first_seen_at', '')}, "
                    f"last_seen: {event.get('last_seen_at', '')}, "
                    f"created_at: {event.get('created_at', '')}, "
                    f"stability: {round(event.get('stability_score', 0), 2)})\n"
                    f"      {event.get('summary', '')[:220]}"
                )
        if claims:
            parts.append("\n[Active claims]")
            for i, claim in enumerate(claims[:15], 1):
                parts.append(
                    f"  [Claim-{i}] {claim['statement']}\n"
                    f"      lifecycle: {claim.get('status', '?')} · "
                    f"kind: {claim.get('claim_kind', claim.get('claim_type', '?'))} · "
                    f"staleness: {claim.get('staleness_status', '?')} · "
                    f"last_refreshed: {claim.get('last_refreshed_at', claim.get('last_validated_at', ''))} · "
                    f"updated_at: {claim.get('updated_at', '')}\n"
                    f"      {claim.get('summary', '')[:220]}"
                )
        return "\n".join(parts), events, claims

    articles = get_articles(
        limit=35, offset=0, topic_id=topic_id, sort="relevance", status="active"
    )
    if summary_data.get("total_articles", 0) > 0 or articles:
        parts.append(
            "\n[Recent articles — no structured events/claims in DB yet; use these headlines]"
        )
        for i, art in enumerate(articles[:30], 1):
            parts.append(
                f"  [{i}] {art.get('title', '')}\n"
                f"      Source: {art.get('source', '')} · "
                f"{str(art.get('summary', '') or '')[:280]}"
            )
        return "\n".join(parts), events, claims

    return None, [], []


def _build_delta_summary(previous_snapshot_id: int | None, snapshot_id: int, topic_id: int) -> dict:
    current_events = get_snapshot_events(snapshot_id)
    current_claims = get_snapshot_claims(snapshot_id)
    prev_events = get_snapshot_events(previous_snapshot_id) if previous_snapshot_id else []
    prev_claims = get_snapshot_claims(previous_snapshot_id) if previous_snapshot_id else []
    recent_evolution = get_claim_evolution(topic_id, limit=200)

    current_event_ids = {e["id"] for e in current_events}
    prev_event_ids = {e["id"] for e in prev_events}
    current_claim_ids = {c["id"] for c in current_claims}
    prev_claim_ids = {c["id"] for c in prev_claims}

    new_event_ids = sorted(current_event_ids - prev_event_ids)
    resolved_event_ids = sorted(prev_event_ids - current_event_ids)
    strengthened_claim_ids = sorted(current_claim_ids - prev_claim_ids)
    weakened_claim_ids = sorted(prev_claim_ids - current_claim_ids)
    superseded_claim_ids = {
        c["id"] for c in current_claims if c.get("status") in {"superseded", "obsolete"}
    }
    current_time = max(
        [_coerce_dt((current_events[0] if current_events else {}).get("last_seen_at")), _coerce_dt((current_claims[0] if current_claims else {}).get("last_refreshed_at"))],
        key=lambda dt: dt or datetime.min.replace(tzinfo=timezone.utc),
    )
    previous_time = max(
        [_coerce_dt((prev_events[0] if prev_events else {}).get("last_seen_at")), _coerce_dt((prev_claims[0] if prev_claims else {}).get("last_refreshed_at"))],
        key=lambda dt: dt or datetime.min.replace(tzinfo=timezone.utc),
    )
    for row in recent_evolution:
        relation = row.get("relation_type")
        created_at = _coerce_dt(row.get("created_at"))
        current_claim_id = row.get("claim_id")
        previous_claim_id = row.get("previous_claim_id")
        relates_to_transition = (
            previous_claim_id in prev_claim_ids
            and current_claim_id in current_claim_ids
        )
        if relates_to_transition:
            if relation == "strengthened" and current_claim_id:
                strengthened_claim_ids.append(current_claim_id)
            if relation in {"weakened", "withdrawn"} and current_claim_id:
                weakened_claim_ids.append(current_claim_id)
            if relation == "supersedes" and previous_claim_id:
                superseded_claim_ids.add(previous_claim_id)
            continue
        if previous_time and created_at and created_at <= previous_time:
            continue
        if current_time and created_at and created_at > current_time + timedelta(days=1):
            continue
        if relation == "strengthened" and current_claim_id:
            strengthened_claim_ids.append(current_claim_id)
        if relation in {"weakened", "withdrawn"} and current_claim_id:
            weakened_claim_ids.append(current_claim_id)
        if relation == "supersedes" and previous_claim_id:
            superseded_claim_ids.add(previous_claim_id)
    strengthened_claim_ids = sorted(set(strengthened_claim_ids))
    weakened_claim_ids = sorted(set(weakened_claim_ids))
    superseded_claim_ids = sorted(superseded_claim_ids)

    summary = (
        f"Topic {topic_id} changed between snapshots: "
        f"{len(new_event_ids)} new events, {len(resolved_event_ids)} resolved events, "
        f"{len(strengthened_claim_ids)} strengthened claims, {len(weakened_claim_ids)} weakened claims."
    )
    return {
        "change_summary": summary,
        "new_event_ids": new_event_ids,
        "resolved_event_ids": resolved_event_ids,
        "strengthened_claim_ids": strengthened_claim_ids,
        "weakened_claim_ids": weakened_claim_ids,
        "superseded_claim_ids": superseded_claim_ids,
    }


def _persist_and_vectorize(topic_id: int, overview_text: str, stats: dict, events: list[dict], claims: list[dict]):
    """Save lineage-aware snapshots and snapshot delta."""
    stats_json = json.dumps(stats, ensure_ascii=False)

    topic_name = ""
    for t in get_topics():
        if t["id"] == topic_id:
            topic_name = t["name"]
            break

    date_str = stats.get("generated_utc", "")[:10]
    tags = [t["tag"] for t in stats.get("top_tags", [])[:5]]
    entities = [e["entity"] for e in stats.get("top_entities", [])[:5]]
    event_ids = [e["id"] for e in events]
    claim_ids = [c["id"] for c in claims]

    snapshot_id = save_temporal_snapshot(
        topic_id=topic_id,
        summary_text=overview_text,
        stats_metadata=stats_json,
        window_type="daily",
        window_start=None,
        window_end=stats.get("generated_utc"),
        snapshot_status="final",
        event_ids=event_ids,
        claim_ids=claim_ids,
    )

    vector_text = (
        f"Domain analysis snapshot for '{topic_name}' on {date_str}. "
        f"Articles: {stats.get('total_articles', 0)}, "
        f"Important: {stats.get('important_count', 0)}, "
        f"Trend: {stats.get('trend_delta', 0):+d}. "
        f"Tags: {', '.join(tags)}. "
        f"Entities: {', '.join(entities)}.\n\n"
        f"{overview_text}"
    )

    add_snapshot_document(
        f"temporal-snapshot-{topic_id}-{snapshot_id}",
        vector_text,
        {
            "topic_id": str(topic_id),
            "topic_name": topic_name,
            "snapshot_id": str(snapshot_id),
            "window_type": "daily",
            "window_end": stats.get("generated_utc", ""),
            "status": "final",
            "date": date_str,
        },
    )

    previous_snapshots = get_temporal_snapshots(topic_id, window_type="daily", limit=2)
    if len(previous_snapshots) >= 2 and previous_snapshots[0]["id"] == snapshot_id:
        previous_snapshot_id = previous_snapshots[1]["id"]
    else:
        previous_snapshot_id = previous_snapshots[0]["id"] if previous_snapshots else None
    delta = _build_delta_summary(previous_snapshot_id, snapshot_id, topic_id)
    save_snapshot_delta(
        topic_id=topic_id,
        from_snapshot_id=previous_snapshot_id,
        to_snapshot_id=snapshot_id,
        change_summary=delta["change_summary"],
        new_event_ids=delta["new_event_ids"],
        resolved_event_ids=delta["resolved_event_ids"],
        strengthened_claim_ids=delta["strengthened_claim_ids"],
        weakened_claim_ids=delta["weakened_claim_ids"],
        superseded_claim_ids=delta["superseded_claim_ids"],
        metadata={"window_type": "daily"},
    )
    print(f"[summary] snapshot {snapshot_id} saved and vectorized for topic {topic_id}")


def generate_topic_summary(topic_id: int, hours: int = 24):
    """Yields status dicts and text chunks for a streaming AI topic summary.
    Persists snapshot and vectorizes it after generation completes."""

    yield {"status": "analyzing"}

    ctx, events, claims = _build_context(topic_id, hours)
    if not ctx:
        msg = "No lineage data available for this topic yet. Add keywords and run fetch to generate events and claims."
        yield msg
        return

    stats = _collect_stats_metadata(topic_id, hours)

    yield {"status": "generating"}

    messages = [
        {"role": "system", "content": SUMMARY_SYSTEM},
        {
            "role": "user",
            "content": (
                f"Current UTC time: {datetime.now(timezone.utc).isoformat()}\n\n"
                f"Context:\n{ctx}\n\n"
                "Write the executive briefing based on the above data."
            ),
        },
    ]

    collected = []
    for chunk in llm_chat_stream(messages, temperature=0.4):
        collected.append(chunk)
        yield chunk

    overview_text = "".join(collected)
    _persist_and_vectorize(topic_id, overview_text, stats, events, claims)


def generate_summary_sync(topic_id: int, hours: int = 24) -> str:
    """Non-streaming version for scheduled background generation."""
    ctx, events, claims = _build_context(topic_id, hours)
    if not ctx:
        return ""

    from llm_client import llm_chat

    stats = _collect_stats_metadata(topic_id, hours)

    messages = [
        {"role": "system", "content": SUMMARY_SYSTEM},
        {
            "role": "user",
            "content": (
                f"Current UTC time: {datetime.now(timezone.utc).isoformat()}\n\n"
                f"Context:\n{ctx}\n\n"
                "Write the executive briefing based on the above data."
            ),
        },
    ]
    result = llm_chat(messages, temperature=0.4)
    _persist_and_vectorize(topic_id, result, stats, events, claims)
    return result


GLOBAL_OVERVIEW_SYSTEM = """You are a senior industry analyst writing a definitive 'Global Knowledge Base Overview' for a specific topic.

Your task: You will be provided with historical snapshots, snapshot deltas, active events, active claims, and evidence sets for a topic. Use these to write a comprehensive, macro-level guide to this domain.

Structure your response as:
## 1. Domain Definition & Scope
What is this topic really about? Based on the articles, what are the core sub-fields or themes?

## 2. Historical Evolution (The Story So Far)
Synthesize the timeline of events. How has the sentiment, focus, or general narrative evolved across the provided snapshots? Mention key turning points.

## 3. Key Entities & Power Dynamics
Who are the major players (companies, people, products)? What are their roles and how do they interact or compete?

## 4. Persistent Themes & Long-Term Trends
What are the underlying currents that keep appearing in the high-importance articles?

## 5. Timeliness Assessment & Verification Gaps
Identify which key narratives are Fresh / Possibly stale / Needs verification, and list what should be re-validated next.

Rules:
- This is NOT a daily news briefing; this is a permanent 'Wikipedia-style' macro analysis.
- Connect the dots between isolated events to show the bigger picture.
- Write in the same language as the provided titles/snapshots.
- If data is sparse, write a shorter but still macro-level overview.
- Perform an internal freshness reasoning pass before writing (recency, consistency, corroboration), but do NOT reveal hidden reasoning chains.
- Prefer newer snapshots/events/claims when older evidence conflicts; explicitly down-rank stale evidence in section 5."""


def _build_global_overview_context(topic_id: int) -> tuple[str | None, str | None]:
    """Returns (context_string, error_message_if_skip). If skip, context is None."""
    snapshots = get_temporal_snapshots(topic_id, window_type="daily", limit=5)
    deltas = get_snapshot_deltas(topic_id, limit=4)
    events = get_events_v2(topic_id, status=None, limit=20)
    claims = get_current_claims(topic_id, limit=20)
    evidence_sets = list_evidence_sets(topic_id, limit=20)
    rc = _get_topic_research_context(topic_id)

    use_article_fallback = False
    fb_summary: dict | None = None
    fb_articles: list = []
    if not snapshots and not events and not claims and not evidence_sets:
        fb_summary = get_insight_summary(topic_id, 168)
        fb_articles = get_articles(
            limit=40, offset=0, topic_id=topic_id, sort="relevance", status="active"
        )
        if (fb_summary.get("total_articles") or 0) == 0 and not fb_articles:
            return None, (
                "Not enough data to generate a global overview yet. "
                "Fetch some articles for this topic first."
            )
        use_article_fallback = True

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
            ctx_parts.append(
                f"Date: {s['created_at']} · "
                f"window_start: {s.get('window_start', '')} · "
                f"window_end: {s.get('window_end', '')} · "
                f"status: {s.get('snapshot_status', '')}\n"
                f"Content: {s['summary_text']}\n"
            )

    if deltas:
        ctx_parts.append("=== Snapshot Deltas (Recent to Old) ===")
        for d in deltas:
            ctx_parts.append(
                f"Delta {d['id']} from {d.get('from_snapshot_id')} to {d.get('to_snapshot_id')}\n"
                f"Created: {d.get('created_at', '')}\n"
                f"Summary: {d.get('change_summary', '')}\n"
            )

    if events:
        ctx_parts.append("=== Active Events ===")
        for i, event in enumerate(events[:15], 1):
            ctx_parts.append(
                f"[Event-{i}] {event.get('title', '')}\n"
                f"Status: {event.get('status', '?')} · "
                f"Lifecycle: {event.get('event_status', '?')} · "
                f"first_seen: {event.get('first_seen_at', '')} · "
                f"last_seen: {event.get('last_seen_at', '')} · "
                f"created_at: {event.get('created_at', '')}\n"
                f"Summary: {event.get('summary', '')}"
            )

    if claims:
        ctx_parts.append("=== Active Claims ===")
        for i, claim in enumerate(claims, 1):
            ctx_parts.append(
                f"[Claim-{i}] {claim['statement']}\n"
                f"Lifecycle: {claim.get('status', '?')} · Kind: {claim.get('claim_kind', claim.get('claim_type', '?'))} · "
                f"staleness: {claim.get('staleness_status', '?')} · "
                f"last_validated: {claim.get('last_validated_at', '')} · "
                f"updated_at: {claim.get('updated_at', '')}\n"
                f"Summary: {claim.get('summary', '')}"
            )

    if evidence_sets:
        ctx_parts.append("=== Evidence Sets ===")
        for i, evidence in enumerate(evidence_sets[:10], 1):
            ctx_parts.append(
                f"[Evidence-{i}] {evidence['title']}\n"
                f"Type: {evidence.get('evidence_type', '?')} · Stance: {evidence.get('stance', '?')}\n"
                f"Created: {evidence.get('created_at', '')} · Updated: {evidence.get('updated_at', '')}\n"
                f"Summary: {evidence.get('summary', '')}"
            )

    if use_article_fallback and fb_summary is not None:
        ctx_parts.append(
            "=== Recent corpus (no daily snapshots / claims / evidence yet) ===\n"
            f"Article count (7d window): {fb_summary.get('total_articles', 0)} · "
            f"Important: {fb_summary.get('important_count', 0)}"
        )
        if fb_summary.get("top_events"):
            tops = fb_summary["top_events"][:5]
            ctx_parts.append(
                "Top events (from insights):\n"
                + "\n".join(
                    f"  • {(ev.get('title') or ev.get('id') or '')[:120]}" for ev in tops
                )
            )
        for i, art in enumerate(fb_articles[:35], 1):
            line = (
                f"[{i}] {art.get('title', '')}\n"
                f"    Source: {art.get('source', '')} · "
                f"Sentiment: {art.get('sentiment', '')}\n"
                f"    {str(art.get('summary', '') or '')[:400]}"
            )
            ctx_parts.append(line)

    return "\n\n".join(ctx_parts), None


def generate_global_overview_sync(topic_id: int) -> str:
    """Run global overview in a background thread: full LLM call + persist. Survives client disconnect."""
    ctx, err = _build_global_overview_context(topic_id)
    if err:
        return err

    snapshot_rows = get_temporal_snapshots(topic_id, window_type="daily", limit=5)
    delta_rows = get_snapshot_deltas(topic_id, limit=4)
    claim_rows = get_current_claims(topic_id, limit=20)

    messages = [
        {"role": "system", "content": GLOBAL_OVERVIEW_SYSTEM},
        {
            "role": "user",
            "content": (
                f"Current UTC time: {datetime.now(timezone.utc).isoformat()}\n\n"
                f"Context:\n{ctx}\n\n"
                "Write the comprehensive global overview."
            ),
        },
    ]
    result = llm_chat(messages, temperature=0.5)
    artifact_id = replace_synthesis_artifact(
        topic_id=topic_id,
        artifact_type="global_overview",
        title="Global Overview",
        content=result,
        status="final",
        metadata={"source": "temporal_snapshots"},
        source_snapshot_ids=[row["id"] for row in snapshot_rows],
        source_delta_ids=[row["id"] for row in delta_rows],
        source_claim_ids=[row["id"] for row in claim_rows],
    )
    add_artifact_document(
        artifact_id,
        result,
        {
            "topic_id": str(topic_id),
            "artifact_type": "global_overview",
            "status": "final",
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    return result


EVOLUTION_REPORT_SYSTEM = """You are a senior analyst writing an evolution report for a monitored topic.

Your task: Explain how the topic changed across recent snapshots. Focus on event turnover, claim strengthening, claim weakening, and structural shifts in the narrative.

Structure:
## 1. Major Changes
## 2. Strengthened Claims
## 3. Weakened Or Superseded Claims
## 4. What Changed In The Bigger Picture
"""


def generate_evolution_report_sync(topic_id: int) -> str:
    snapshots = get_temporal_snapshots(topic_id, window_type="daily", limit=5)
    deltas = get_snapshot_deltas(topic_id, limit=5)
    claims = get_claims_v2(topic_id, limit=20)

    ctx_parts: list[str] = []
    if snapshots:
        ctx_parts.append("=== Recent Snapshots ===")
        for snap in snapshots:
            ctx_parts.append(f"{snap['created_at']}\n{snap['summary_text']}")
    if deltas:
        ctx_parts.append("=== Snapshot Deltas ===")
        for delta in deltas:
            ctx_parts.append(delta.get("change_summary", ""))
    if claims:
        ctx_parts.append("=== Claims ===")
        for claim in claims[:15]:
            ctx_parts.append(
                f"{claim['statement']}\nstatus={claim.get('status', '?')} summary={claim.get('summary', '')}"
            )

    if not ctx_parts:
        articles = get_articles(
            limit=35, offset=0, topic_id=topic_id, sort="relevance", status="active"
        )
        if not articles:
            return ""
        ctx_parts.append(
            "=== Recent articles (no snapshot timeline yet; provisional evolution view) ==="
        )
        for art in articles[:30]:
            ctx_parts.append(
                f"- {art.get('title', '')}\n"
                f"  {str(art.get('summary', '') or '')[:320]}"
            )

    result = llm_chat(
        [
            {"role": "system", "content": EVOLUTION_REPORT_SYSTEM},
            {"role": "user", "content": "\n\n".join(ctx_parts)},
        ],
        temperature=0.4,
    )
    artifact_id = replace_synthesis_artifact(
        topic_id=topic_id,
        artifact_type="evolution_report",
        title="Evolution Report",
        content=result,
        status="final",
        metadata={"source": "snapshot_deltas"},
        source_snapshot_ids=[row["id"] for row in snapshots],
        source_delta_ids=[row["id"] for row in deltas],
        source_claim_ids=[row["id"] for row in claims[:15]],
    )
    add_artifact_document(
        artifact_id,
        result,
        {
            "topic_id": str(topic_id),
            "artifact_type": "evolution_report",
            "status": "final",
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    return result


def generate_global_overview(topic_id: int):
    """Streaming global overview generator."""
    yield {"status": "analyzing_history"}

    ctx, err = _build_global_overview_context(topic_id)
    if err:
        yield err
        return

    yield {"status": "generating_global"}

    messages = [
        {"role": "system", "content": GLOBAL_OVERVIEW_SYSTEM},
        {
            "role": "user",
            "content": (
                f"Current UTC time: {datetime.now(timezone.utc).isoformat()}\n\n"
                f"Context:\n{ctx}\n\n"
                "Write the comprehensive global overview."
            ),
        },
    ]

    collected = []
    for chunk in llm_chat_stream(messages, temperature=0.5):
        collected.append(chunk)
        yield chunk


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
