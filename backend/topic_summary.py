"""Generate, persist, and vectorize AI narrative summaries for topics."""

import hashlib
import json
import re as _re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta

from database import (
    get_articles,
    get_event_card_summaries,
    get_current_claims,
    get_events_v2,
    get_insight_summary,
    get_topic_insights,
    get_claims_v2,
    get_claims_by_ids,
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

CitationItem = dict[str, str]


@dataclass
class EvolutionFactBundle:
    """Structured input bundle for the two-stage evolution report pipeline.

    Replaces the long debug string as the primary data vehicle between DB
    loading and LLM generation.  Both the extractor (Stage B) and the
    narrator (Stage C) receive this object; each stage decides which fields
    to consume.
    """

    topic_id: int
    tier: str                          # 'skip' | 'provisional' | 'full'
    error: str | None                  # set only when tier == 'skip'
    research_context: dict

    baseline_snapshot: dict | None
    current_snapshot: dict | None
    intermediate_snapshots: list[dict]

    baseline_events: list[dict]
    current_events: list[dict]
    baseline_claims: list[dict]
    current_claims: list[dict]

    new_events: list[dict]             # events in TN but not T1
    resolved_events: list[dict]        # events in T1 but not TN
    new_claims: list[dict]             # claims in TN but not T1
    dropped_claims: list[dict]         # claims in T1 but not TN
    persisted_claims: list[dict]       # claims in both snapshots

    claim_evolution_records: list[dict]
    snapshot_deltas: list[dict]
    evidence_sets: list[dict]


@dataclass
class DiffFacts:
    """Structured change facts extracted by the LLM extractor (Stage B).

    The narrator (Stage C) receives ONLY this object plus the citation
    catalog — not the raw snapshot prose.  Keeps the narrator grounded.

    Schema v2 adds:
    - top_changes: 3-5 thematic shifts that drive the whole narrative
    - change_id / priority / narrative_role per item for section routing
    - supported_by_event_ids on claim_trajectories (explicit event binding)
    - derived_from_change_ids on strategic_implications (traceability)
    """

    top_changes: list[dict]             # 3-5 prioritized thematic shifts (narrative_role="observed_change")
    event_transitions: list[dict]       # emerged / resolved / reframed events
    claim_trajectories: list[dict]      # emerged / dropped / strengthened / weakened claims
    strategic_implications: list[dict]  # high-level inferences derived from top_changes

    validation_errors: list[str] = field(default_factory=list)
    raw_extractor_hash: str = ""

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
- Be specific: cite sources when relevant.
- Prioritize significance over completeness — pick what matters most.
- Use clear, direct language. No filler.
- Write in the same language as the article titles (if titles are in Chinese, write in Chinese; if English, write in English).
- If there are very few or no articles, say so honestly and keep it short.
- Perform an internal freshness reasoning pass before writing (recency, consistency, corroboration), but do NOT reveal hidden reasoning steps.
- If information appears old or uncertain, lower confidence in wording and place it in Timeliness Assessment.
- Reflect narrative evolution in existing sections: new events appearing, old events being superseded, and claim strengthening/weakening.
- Citation: when you state a fact supported by a source in the [Citation Catalog], append its ID inline right after the statement: e.g. "Growth slowed [E1] amid supply issues [A2]." Use square brackets only; never invent IDs.
- ONLY use E# and A# IDs from the [Citation Catalog] as inline citations. Do NOT use context reference labels like [Claim-N], [Event-N], [Evidence-N] as citations in the output."""


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


def _analysis_time_text(row: dict) -> str:
    """Human-readable analysis timeline timestamp: published_at first."""
    return str(row.get("published_at") or row.get("created_at") or "")


def _build_citation_catalog(topic_id: int) -> list[CitationItem]:
    """Build a compact citation catalog for long-form analysis rendering."""
    summary = get_insight_summary(topic_id, 168)
    events = summary.get("top_events", [])[:8]
    articles = get_articles(
        limit=30, offset=0, topic_id=topic_id, sort="relevance", status="active"
    )
    citations: list[CitationItem] = []
    used_urls: set[str] = set()
    event_idx = 1
    article_idx = 1

    for event in events:
        url = str(event.get("canonical_url") or "").strip()
        title = str(event.get("title") or "").strip()
        if not url or not title or url in used_urls:
            continue
        used_urls.add(url)
        citations.append(
            {
                "id": f"E{event_idx}",
                "type": "event",
                "title": title,
                "url": url,
            }
        )
        event_idx += 1

    for article in articles:
        url = str(article.get("url") or "").strip()
        title = str(article.get("title") or "").strip()
        if not url or not title or url in used_urls:
            continue
        used_urls.add(url)
        citations.append(
            {
                "id": f"A{article_idx}",
                "type": "article",
                "title": title,
                "url": url,
            }
        )
        article_idx += 1
        if article_idx > 8:
            break
    return citations


def _build_evolution_citation_catalog(
    topic_id: int,
    oldest_ts: str,
    newest_ts: str,
) -> list[CitationItem]:
    """Build a citation catalog scoped to the evolution report's snapshot time span.

    Unlike _build_citation_catalog (fixed 168h window), this computes the hours
    between oldest_ts and now to ensure events from the full snapshot span are
    included.  Falls back to 720h (30 days) when timestamps are unavailable.
    """
    # Compute hours from oldest snapshot to now
    try:
        oldest_dt = _coerce_dt(oldest_ts)
        now = datetime.now(timezone.utc)
        span_hours = max(int((now - oldest_dt).total_seconds() / 3600) + 24, 48) if oldest_dt else 720
    except Exception:
        span_hours = 720

    # Cap at 90 days to avoid querying the entire DB
    span_hours = min(span_hours, 2160)

    summary = get_insight_summary(topic_id, span_hours)
    events = summary.get("top_events", [])[:10]
    articles = get_articles(
        limit=30, offset=0, topic_id=topic_id, sort="relevance", status="active"
    )

    citations: list[CitationItem] = []
    used_urls: set[str] = set()
    event_idx = 1
    article_idx = 1

    for event in events:
        url = str(event.get("canonical_url") or "").strip()
        title = str(event.get("title") or "").strip()
        if not url or not title or url in used_urls:
            continue
        used_urls.add(url)
        citations.append({"id": f"E{event_idx}", "type": "event", "title": title, "url": url})
        event_idx += 1

    for article in articles:
        url = str(article.get("url") or "").strip()
        title = str(article.get("title") or "").strip()
        if not url or not title or url in used_urls:
            continue
        used_urls.add(url)
        citations.append({"id": f"A{article_idx}", "type": "article", "title": title, "url": url})
        article_idx += 1
        if article_idx > 10:
            break

    return citations


def _build_citation_prompt(citations: list[CitationItem]) -> str:
    if not citations:
        return ""
    lines = ["[Citation Catalog]"]
    for c in citations:
        lines.append(f"  {c['id']} ({c['type']}): {c['title']}")
    lines.append(
        "Append the matching ID in square brackets inline after any statement it supports. "
        "When citing multiple sources, write each in its own brackets separated by a space: [E1] [E2] not [E1][E2]."
    )
    return "\n".join(lines)


def _collect_evolution_diagnostics(
    ctx: str,
    user_content: str,
    citations: list[CitationItem],
    raw_llm_out: str,
    result: str,
    tier: str,
) -> dict:
    """Collect structured diagnostics for a single evolution report generation.

    This is stored in the artifact metadata so that each generation run is
    self-documenting.  It enables post-hoc attribution of generic output to
    either context quality, signal tier, or prompt compliance.
    """
    # Section names and per-section char lengths
    section_names = _re.findall(r"=== (.+?) ===", ctx)
    raw_parts = _re.split(r"=== .+? ===", ctx)
    section_lengths: dict[str, int] = {
        name: len(raw_parts[i + 1].strip()) if i + 1 < len(raw_parts) else 0
        for i, name in enumerate(section_names)
    }

    # Diff signal counts (markers injected by _build_evolution_context_v2)
    diff_signals = {
        "new_events": len(_re.findall(r"\[NE\]", ctx)),
        "resolved_events": len(_re.findall(r"\[RE\]", ctx)),
        "new_claims": len(_re.findall(r"\[NC\]", ctx)),
        "dropped_claims": len(_re.findall(r"\[DC\]", ctx)),
        "persisted_claims": len(_re.findall(r"\[PC\]", ctx)),
        "evo_records": len(_re.findall(r"\[EvoRecord-\d+\]", ctx)),
    }

    # Citation usage
    cited_in_result = list(set(_re.findall(r"\[([EA]\d+)\]", result)))

    return {
        "tier": tier,
        "context_length": len(ctx),
        "user_content_length": len(user_content),
        "section_names": section_names,
        "section_lengths": section_lengths,
        "diff_signals": diff_signals,
        "citation_ids_available": [c["id"] for c in citations],
        "citation_ids_used": cited_in_result,
        "citations_used_count": len(cited_in_result),
        "raw_llm_out_length": len(raw_llm_out),
        "result_length": len(result),
        "result_hash": hashlib.md5(result.encode()).hexdigest()[:8],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _detect_generic_output(
    result: str,
    ctx: str,
    citations: list[CitationItem],
) -> dict:
    """Heuristic check for low-signal / generic LLM output.

    Does NOT block artifact storage — attaches a label so you can quickly
    distinguish 'context problem' from 'prompt compliance problem'.

    Returns a dict with 'is_generic', 'flags', and supporting counts.
    """
    flags: list[str] = []

    # 1. Citation density: fewer than 2 distinct citations used
    cited = list(set(_re.findall(r"\[([EA]\d+)\]", result)))
    if len(cited) < 2:
        flags.append("few_citations")

    # 2. Diff entity coverage: titles from injected diff markers appear in result
    injected_titles = _re.findall(r"\[(?:NE|NC|DC|RE|PC)\] ([^\n]+)", ctx)
    if injected_titles:
        # Check if at least one meaningful word from any injected title appears
        matched = sum(
            1
            for title in injected_titles[:30]
            for word in title.split()[:5]
            if len(word) > 5 and word.lower() in result.lower()
        )
        if matched == 0:
            flags.append("no_diff_entities_referenced")

    # 3. Section length uniformity: all four sections similar length → template prose
    section_texts = _re.split(r"## \d+\.", result)[1:]
    if len(section_texts) >= 4:
        lengths = [len(s.strip()) for s in section_texts[:4]]
        avg = sum(lengths) / len(lengths)
        if avg > 0:
            cv = (sum((l - avg) ** 2 for l in lengths) / len(lengths)) ** 0.5 / avg
            if cv < 0.15:
                flags.append("section_length_uniform")

    # 4. Generic phrase density
    generic_phrases = [
        "in the bigger picture",
        "macro narrative",
        "strategic balance",
        "risk profile",
        "overall trajectory",
        "broadly speaking",
        "in general terms",
    ]
    generic_hits = sum(1 for p in generic_phrases if p.lower() in result.lower())
    if generic_hits >= 3:
        flags.append("high_generic_phrase_density")

    return {
        "is_generic": len(flags) >= 2,
        "flags": flags,
        "citations_used": len(cited),
        "diff_entity_matches": matched if injected_titles else 0,
        "injected_titles_sampled": len(injected_titles),
    }


def _parse_json_content(
    raw: str,
    catalog: list[CitationItem],
) -> str:
    """Try to extract 'content' from a JSON-wrapped LLM response.

    If the LLM returned valid JSON with a 'content' key, extract and return it.
    Optionally strip any citation IDs that were not in the original catalog.
    Falls back to the raw string when parsing fails.
    """
    import json as _json

    text = raw.strip()
    # Strip markdown code fences that some models add around JSON
    if text.startswith("```"):
        lines = text.splitlines()
        inner = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(inner).strip()

    try:
        obj = _json.loads(text)
    except (_json.JSONDecodeError, ValueError):
        return raw  # Not JSON — return as-is (graceful degradation)

    if not isinstance(obj, dict):
        return raw

    content = obj.get("content")
    if not isinstance(content, str) or not content.strip():
        return raw

    # Validate cited_ids: remove inline markers not in catalog
    valid_ids = {c["id"] for c in catalog}
    import re as _re

    def _drop_invalid(m: "_re.Match[str]") -> str:
        cid = m.group(1)
        return m.group(0) if cid in valid_ids else ""

    content = _re.sub(r"\[([EA]\d+)\]", _drop_invalid, content)
    return content


def _normalize_citations(text: str, catalog: list[CitationItem]) -> str:
    """Post-process streaming LLM output to normalise common citation format errors.

    Handles:
    - (E1) / (A2)  → [E1] / [A2]         (wrong bracket style)
    - [e1] / [a2]  → [E1] / [A2]         (lower-case IDs)
    - (see E1) / (Source: E1) → [E1]     (verbose reference style)
    - Any citation ID not in catalog is removed to avoid dangling buttons.
    """
    import re as _re

    valid_ids = {c["id"] for c in catalog}

    # (E1) or (A2) with optional space
    text = _re.sub(
        r"\(\s*([EA]\d+)\s*\)",
        lambda m: f"[{m.group(1).upper()}]",
        text,
    )
    # (see E1) / (Source: E1) / (ref: E1)
    text = _re.sub(
        r"\(\s*(?:see|source|ref|cf\.?)\s*:?\s*([EA]\d+)\s*\)",
        lambda m: f"[{m.group(1).upper()}]",
        text,
        flags=_re.IGNORECASE,
    )
    # Lower-case [e1] / [a2]
    text = _re.sub(
        r"\[([ea]\d+)\]",
        lambda m: f"[{m.group(1).upper()}]",
        text,
    )
    # Remove IDs that are not in the catalog
    def _drop_invalid(m: "_re.Match[str]") -> str:
        cid = m.group(1)
        return m.group(0) if cid in valid_ids else ""

    text = _re.sub(r"\[([EA]\d+)\]", _drop_invalid, text)

    # Strip internal DiffFacts change_id labels that leaked into narrative
    # (e.g. TC1, TC2, EV1, EV2, CL1, SI1 — structural references, not citable)
    text = _re.sub(r"\[(?:TC|EV|CL|SI)\d+\]", "", text)
    text = _re.sub(r"\b(?:TC|EV|CL|SI)\d+\b", "", text)

    # Normalize bare external catalog IDs that are missing brackets
    # e.g. "转运 E5。" → "转运 [E5]。"  (only for IDs present in catalog)
    def _bracket_or_drop_bare(m: "_re.Match[str]") -> str:
        cid = m.group(1)
        return f"[{cid}]" if cid in valid_ids else ""

    text = _re.sub(r"(?<!\[)\b([EA]\d+)\b(?!\])", _bracket_or_drop_bare, text)

    # Ensure space between adjacent citation badges: [E1][E2] → [E1] [E2]
    text = _re.sub(r"\]\s*\[", "] [", text)

    # Downgrade context-reference pseudo-citations to plain readable text.
    # These have no catalog entry and cannot become clickable buttons.
    # Handles variants: mixed-case, spaces around hyphen, en-dash, em-dash.
    # e.g. [Claim-12] -> "Claim 12", [Event-7] -> "Event 7", [claim - 3] -> "Claim 3"
    def _downgrade_pseudo(m: "_re.Match[str]") -> str:
        kind = m.group(1).capitalize()
        num = m.group(2)
        return f"{kind} {num}"

    text = _re.sub(
        r"\[(Claim|Event|Evidence|Evolution)\s*[-\u2013\u2014]\s*(\d+)\]",
        _downgrade_pseudo,
        text,
        flags=_re.IGNORECASE,
    )

    return text


def _collect_stats_metadata(
    topic_id: int,
    hours: int = 24,
    citations: list[CitationItem] | None = None,
) -> dict:
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
        "citations": citations or [],
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
    claim_evolution = get_claim_evolution(topic_id, limit=25)

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
                analysis_ts = _analysis_time_text(event)
                parts.append(
                    f"  EventRef {i}: {event['title']} "
                    f"(status: {event.get('status', '?')}, "
                    f"lifecycle: {event.get('event_status', '?')}, "
                    f"analysis_time: {analysis_ts}, "
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
                    f"  ClaimRef {i}: {claim['statement']}\n"
                    f"      lifecycle: {claim.get('status', '?')} · "
                    f"kind: {claim.get('claim_kind', claim.get('claim_type', '?'))} · "
                    f"staleness: {claim.get('staleness_status', '?')} · "
                    f"last_refreshed: {claim.get('last_refreshed_at', claim.get('last_validated_at', ''))} · "
                    f"updated_at: {claim.get('updated_at', '')}\n"
                    f"      {claim.get('summary', '')[:220]}"
                )
        if claim_evolution:
            parts.append("\n[Claim evolution signals]")
            for i, evo in enumerate(claim_evolution[:12], 1):
                parts.append(
                    f"  EvolutionRef {i}: relation: {evo.get('relation_type', '?')} · "
                    f"claim_id: {evo.get('claim_id', '')} · previous_claim_id: {evo.get('previous_claim_id', '')} · "
                    f"time: {evo.get('created_at', '')}\n"
                    f"      reason: {evo.get('reason', '')}"
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
    """Compute the change summary between two consecutive snapshots.

    Semantic separation (critical):
    - emerged_claim_ids / dropped_claim_ids  — pure set-difference of snapshot
      claim membership (a claim appeared or disappeared, reason unknown).
    - strengthened_claim_ids / weakened_claim_ids — ONLY from claim_evolution
      table entries with the matching relation_type.  These carry semantic
      meaning ("an analyst flagged this claim as strengthening/weakening").

    The DB columns `strengthened_claim_ids` and `weakened_claim_ids` store the
    semantically correct values; emerged/dropped are appended to metadata_json
    so callers can access them without a schema migration.
    """
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

    # Set-difference signals: membership change, not semantic strength change
    emerged_claim_ids: set[str] = current_claim_ids - prev_claim_ids
    dropped_claim_ids: set[str] = prev_claim_ids - current_claim_ids

    # Semantic signals: only from claim_evolution (relation_type labels)
    strengthened_claim_ids: set[str] = set()
    weakened_claim_ids: set[str] = set()
    superseded_claim_ids: set[str] = {
        c["id"] for c in current_claims if c.get("status") in {"superseded", "obsolete"}
    }

    current_time = max(
        [
            _coerce_dt((current_events[0] if current_events else {}).get("last_seen_at")),
            _coerce_dt((current_claims[0] if current_claims else {}).get("last_refreshed_at")),
        ],
        key=lambda dt: dt or datetime.min.replace(tzinfo=timezone.utc),
    )
    previous_time = max(
        [
            _coerce_dt((prev_events[0] if prev_events else {}).get("last_seen_at")),
            _coerce_dt((prev_claims[0] if prev_claims else {}).get("last_refreshed_at")),
        ],
        key=lambda dt: dt or datetime.min.replace(tzinfo=timezone.utc),
    )

    for row in recent_evolution:
        relation = row.get("relation_type")
        created_at = _coerce_dt(row.get("created_at"))
        current_claim_id = row.get("claim_id")
        previous_claim_id = row.get("previous_claim_id")

        relates_to_transition = (
            previous_claim_id in prev_claim_ids and current_claim_id in current_claim_ids
        )
        if relates_to_transition:
            if relation == "strengthened" and current_claim_id:
                strengthened_claim_ids.add(current_claim_id)
            if relation in {"weakened", "withdrawn"} and current_claim_id:
                weakened_claim_ids.add(current_claim_id)
            if relation == "supersedes" and previous_claim_id:
                superseded_claim_ids.add(previous_claim_id)
            continue

        if previous_time and created_at and created_at <= previous_time:
            continue
        if current_time and created_at and created_at > current_time + timedelta(days=1):
            continue

        if relation == "strengthened" and current_claim_id:
            strengthened_claim_ids.add(current_claim_id)
        if relation in {"weakened", "withdrawn"} and current_claim_id:
            weakened_claim_ids.add(current_claim_id)
        if relation == "supersedes" and previous_claim_id:
            superseded_claim_ids.add(previous_claim_id)

    strengthened_list = sorted(strengthened_claim_ids)
    weakened_list = sorted(weakened_claim_ids)
    superseded_list = sorted(superseded_claim_ids)
    emerged_list = sorted(emerged_claim_ids)
    dropped_list = sorted(dropped_claim_ids)

    summary = (
        f"Topic {topic_id} changed between snapshots: "
        f"{len(new_event_ids)} new events, {len(resolved_event_ids)} resolved events, "
        f"{len(emerged_list)} emerged claims, {len(dropped_list)} dropped claims, "
        f"{len(strengthened_list)} strengthened claims (semantic), "
        f"{len(weakened_list)} weakened claims (semantic)."
    )
    return {
        "change_summary": summary,
        "new_event_ids": new_event_ids,
        "resolved_event_ids": resolved_event_ids,
        # Semantically labelled from claim_evolution only
        "strengthened_claim_ids": strengthened_list,
        "weakened_claim_ids": weakened_list,
        "superseded_claim_ids": superseded_list,
        # Set-difference membership signals (stored in metadata for callers)
        "emerged_claim_ids": emerged_list,
        "dropped_claim_ids": dropped_list,
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
        metadata={
            "window_type": "daily",
            # Set-difference membership signals (not stored in dedicated columns)
            "emerged_claim_ids": delta.get("emerged_claim_ids", []),
            "dropped_claim_ids": delta.get("dropped_claim_ids", []),
        },
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

    citations = _build_citation_catalog(topic_id)
    stats = _collect_stats_metadata(topic_id, hours, citations)

    yield {"status": "generating"}

    messages = [
        {"role": "system", "content": SUMMARY_SYSTEM},
        {
            "role": "user",
            "content": (
                f"Current UTC time: {datetime.now(timezone.utc).isoformat()}\n\n"
                f"Context:\n{ctx}\n\n"
                f"{_build_citation_prompt(citations)}\n\n"
                "Write the executive briefing based on the above data."
            ),
        },
    ]

    collected = []
    for chunk in llm_chat_stream(messages, temperature=0.4):
        collected.append(chunk)
        yield chunk

    overview_text = _normalize_citations("".join(collected), citations)
    _persist_and_vectorize(topic_id, overview_text, stats, events, claims)


def generate_summary_sync(topic_id: int, hours: int = 24) -> str:
    """Non-streaming version for scheduled background generation."""
    ctx, events, claims = _build_context(topic_id, hours)
    if not ctx:
        return ""

    from llm_client import llm_chat

    citations = _build_citation_catalog(topic_id)
    stats = _collect_stats_metadata(topic_id, hours, citations)

    messages = [
        {"role": "system", "content": SUMMARY_SYSTEM},
        {
            "role": "user",
            "content": (
                f"Current UTC time: {datetime.now(timezone.utc).isoformat()}\n\n"
                f"Context:\n{ctx}\n\n"
                f"{_build_citation_prompt(citations)}\n\n"
                "Write the executive briefing based on the above data."
            ),
        },
    ]
    result = _normalize_citations(llm_chat(messages, temperature=0.4), citations)
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
- Prefer newer snapshots/events/claims when older evidence conflicts; explicitly down-rank stale evidence in section 5.
- Explicitly capture narrative evolution in existing sections (new events, replaced/obsolete events, claim strengthening/weakening).
- Citation: when you state a fact supported by a source in the [Citation Catalog], append its ID inline right after the statement: e.g. "Growth slowed [E1] amid supply issues [A2]." Use square brackets only; never invent IDs.
- ONLY use IDs from the [Citation Catalog] (E# and A# format) as inline citations. Do NOT reference context labels like ClaimRef, EventRef, EvidenceRef, EvolutionRef, [Claim-N], [Event-N], [Evidence-N], or [Evidence-N] as citations in the output."""


def _build_global_overview_context(topic_id: int) -> tuple[str | None, str | None]:
    """Returns (context_string, error_message_if_skip). If skip, context is None."""
    snapshots = get_temporal_snapshots(topic_id, window_type="daily", limit=5)
    deltas = get_snapshot_deltas(topic_id, limit=4)
    events = get_events_v2(topic_id, status=None, limit=20)
    claims = get_current_claims(topic_id, limit=20)
    claim_evolution = get_claim_evolution(topic_id, limit=30)
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
                f"TimelineDate: {s.get('window_end') or s.get('created_at', '')} · "
                f"snapshot_created_at: {s.get('created_at', '')} · "
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
            analysis_ts = _analysis_time_text(event)
            ctx_parts.append(
                f"EventRef {i}: {event.get('title', '')}\n"
                f"Status: {event.get('status', '?')} · "
                f"Lifecycle: {event.get('event_status', '?')} · "
                f"analysis_time: {analysis_ts} · "
                f"first_seen: {event.get('first_seen_at', '')} · "
                f"last_seen: {event.get('last_seen_at', '')} · "
                f"created_at: {event.get('created_at', '')}\n"
                f"Summary: {event.get('summary', '')}"
            )

    if claims:
        ctx_parts.append("=== Active Claims ===")
        for i, claim in enumerate(claims, 1):
            ctx_parts.append(
                f"ClaimRef {i}: {claim['statement']}\n"
                f"Lifecycle: {claim.get('status', '?')} · Kind: {claim.get('claim_kind', claim.get('claim_type', '?'))} · "
                f"staleness: {claim.get('staleness_status', '?')} · "
                f"last_validated: {claim.get('last_validated_at', '')} · "
                f"updated_at: {claim.get('updated_at', '')}\n"
                f"Summary: {claim.get('summary', '')}"
            )
    if claim_evolution:
        ctx_parts.append("=== Claim Evolution Signals ===")
        for i, evo in enumerate(claim_evolution[:15], 1):
            ctx_parts.append(
                f"EvolutionRef {i}: relation={evo.get('relation_type', '?')} "
                f"claim_id={evo.get('claim_id', '')} previous_claim_id={evo.get('previous_claim_id', '')}\n"
                f"created_at={evo.get('created_at', '')}\n"
                f"reason={evo.get('reason', '')}"
            )

    if evidence_sets:
        ctx_parts.append("=== Evidence Sets ===")
        for i, evidence in enumerate(evidence_sets[:10], 1):
            ctx_parts.append(
                f"EvidenceRef {i}: {evidence['title']}\n"
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
    citations = _build_citation_catalog(topic_id)

    messages = [
        {"role": "system", "content": GLOBAL_OVERVIEW_SYSTEM},
        {
            "role": "user",
            "content": (
                f"Current UTC time: {datetime.now(timezone.utc).isoformat()}\n\n"
                f"Context:\n{ctx}\n\n"
                f"{_build_citation_prompt(citations)}\n\n"
                "Write the comprehensive global overview."
            ),
        },
    ]
    result = _normalize_citations(llm_chat(messages, temperature=0.5), citations)
    artifact_id = replace_synthesis_artifact(
        topic_id=topic_id,
        artifact_type="global_overview",
        title="Global Overview",
        content=result,
        status="final",
        metadata={"source": "temporal_snapshots", "citations": citations},
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


# ─────────────────────────────────────────────────────────────────────────────
# Stage A: EvolutionFactBundle assembly
# ─────────────────────────────────────────────────────────────────────────────

def _load_evolution_fact_bundle(topic_id: int) -> EvolutionFactBundle:
    """Load all evolution data from DB and assemble an EvolutionFactBundle.

    This is the single canonical data-assembly step for the two-stage
    evolution pipeline.  It does NOT produce any string output; downstream
    stages (extractor, narrator, debug renderer) receive the bundle and
    decide independently how to consume it.
    """
    snapshots = get_temporal_snapshots(topic_id, window_type="daily", limit=6)
    deltas = get_snapshot_deltas(topic_id, limit=5)
    rc = _get_topic_research_context(topic_id)

    # ── Skip: no snapshots AND no articles ────────────────────────────────
    if not snapshots:
        articles = get_articles(
            limit=35, offset=0, topic_id=topic_id, sort="relevance", status="active"
        )
        if not articles:
            return EvolutionFactBundle(
                topic_id=topic_id,
                tier="skip",
                error=(
                    "Not enough temporal data to generate an evolution report yet. "
                    "The topic needs at least two daily snapshots. "
                    "Fetch some articles and run the summary pipeline first."
                ),
                research_context=rc,
                baseline_snapshot=None,
                current_snapshot=None,
                intermediate_snapshots=[],
                baseline_events=[],
                current_events=[],
                baseline_claims=[],
                current_claims=[],
                new_events=[],
                resolved_events=[],
                new_claims=[],
                dropped_claims=[],
                persisted_claims=[],
                claim_evolution_records=[],
                snapshot_deltas=deltas,
                evidence_sets=[],
            )
        # Provisional: articles exist but no snapshots yet
        return EvolutionFactBundle(
            topic_id=topic_id,
            tier="provisional",
            error=None,
            research_context=rc,
            baseline_snapshot=None,
            current_snapshot=None,
            intermediate_snapshots=[],
            baseline_events=[],
            current_events=[],
            baseline_claims=[],
            current_claims=[],
            new_events=[],
            resolved_events=[],
            new_claims=[],
            dropped_claims=[],
            persisted_claims=[],
            claim_evolution_records=[],
            snapshot_deltas=deltas,
            evidence_sets=[],
        )

    # DB returns newest first — snapshots[0] = TN, snapshots[-1] = T1
    current_snap = snapshots[0]
    baseline_snap = snapshots[-1]
    intermediate_snaps = list(reversed(snapshots[1:-1]))

    baseline_events = get_snapshot_events(baseline_snap["id"])
    current_events = get_snapshot_events(current_snap["id"])
    baseline_claims = get_snapshot_claims(baseline_snap["id"])
    current_claims = get_snapshot_claims(current_snap["id"])

    baseline_event_ids = {e["id"] for e in baseline_events}
    current_event_ids = {e["id"] for e in current_events}
    baseline_claim_ids = {c["id"] for c in baseline_claims}
    current_claim_ids = {c["id"] for c in current_claims}

    all_events: dict = {e["id"]: e for e in baseline_events + current_events}
    all_claims: dict = {c["id"]: c for c in baseline_claims + current_claims}

    new_event_ids = current_event_ids - baseline_event_ids
    resolved_event_ids = baseline_event_ids - current_event_ids
    new_claim_ids = current_claim_ids - baseline_claim_ids
    dropped_claim_ids = baseline_claim_ids - current_claim_ids
    persisted_claim_ids = baseline_claim_ids & current_claim_ids

    claim_evolution = get_claim_evolution(topic_id, limit=30)
    evidence_sets = list_evidence_sets(topic_id, limit=10)

    has_diff_signals = bool(
        new_event_ids or resolved_event_ids or new_claim_ids
        or dropped_claim_ids or claim_evolution
    )
    tier = "full" if has_diff_signals else "provisional"

    return EvolutionFactBundle(
        topic_id=topic_id,
        tier=tier,
        error=None,
        research_context=rc,
        baseline_snapshot=baseline_snap,
        current_snapshot=current_snap,
        intermediate_snapshots=intermediate_snaps,
        baseline_events=baseline_events,
        current_events=current_events,
        baseline_claims=baseline_claims,
        current_claims=current_claims,
        new_events=[all_events[eid] for eid in new_event_ids if eid in all_events],
        resolved_events=[all_events[eid] for eid in resolved_event_ids if eid in all_events],
        new_claims=[all_claims[cid] for cid in new_claim_ids if cid in all_claims],
        dropped_claims=[all_claims[cid] for cid in dropped_claim_ids if cid in all_claims],
        persisted_claims=[all_claims[cid] for cid in persisted_claim_ids if cid in all_claims],
        claim_evolution_records=claim_evolution,
        snapshot_deltas=deltas,
        evidence_sets=evidence_sets,
    )


def _render_evolution_debug_context(bundle: EvolutionFactBundle) -> str:
    """Render an EvolutionFactBundle as a human-readable debug string.

    Used by the debug script and the backward-compat wrapper.  NOT passed
    directly to the narrator — the narrator receives structured DiffFacts.
    """
    rc = bundle.research_context
    ctx_parts: list[str] = []

    if rc.get("brief") or rc.get("angles"):
        ctx_parts.append("=== Research Context ===")
        if rc.get("brief"):
            ctx_parts.append(f"Research Direction: {rc['brief']}")
        if rc.get("angles"):
            ctx_parts.append(
                "Research Angles:\n" + "\n".join(f"  • {a}" for a in rc["angles"])
            )
        if rc.get("entities"):
            ctx_parts.append(f"Key Entities: {', '.join(rc['entities'])}")
        if rc.get("geographic_scope"):
            ctx_parts.append(f"Geographic Scope: {', '.join(rc['geographic_scope'])}")

    if bundle.baseline_snapshot:
        b_ts = (
            bundle.baseline_snapshot.get("window_end")
            or bundle.baseline_snapshot.get("created_at", "")
        )
        ctx_parts.append(f"=== Baseline Snapshot [T1 · {b_ts}] ===")
        ctx_parts.append(f"Summary:\n{bundle.baseline_snapshot['summary_text']}")
        if bundle.baseline_events:
            ev_lines = "\n".join(
                f"  • {ev.get('title', '')} (lifecycle={ev.get('event_status', '?')})"
                for ev in bundle.baseline_events[:12]
            )
            ctx_parts.append(
                f"Active Events at T1 ({len(bundle.baseline_events)}):\n{ev_lines}"
            )
        if bundle.baseline_claims:
            cl_lines = "\n".join(
                f"  • {c['statement']} [staleness={c.get('staleness_status', '?')}]"
                for c in bundle.baseline_claims[:15]
            )
            ctx_parts.append(
                f"Active Claims at T1 ({len(bundle.baseline_claims)}):\n{cl_lines}"
            )

    if bundle.current_snapshot:
        c_ts = (
            bundle.current_snapshot.get("window_end")
            or bundle.current_snapshot.get("created_at", "")
        )
        ctx_parts.append(f"=== Current Snapshot [TN · {c_ts}] ===")
        ctx_parts.append(f"Summary:\n{bundle.current_snapshot['summary_text']}")
        if bundle.current_events:
            ev_lines = "\n".join(
                f"  • {ev.get('title', '')} (lifecycle={ev.get('event_status', '?')})"
                for ev in bundle.current_events[:12]
            )
            ctx_parts.append(
                f"Active Events at TN ({len(bundle.current_events)}):\n{ev_lines}"
            )
        if bundle.current_claims:
            cl_lines = "\n".join(
                f"  • {c['statement']} [staleness={c.get('staleness_status', '?')}]"
                for c in bundle.current_claims[:15]
            )
            ctx_parts.append(
                f"Active Claims at TN ({len(bundle.current_claims)}):\n{cl_lines}"
            )

    b_ts_s = (
        str(
            bundle.baseline_snapshot.get("window_end")
            or bundle.baseline_snapshot.get("created_at", "")
        )[:19]
        if bundle.baseline_snapshot
        else ""
    )
    c_ts_s = (
        str(
            bundle.current_snapshot.get("window_end")
            or bundle.current_snapshot.get("created_at", "")
        )[:19]
        if bundle.current_snapshot
        else ""
    )
    diff_parts: list[str] = []

    if bundle.new_events:
        lines = [
            f"  [NE] {ev.get('title', ev['id'])}\n"
            f"       first_seen={ev.get('first_seen_at', '')} · "
            f"last_seen={ev.get('last_seen_at', '')} · "
            f"status={ev.get('event_status', '?')}\n"
            f"       {str(ev.get('summary', '') or '')[:220]}"
            for ev in bundle.new_events[:10]
        ]
        diff_parts.append(
            f"[+] New Events ({len(bundle.new_events)} appeared after baseline):\n"
            + "\n".join(lines)
        )

    if bundle.resolved_events:
        lines = [
            f"  [RE] {ev.get('title', ev['id'])}\n"
            f"       {str(ev.get('summary', '') or '')[:180]}"
            for ev in bundle.resolved_events[:10]
        ]
        diff_parts.append(
            f"[-] Resolved Events ({len(bundle.resolved_events)} gone since baseline):\n"
            + "\n".join(lines)
        )

    if bundle.new_claims:
        lines = [
            f"  [NC] {cl.get('statement', cl['id'])}\n"
            f"       staleness={cl.get('staleness_status', '?')} · "
            f"kind={cl.get('claim_type', '?')}\n"
            f"       {str(cl.get('summary', '') or '')[:200]}"
            for cl in bundle.new_claims[:12]
        ]
        diff_parts.append(
            f"[+] New Claims ({len(bundle.new_claims)} emerged since baseline):\n"
            + "\n".join(lines)
        )

    if bundle.dropped_claims:
        lines = [
            f"  [DC] {cl.get('statement', cl['id'])}\n"
            f"       staleness={cl.get('staleness_status', '?')} · "
            f"kind={cl.get('claim_type', '?')}"
            for cl in bundle.dropped_claims[:12]
        ]
        diff_parts.append(
            f"[-] Dropped Claims ({len(bundle.dropped_claims)} disappeared since baseline):\n"
            + "\n".join(lines)
        )

    if bundle.persisted_claims:
        lines = [
            f"  [PC] {cl.get('statement', cl['id'])}\n"
            f"       staleness={cl.get('staleness_status', '?')} · still active in both snapshots"
            for cl in bundle.persisted_claims[:10]
        ]
        diff_parts.append(
            f"[~] Persisted Claims ({len(bundle.persisted_claims)} active in both snapshots):\n"
            + "\n".join(lines)
        )

    if diff_parts:
        ctx_parts.append(
            f"=== Explicit Diff ({b_ts_s} → {c_ts_s}) ===\n\n"
            + "\n\n".join(diff_parts)
        )

    if bundle.claim_evolution_records:
        ctx_parts.append("=== Claim Evolution Records (semantic trajectory) ===")
        for i, evo in enumerate(bundle.claim_evolution_records[:20], 1):
            ctx_parts.append(
                f"[EvoRecord-{i}] relation={evo.get('relation_type', '?')} · "
                f"created={evo.get('created_at', '')}\n"
                f"  reason={evo.get('reason', '')}"
            )

    if bundle.intermediate_snapshots:
        ctx_parts.append("=== Intermediate Snapshots (T2 … TN-1) ===")
        for snap in bundle.intermediate_snapshots:
            ts = snap.get("window_end") or snap.get("created_at", "")
            ctx_parts.append(f"[Snapshot · {ts}]\n{snap['summary_text']}")

    if bundle.snapshot_deltas:
        ctx_parts.append("=== Snapshot Deltas (aggregate change signals) ===")
        for d in reversed(bundle.snapshot_deltas):
            ctx_parts.append(
                f"Delta {d['id']} · {d.get('from_snapshot_id')} → {d.get('to_snapshot_id')}\n"
                f"  {d.get('change_summary', '')}"
            )

    if bundle.evidence_sets:
        ctx_parts.append("=== Evidence Sets ===")
        for i, ev in enumerate(bundle.evidence_sets, 1):
            ctx_parts.append(
                f"EvidenceRef {i}: {ev['title']}\n"
                f"  Type={ev.get('evidence_type', '?')} · Stance={ev.get('stance', '?')}\n"
                f"  {ev.get('summary', '')}"
            )

    return "\n\n".join(ctx_parts)


# ─────────────────────────────────────────────────────────────────────────────
# Stage B: Extractor helpers
# ─────────────────────────────────────────────────────────────────────────────

def _build_extractor_user_message(
    bundle: EvolutionFactBundle,
    citations: list[CitationItem],
) -> str:
    """Build the focused user message for the extractor (Stage B) LLM call.

    Ordering is designed to direct extractor attention first to the
    high-signal diff, then to context events for event_transitions synthesis,
    then to secondary reference information.

    1. Signal Tier + time span
    2. Context Events (from citation catalog — used for event_transitions synthesis)
    3. New / Resolved events (structural changes)
    4. New Claims [+] (primary diff signal)
    5. Dropped Claims [-] (primary diff signal)
    6. Claim Evolution Records (semantic signal)
    7. Evidence Sets (supporting evidence)
    8. Citation Catalog
    9. Instruction reminder
    """
    b_ts = str(
        (bundle.baseline_snapshot or {}).get("window_end")
        or (bundle.baseline_snapshot or {}).get("created_at", "")
    )
    c_ts = str(
        (bundle.current_snapshot or {}).get("window_end")
        or (bundle.current_snapshot or {}).get("created_at", "")
    )
    parts: list[str] = [
        f"Current UTC time: {datetime.now(timezone.utc).isoformat()}",
        f"Signal Tier: {bundle.tier.upper()}",
        f"Time span: {b_ts[:19]} → {c_ts[:19]}",
    ]

    # Context Events from citation catalog — provide framing events so extractor
    # can synthesize "reframed" event_transitions when no new/resolved events exist
    event_citations = [c for c in citations if c.get("type") == "event"]
    if event_citations:
        parts.append("=== Context Events (framing this period) ===")
        for c in event_citations[:8]:
            parts.append(f"  [{c['id']}] {c['title']}")
        if not bundle.new_events and not bundle.resolved_events:
            parts.append(
                "NOTE: No new or resolved events this period. "
                "Use the Context Events above to synthesize 'reframed' event_transitions "
                "that describe how these events are being newly interpreted by the emerging claims."
            )

    if bundle.new_events:
        parts.append("=== New Events [+] ===")
        for i, ev in enumerate(bundle.new_events[:10]):
            parts.append(
                f"[NE-{i}] id={ev['id']} title={ev.get('title', '')}\n"
                f"  first_seen={ev.get('first_seen_at', '')} "
                f"last_seen={ev.get('last_seen_at', '')}\n"
                f"  summary: {str(ev.get('summary', '') or '')[:200]}"
            )

    if bundle.resolved_events:
        parts.append("=== Resolved Events [-] ===")
        for i, ev in enumerate(bundle.resolved_events[:10]):
            parts.append(
                f"[RE-{i}] id={ev['id']} title={ev.get('title', '')}\n"
                f"  summary: {str(ev.get('summary', '') or '')[:180]}"
            )

    if bundle.new_claims:
        parts.append("=== New Claims [+] ===")
        for i, cl in enumerate(bundle.new_claims[:12]):
            parts.append(
                f"[NC-{i}] id={cl['id']} "
                f"kind={cl.get('claim_type', '?')} "
                f"staleness={cl.get('staleness_status', '?')}\n"
                f"  statement: {cl.get('statement', '')}\n"
                f"  context: {str(cl.get('summary', '') or '')[:180]}"
            )

    if bundle.dropped_claims:
        parts.append("=== Dropped Claims [-] ===")
        for i, cl in enumerate(bundle.dropped_claims[:12]):
            parts.append(
                f"[DC-{i}] id={cl['id']} kind={cl.get('claim_type', '?')}\n"
                f"  statement: {cl.get('statement', '')}"
            )

    if bundle.persisted_claims:
        parts.append("=== Persisted Claims [~] ===")
        for i, cl in enumerate(bundle.persisted_claims[:8]):
            parts.append(
                f"[PC-{i}] id={cl['id']} "
                f"staleness={cl.get('staleness_status', '?')}\n"
                f"  statement: {cl.get('statement', '')}"
            )

    if bundle.claim_evolution_records:
        parts.append("=== Claim Evolution Records ===")
        for i, evo in enumerate(bundle.claim_evolution_records[:15]):
            parts.append(
                f"[CE-{i}] relation={evo.get('relation_type', '?')} "
                f"claim_id={evo.get('claim_id', '')} "
                f"prev_claim_id={evo.get('previous_claim_id', '')}\n"
                f"  reason: {evo.get('reason', '')}"
            )

    if bundle.evidence_sets:
        parts.append("=== Evidence Sets ===")
        for i, ev in enumerate(bundle.evidence_sets[:8]):
            parts.append(
                f"[ES-{i}] {ev['title']} "
                f"type={ev.get('evidence_type', '?')} "
                f"stance={ev.get('stance', '?')}\n"
                f"  {ev.get('summary', '')}"
            )

    parts.append(_build_citation_prompt(citations))
    parts.append(
        "TASK: Follow the 4-step process in your system prompt.\n"
        "Step 1: Group claim shifts into 3-5 top_changes (required).\n"
        "Step 2: Fill event_transitions — synthesize 'reframed' entries from Context Events if no [NE-N]/[RE-N] exist.\n"
        "Step 3: Fill claim_trajectories (priority claims only, max 8).\n"
        "Step 4: Fill strategic_implications (max 3, must reference top_changes change_ids).\n"
        "Output ONLY the JSON object, no other text."
    )
    return "\n\n".join(parts)


def _build_rule_based_diff_facts(
    bundle: EvolutionFactBundle,
    valid_citation_ids: set[str],
) -> DiffFacts:
    """Construct DiffFacts directly from the bundle without an LLM call.

    Used as (a) a fallback when the extractor LLM returns invalid output,
    and (b) the primary path for the provisional tier to avoid an extra LLM
    call on sparse data.

    Produces simplified top_changes by bucketing all emerged/dropped claims
    into two aggregate entries so the narrator always has top_changes to work
    from, even without an LLM call.
    """
    event_transitions: list[dict] = []
    for i, ev in enumerate(bundle.new_events[:10]):
        event_transitions.append({
            "change_id": f"EV{i+1}",
            "priority": 1,
            "narrative_role": "event_shift",
            "kind": "emerged",
            "entity_id": ev["id"],
            "title": ev.get("title", ""),
            "statement": str(ev.get("summary", "") or "")[:200] or ev.get("title", ""),
            "citation_ids": [],
            "derived_from_change_ids": [],
        })
    for i, ev in enumerate(bundle.resolved_events[:10]):
        event_transitions.append({
            "change_id": f"EV{len(bundle.new_events)+i+1}",
            "priority": 1,
            "narrative_role": "event_shift",
            "kind": "resolved",
            "entity_id": ev["id"],
            "title": ev.get("title", ""),
            "statement": str(ev.get("summary", "") or "")[:180] or ev.get("title", ""),
            "citation_ids": [],
            "derived_from_change_ids": [],
        })

    claim_trajectories: list[dict] = []
    cl_idx = 1
    for cl in bundle.new_claims[:8]:
        claim_trajectories.append({
            "change_id": f"CL{cl_idx}",
            "priority": 1,
            "narrative_role": "claim_shift",
            "kind": "emerged",
            "entity_id": cl["id"],
            "statement": cl.get("statement", ""),
            "context": str(cl.get("summary", "") or "")[:180],
            "citation_ids": [],
            "supported_by_event_ids": [],
        })
        cl_idx += 1
    for cl in bundle.dropped_claims[:8]:
        claim_trajectories.append({
            "change_id": f"CL{cl_idx}",
            "priority": 2,
            "narrative_role": "claim_shift",
            "kind": "dropped",
            "entity_id": cl["id"],
            "statement": cl.get("statement", ""),
            "context": "",
            "citation_ids": [],
            "supported_by_event_ids": [],
        })
        cl_idx += 1
    for evo in bundle.claim_evolution_records[:10]:
        rel = evo.get("relation_type", "")
        if rel in {"strengthened", "weakened", "supersedes"}:
            kind = (
                "strengthened" if rel == "strengthened"
                else ("weakened" if rel == "weakened" else "dropped")
            )
            claim_trajectories.append({
                "change_id": f"CL{cl_idx}",
                "priority": 1,
                "narrative_role": "claim_shift",
                "kind": kind,
                "entity_id": evo.get("claim_id", ""),
                "statement": evo.get("reason", ""),
                "context": evo.get("reason", ""),
                "citation_ids": [],
                "supported_by_event_ids": [],
            })
            cl_idx += 1

    # Build simplified top_changes so narrator always has high-level anchors
    top_changes: list[dict] = []
    if bundle.new_claims:
        top_changes.append({
            "change_id": "TC1",
            "priority": 1,
            "entity_type": "claim_cluster",
            "novelty": "emerged_cluster",
            "narrative_role": "observed_change",
            "statement": (
                f"{len(bundle.new_claims)} new claim(s) entered monitoring: "
                + "; ".join(
                    cl.get("statement", "")[:80]
                    for cl in bundle.new_claims[:3]
                )
            ),
            "context": "New assertions entered this period's snapshot.",
            "citation_ids": [],
            "source_entity_ids": [f"CL{i+1}" for i in range(min(len(bundle.new_claims), 8))],
        })
    if bundle.dropped_claims:
        top_changes.append({
            "change_id": "TC2",
            "priority": 2,
            "entity_type": "claim_cluster",
            "novelty": "resolved_cluster",
            "narrative_role": "observed_change",
            "statement": (
                f"{len(bundle.dropped_claims)} claim(s) dropped from monitoring: "
                + "; ".join(
                    cl.get("statement", "")[:80]
                    for cl in bundle.dropped_claims[:3]
                )
            ),
            "context": "These assertions stopped appearing in recent snapshots.",
            "citation_ids": [],
            "source_entity_ids": [],
        })

    return DiffFacts(
        top_changes=top_changes,
        event_transitions=event_transitions,
        claim_trajectories=claim_trajectories,
        strategic_implications=[],
        validation_errors=[],
        raw_extractor_hash="",
    )


def _extract_diff_facts_llm(
    bundle: EvolutionFactBundle,
    citations: list[CitationItem],
) -> tuple[DiffFacts, dict]:
    """Call the extractor LLM and return (DiffFacts, stage_facts_diagnostics).

    Falls back to rule-based DiffFacts if the LLM returns invalid JSON or
    empty facts despite non-empty diff signals in the bundle.
    """
    user_msg = _build_extractor_user_message(bundle, citations)
    raw = llm_chat(
        [
            {"role": "system", "content": EVOLUTION_EXTRACTOR_SYSTEM},
            {"role": "user", "content": user_msg},
        ],
        temperature=0.2,
    )
    raw_hash = hashlib.md5(raw.encode()).hexdigest()[:8]
    validation_errors: list[str] = []

    parsed: dict = {}
    try:
        text = raw.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(
                ln for ln in lines if not ln.strip().startswith("```")
            ).strip()
        parsed = json.loads(text)
    except (json.JSONDecodeError, ValueError) as exc:
        validation_errors.append(f"JSON parse error: {exc}")

    valid_ids = {c["id"] for c in citations}

    def _clean_cits(ids: object) -> list[str]:
        if not isinstance(ids, list):
            return []
        return [cid for cid in ids if isinstance(cid, str) and cid in valid_ids]

    if validation_errors:
        diff_facts = _build_rule_based_diff_facts(bundle, valid_ids)
        diff_facts.validation_errors = validation_errors
        diff_facts.raw_extractor_hash = raw_hash
    else:
        def _clean_str_list(val: object) -> list[str]:
            if not isinstance(val, list):
                return []
            return [s for s in val if isinstance(s, str)]

        top_changes = [
            {
                "change_id": item.get("change_id", ""),
                "priority": item.get("priority", 1),
                "entity_type": item.get("entity_type", ""),
                "novelty": item.get("novelty", ""),
                "narrative_role": item.get("narrative_role", "observed_change"),
                "statement": item.get("statement", ""),
                "context": item.get("context", ""),
                "citation_ids": _clean_cits(item.get("citation_ids", [])),
                "source_entity_ids": _clean_str_list(item.get("source_entity_ids", [])),
            }
            for item in (parsed.get("top_changes") or [])
            if isinstance(item, dict)
        ]
        event_transitions = [
            {
                "change_id": item.get("change_id", ""),
                "priority": item.get("priority", 1),
                "narrative_role": item.get("narrative_role", "event_shift"),
                "kind": item.get("kind", ""),
                "entity_id": item.get("entity_id", ""),
                "title": item.get("title", ""),
                "statement": item.get("statement", ""),
                "citation_ids": _clean_cits(item.get("citation_ids", [])),
                "derived_from_change_ids": _clean_str_list(item.get("derived_from_change_ids", [])),
            }
            for item in (parsed.get("event_transitions") or [])
            if isinstance(item, dict)
        ]
        claim_trajectories = [
            {
                "change_id": item.get("change_id", ""),
                "priority": item.get("priority", 1),
                "narrative_role": item.get("narrative_role", "claim_shift"),
                "kind": item.get("kind", ""),
                "entity_id": item.get("entity_id", ""),
                "statement": item.get("statement", ""),
                "context": item.get("context", ""),
                "citation_ids": _clean_cits(item.get("citation_ids", [])),
                "supported_by_event_ids": _clean_str_list(item.get("supported_by_event_ids", [])),
            }
            for item in (parsed.get("claim_trajectories") or [])
            if isinstance(item, dict)
        ]
        strategic_implications = [
            {
                "change_id": item.get("change_id", ""),
                "narrative_role": item.get("narrative_role", "implication"),
                "statement": item.get("statement", ""),
                "derived_from_change_ids": _clean_str_list(item.get("derived_from_change_ids", [])),
                "citation_ids": _clean_cits(item.get("citation_ids", [])),
            }
            for item in (parsed.get("strategic_implications") or [])
            if isinstance(item, dict)
        ]

        # If extractor returned no top_changes, synthesize from rule-based
        if not top_changes and (claim_trajectories or event_transitions):
            rb = _build_rule_based_diff_facts(bundle, valid_ids)
            top_changes = rb.top_changes

        diff_facts = DiffFacts(
            top_changes=top_changes,
            event_transitions=event_transitions,
            claim_trajectories=claim_trajectories,
            strategic_implications=strategic_implications,
            validation_errors=[],
            raw_extractor_hash=raw_hash,
        )

    # If LLM returned empty facts despite non-empty diff, fall back to rule-based
    if not diff_facts.event_transitions and not diff_facts.claim_trajectories:
        has_diff = bool(
            bundle.new_events or bundle.resolved_events
            or bundle.new_claims or bundle.dropped_claims
        )
        if has_diff:
            fallback = _build_rule_based_diff_facts(bundle, valid_ids)
            diff_facts.event_transitions = fallback.event_transitions
            diff_facts.claim_trajectories = fallback.claim_trajectories
            diff_facts.validation_errors.append(
                "Empty LLM facts despite non-empty diff; applied rule-based fallback"
            )

    stage_facts_diag = _collect_stage_facts_diagnostics(diff_facts)
    stage_facts_diag["raw_extractor_length"] = len(raw)
    return diff_facts, stage_facts_diag


# ─────────────────────────────────────────────────────────────────────────────
# Stage C: Narrator helpers
# ─────────────────────────────────────────────────────────────────────────────

def _build_narrator_user_message(
    diff_facts: DiffFacts,
    citations: list[CitationItem],
    bundle: EvolutionFactBundle,
    tier: str,
) -> str:
    """Build the user message for the narrator (Stage C) LLM call.

    Passes DiffFacts v2 structure to the narrator, with top_changes explicitly
    separated so the narrator can use them for Section 1 without having to
    re-derive them from the claim lists.

    The narrator does NOT receive full snapshot prose — only structured facts
    and a brief reference context for wording inspiration.
    """
    facts_payload = {
        "top_changes": diff_facts.top_changes,
        "event_transitions": diff_facts.event_transitions,
        "claim_trajectories": diff_facts.claim_trajectories,
        "strategic_implications": diff_facts.strategic_implications,
    }

    tier_note = (
        "FULL — grounded facts are available. "
        "Write specifically from [Extracted Change Facts] below."
        if tier == "full"
        else (
            "PROVISIONAL — diff signals are minimal. "
            "Write concisely and explicitly acknowledge limited evidence."
        )
    )

    ref_parts: list[str] = []
    if bundle.baseline_snapshot:
        b_ts = str(
            bundle.baseline_snapshot.get("window_end")
            or bundle.baseline_snapshot.get("created_at", "")
        )
        b_summary = str(bundle.baseline_snapshot.get("summary_text", ""))[:400]
        ref_parts.append(f"Baseline [{b_ts[:19]}]: {b_summary}")
    if bundle.current_snapshot:
        c_ts = str(
            bundle.current_snapshot.get("window_end")
            or bundle.current_snapshot.get("created_at", "")
        )
        c_summary = str(bundle.current_snapshot.get("summary_text", ""))[:400]
        ref_parts.append(f"Current [{c_ts[:19]}]: {c_summary}")
    rc = bundle.research_context
    if rc.get("brief"):
        ref_parts.append(f"Research Direction: {rc['brief']}")

    parts: list[str] = [
        f"Current UTC time: {datetime.now(timezone.utc).isoformat()}",
        f"Signal Tier: {tier_note}",
        (
            "=== Extracted Change Facts ===\n"
            + json.dumps(facts_payload, ensure_ascii=False, indent=2)
        ),
        _build_citation_prompt(citations),
    ]
    if ref_parts:
        parts.append(
            "=== Reference Context (wording only — do not introduce new facts) ===\n"
            + "\n\n".join(ref_parts)
        )
    parts.append(
        "Write the evolution report following the section contracts in your system prompt. "
        "Section 1 uses top_changes only. "
        "Section 2 uses event_transitions only. "
        "Section 3 uses claim_trajectories (priority=1) only. "
        "Section 4 uses strategic_implications only. "
        "Do NOT repeat content between sections."
    )
    return "\n\n".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# Multi-stage diagnostics
# ─────────────────────────────────────────────────────────────────────────────

def _collect_stage_context_diagnostics(
    bundle: EvolutionFactBundle,
    citations: list[CitationItem],
) -> dict:
    """Stage A diagnostics: context assembly quality."""
    return {
        "tier": bundle.tier,
        "snapshot_count": (
            (1 if bundle.baseline_snapshot else 0)
            + (1 if bundle.current_snapshot else 0)
            + len(bundle.intermediate_snapshots)
        ),
        "new_events_count": len(bundle.new_events),
        "resolved_events_count": len(bundle.resolved_events),
        "new_claims_count": len(bundle.new_claims),
        "dropped_claims_count": len(bundle.dropped_claims),
        "persisted_claims_count": len(bundle.persisted_claims),
        "claim_evolution_count": len(bundle.claim_evolution_records),
        "evidence_sets_count": len(bundle.evidence_sets),
        "citation_ids_available": [c["id"] for c in citations],
    }


def _collect_stage_facts_diagnostics(diff_facts: DiffFacts) -> dict:
    """Stage B diagnostics: extractor output quality."""
    # Count priority-1 claim trajectories
    p1_claims = sum(
        1 for ct in diff_facts.claim_trajectories
        if ct.get("priority", 1) == 1
    )
    # Count claim trajectories with event bindings
    bound_claims = sum(
        1 for ct in diff_facts.claim_trajectories
        if ct.get("supported_by_event_ids")
    )
    # Count event transitions that are synthesized (kind=reframed)
    reframed_events = sum(
        1 for et in diff_facts.event_transitions
        if et.get("kind") == "reframed"
    )
    return {
        "raw_extractor_hash": diff_facts.raw_extractor_hash,
        "validation_errors": list(diff_facts.validation_errors),
        "is_fallback": bool(diff_facts.validation_errors),
        "top_changes_count": len(diff_facts.top_changes),
        "event_transitions_count": len(diff_facts.event_transitions),
        "event_transitions_reframed": reframed_events,
        "claim_trajectories_count": len(diff_facts.claim_trajectories),
        "claim_trajectories_priority1": p1_claims,
        "claim_trajectories_bound_to_events": bound_claims,
        "strategic_implications_count": len(diff_facts.strategic_implications),
    }


def _assess_evolution_adequacy(
    bundle: EvolutionFactBundle,
    stage_facts_diag: dict,
) -> tuple[bool, str | None]:
    """Decide whether there is enough structured signal to justify a narrative.

    Returns (should_emit, suppression_reason).
    If should_emit is False, the caller MUST NOT invoke the narrator or persist
    a final evolution_report artifact.

    Rules (in order):
    1. Provisional tier with zero diff signals → suppress.
    2. After Stage B, if all three fact dimensions are zero → suppress.
    3. Full tier where extractor failed AND rule-based fallback is also empty → suppress.
    """
    tier = bundle.tier

    # Rule 1 — provisional with no diff signals at all
    if tier == "provisional":
        has_any_signal = bool(
            bundle.new_events
            or bundle.resolved_events
            or bundle.new_claims
            or bundle.dropped_claims
            or bundle.claim_evolution_records
        )
        if not has_any_signal:
            return False, (
                "provisional tier with no diff signals: "
                "no new/resolved events, no new/dropped claims, no claim evolution records"
            )

    # Rule 2 — all three structured fact dimensions empty
    top_changes = stage_facts_diag.get("top_changes_count", 0)
    ev_transitions = stage_facts_diag.get("event_transitions_count", 0)
    p1_claims = stage_facts_diag.get("claim_trajectories_priority1", 0)

    if top_changes == 0 and ev_transitions == 0 and p1_claims == 0:
        return False, (
            f"insufficient structured facts after Stage B "
            f"(top_changes={top_changes}, event_transitions={ev_transitions}, "
            f"p1_claims={p1_claims}) — skipping narrator"
        )

    # Rule 3 — full tier extractor failed AND even rule-based fallback produced nothing
    if tier == "full" and stage_facts_diag.get("is_fallback"):
        claim_count = stage_facts_diag.get("claim_trajectories_count", 0)
        if ev_transitions == 0 and claim_count == 0:
            return False, (
                "full tier extractor failed and rule-based fallback produced no facts — "
                "skipping narrator"
            )

    return True, None


def _collect_stage_narrative_diagnostics(
    result: str,
    diff_facts: DiffFacts,
    citations: list[CitationItem],
) -> dict:
    """Stage C diagnostics: narrative grounding and citation usage."""
    cited_in_result = list(set(_re.findall(r"\[([EA]\d+)\]", result)))

    # Measure facts grounded: check top_changes + priority-1 claim trajectories + event transitions
    entity_statements = (
        [f.get("statement", "") for f in diff_facts.top_changes]
        + [f.get("title", "") or f.get("statement", "") for f in diff_facts.event_transitions]
        + [
            f.get("statement", "")
            for f in diff_facts.claim_trajectories
            if f.get("priority", 1) == 1
        ]
    )
    grounded_count = sum(
        1
        for stmt in entity_statements[:30]
        if stmt and any(
            word.lower() in result.lower()
            for word in stmt.split()[:5]
            if len(word) > 5
        )
    )

    # Section coverage: extract text of each section
    section_texts = _re.split(r"## \d+\.", result)[1:]
    section_lengths = [len(s.strip()) for s in section_texts[:4]]
    insufficient_sections = sum(
        1 for s in section_texts[:4]
        if "insufficient evidence" in s.lower()
    )

    # Repetition detection: overlap between Section 1 and Section 3 (index 0, 2)
    section_overlap = 0
    if len(section_texts) >= 3:
        s1_words = set(w.lower() for w in section_texts[0].split() if len(w) > 6)
        s3_words = set(w.lower() for w in section_texts[2].split() if len(w) > 6)
        common = s1_words & s3_words
        if s1_words:
            section_overlap = round(len(common) / len(s1_words), 2)

    generic_check = _detect_generic_output(result=result, ctx="", citations=citations)
    return {
        "result_length": len(result),
        "result_hash": hashlib.md5(result.encode()).hexdigest()[:8],
        "citations_used": cited_in_result,
        "citations_used_count": len(cited_in_result),
        "facts_grounded_count": grounded_count,
        "facts_total_count": len(entity_statements),
        "section_lengths": section_lengths,
        "insufficient_sections": insufficient_sections,
        "section1_section3_overlap": section_overlap,
        "generic_check": generic_check,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _build_evolution_context_v2(topic_id: int) -> tuple[str | None, str | None, str]:
    """Backward-compatible wrapper around the new bundle-based pipeline.

    Returns (context_string, error_message_if_skip, tier) to keep existing
    callers (tests, debug scripts) working without modification.
    """
    bundle = _load_evolution_fact_bundle(topic_id)
    if bundle.tier == "skip":
        return None, bundle.error, "skip"
    return _render_evolution_debug_context(bundle), None, bundle.tier


# ─────────────────────────────────────────────────────────────────────────────
# LLM prompts
# ─────────────────────────────────────────────────────────────────────────────

EVOLUTION_EXTRACTOR_SYSTEM = """You are a temporal-change analyst. Your ONLY task is to extract structured change facts from the provided snapshot diff data and organize them into a narrative-ready skeleton.

Output a single JSON object. No prose paragraphs. No markdown code fences around the JSON.

## STEP 1 — Identify top_changes first (most important step)

Before filling other arrays, scan ALL [NC-N] and [DC-N] items and group them into 3-5 thematic clusters representing the most narratively significant shifts. Each cluster becomes one entry in top_changes.

Example: If NC-0, NC-6, NC-11 all describe US-Iran diplomatic escalation, group them as one top_change statement.

## STEP 2 — Fill event_transitions

If [NE-N] items exist → map each to an "emerged" event_transition.
If [RE-N] items exist → map each to a "resolved" event_transition.
If NO [NE-N] or [RE-N] items exist, but [Context Events] are provided:
  → Create 1-3 "reframed" event_transitions describing how the existing events are being newly interpreted based on the emerging claims. Use the event titles from [Context Events] and cite them properly.
  → Do NOT leave event_transitions empty if there are context events and meaningful claim shifts.

## STEP 3 — Fill claim_trajectories (priority claims only)

Only include the claims that support the top_changes (priority 1). Secondary claims (priority 2) may be included but kept brief. Assign supported_by_event_ids to connect each claim to the relevant event_transitions.

## STEP 4 — Fill strategic_implications

Derive at most 3 implications. Each MUST reference specific change_ids from top_changes in derived_from_change_ids.

## JSON Schema:
{
  "top_changes": [
    {
      "change_id": "TC1",
      "priority": 1,
      "entity_type": "claim_cluster" | "event" | "cross-cutting",
      "novelty": "emerged_cluster" | "resolved_cluster" | "intensified" | "retreated",
      "narrative_role": "observed_change",
      "statement": "<1-2 sentence thematic description of what shifted>",
      "context": "<why this shift matters>",
      "citation_ids": ["E1", "A2"],
      "source_entity_ids": ["NC-0", "NC-6"]
    }
  ],
  "event_transitions": [
    {
      "change_id": "EV1",
      "priority": 1,
      "narrative_role": "event_shift",
      "kind": "emerged" | "resolved" | "reframed",
      "entity_id": "<event id from input or 'synthesized'>",
      "title": "<event title>",
      "statement": "<1-2 sentence factual description of what this event represents or how it was reframed>",
      "citation_ids": ["E1"],
      "derived_from_change_ids": ["TC1"]
    }
  ],
  "claim_trajectories": [
    {
      "change_id": "CL1",
      "priority": 1,
      "narrative_role": "claim_shift",
      "kind": "emerged" | "dropped" | "strengthened" | "weakened",
      "entity_id": "<claim id from input>",
      "statement": "<exact or paraphrased claim statement with citation>",
      "context": "<brief explanation of direction change>",
      "citation_ids": ["A3"],
      "supported_by_event_ids": ["EV1"]
    }
  ],
  "strategic_implications": [
    {
      "change_id": "SI1",
      "narrative_role": "implication",
      "statement": "<1-2 sentence structural implication>",
      "derived_from_change_ids": ["TC1", "TC2"],
      "citation_ids": ["A8"]
    }
  ]
}

Rules:
- ONLY use citation IDs from the [Citation Catalog]. If no valid citation, use [].
- Do NOT introduce entity names not present in the input data.
- Keep statements concise and factual. No generic summaries.
- top_changes should reflect genuine narrative clusters (aim for 1-3). If the diff signals are too sparse to form even ONE coherent change cluster, return an EMPTY top_changes array. Do NOT invent or pad clusters.
- event_transitions must NOT be empty when [Context Events] are provided and claims shifted significantly.
- claim_trajectories: include priority=1 claims only (those that support a top_change). Limit to 8 total.
- strategic_implications: at most 3; each must have derived_from_change_ids pointing to top_changes change_ids.
"""


EVOLUTION_NARRATOR_SYSTEM = """You are a senior analyst writing an evolution report for a monitored domain.

Your ONLY authoritative input is [Extracted Change Facts] in the user message.
[Reference Context] is provided only for wording inspiration — do NOT use it to introduce new facts or entities.

## Section Contracts (STRICTLY enforced)

### ## 1. Observed Changes
SOURCE: top_changes array ONLY.
WRITE: For each top_change (priority order), 2 sentences: (1) state the thematic shift and direction (intensified/retreated/emerged/resolved), citing at least one source; (2) explain why this matters or what structural force it reflects. Do not merge multiple changes into one sentence.
DO NOT: list individual claim statements or event titles here.
DO NOT: repeat content from this section in Section 3.

### ## 2. Event-Level Shifts
SOURCE: event_transitions array ONLY.
WRITE: For each event_transition, one paragraph. Name the event/title explicitly. Explain whether it emerged, resolved, or was reframed. State its significance to this monitoring period.
IF event_transitions is empty: write "No discrete event-level transitions this period." (one sentence only, do NOT say "Insufficient evidence")
DO NOT: repeat content from this section in Section 1.

### ## 3. Claim Trajectories
SOURCE: claim_trajectories with priority=1 ONLY.
WRITE: For each priority-1 claim, 2 sentences: (1) state the direction (emerged/dropped/strengthened/weakened) and cite the evidence; (2) explain what this shift means for the monitored domain — connect to supported_by_event_ids if available. Include citations in both sentences where applicable.
DO NOT: repeat thematic summaries from Section 1. Be specific and granular here.
DO NOT: include priority=2 claims unless this section would otherwise be empty.

### ## 4. Strategic Implications
SOURCE: strategic_implications array ONLY. Each implication must have derived_from_change_ids.
WRITE: 1-3 short paragraphs, each tracing a structural consequence back to specific top_changes or claim_trajectories. Use citations.
IF strategic_implications is empty: write one sentence noting the changes are too preliminary for structural conclusions.

## Universal Rules
- Do NOT invent facts, entities, or claims not present in [Extracted Change Facts].
- Do NOT reproduce content across sections. Each section must contribute new information.
- ONLY cite IDs from the [Citation Catalog]. Never invent citation IDs.
- Write in the same language as the provided data.
- Prioritize specificity over completeness. If a section has thin facts, write less — not generic prose.
- Do NOT write internal DiffFacts change_ids (e.g. TC1, TC2, EV1, EV2, CL1, SI1) in the narrative text. These are structural labels only — they are not citable sources.
- When citing sources from the [Citation Catalog], ALWAYS use square brackets: write [E1] not E1 or (E1). Place citations at the end of a clause, not mid-phrase.
"""


def generate_evolution_report_sync(topic_id: int) -> str:
    """Two-stage evolution report generation.

    Stage A: Load EvolutionFactBundle from DB and assess tier.
    Stage B (full tier only): LLM extractor produces structured DiffFacts JSON.
    Stage C: LLM narrator writes the final report from DiffFacts only.
    """
    # ── Stage A: Assemble fact bundle ─────────────────────────────────────
    bundle = _load_evolution_fact_bundle(topic_id)
    if bundle.tier == "skip":
        return bundle.error  # type: ignore[return-value]

    snapshots = get_temporal_snapshots(topic_id, window_type="daily", limit=6)
    oldest_ts = (
        snapshots[-1].get("window_end") or snapshots[-1].get("created_at", "")
        if snapshots else ""
    )
    newest_ts = (
        snapshots[0].get("window_end") or snapshots[0].get("created_at", "")
        if snapshots else ""
    )
    citations = _build_evolution_citation_catalog(topic_id, oldest_ts, newest_ts)
    stage_context_diag = _collect_stage_context_diagnostics(bundle, citations)

    print(
        f"[evolution] topic={topic_id} tier={bundle.tier} "
        f"new_events={stage_context_diag['new_events_count']} "
        f"new_claims={stage_context_diag['new_claims_count']} "
        f"citations={len(citations)}"
    )

    # ── Stage B: Extract DiffFacts ────────────────────────────────────────
    if bundle.tier == "full":
        diff_facts, stage_facts_diag = _extract_diff_facts_llm(bundle, citations)
        if stage_facts_diag.get("is_fallback"):
            print(
                f"[evolution] topic={topic_id} ⚠ extractor fallback — "
                f"errors={stage_facts_diag['validation_errors']}"
            )
    else:
        # Provisional: build rule-based facts, skip the extractor LLM call
        valid_ids = {c["id"] for c in citations}
        diff_facts = _build_rule_based_diff_facts(bundle, valid_ids)
        stage_facts_diag = _collect_stage_facts_diagnostics(diff_facts)

    # ── Adequacy Gate: block narrator if data is too thin ─────────────────
    should_emit, suppression_reason = _assess_evolution_adequacy(bundle, stage_facts_diag)
    if not should_emit:
        print(
            f"[evolution] topic={topic_id} ⊘ suppressed — {suppression_reason} | "
            f"tier={bundle.tier} "
            f"new_ev={stage_context_diag['new_events_count']} "
            f"new_cl={stage_context_diag['new_claims_count']} "
            f"claim_evo={stage_context_diag['claim_evolution_count']} "
            f"top_changes={stage_facts_diag['top_changes_count']} "
            f"ev_trans={stage_facts_diag['event_transitions_count']} "
            f"p1_claims={stage_facts_diag['claim_trajectories_priority1']}"
        )
        return suppression_reason  # type: ignore[return-value]

    # ── Stage C: Generate narrative ───────────────────────────────────────
    narrator_user = _build_narrator_user_message(diff_facts, citations, bundle, bundle.tier)
    raw_narrative = llm_chat(
        [
            {"role": "system", "content": EVOLUTION_NARRATOR_SYSTEM},
            {"role": "user", "content": narrator_user},
        ],
        temperature=0.45,
    )
    result = _normalize_citations(raw_narrative, citations)
    stage_narrative_diag = _collect_stage_narrative_diagnostics(result, diff_facts, citations)

    if stage_narrative_diag["generic_check"]["is_generic"]:
        print(
            f"[evolution] topic={topic_id} ⚠ generic narrative — "
            f"flags={stage_narrative_diag['generic_check']['flags']}"
        )
    else:
        print(
            f"[evolution] topic={topic_id} "
            f"top_changes={stage_facts_diag['top_changes_count']} "
            f"ev={stage_facts_diag['event_transitions_count']}(reframed={stage_facts_diag['event_transitions_reframed']}) "
            f"cl={stage_facts_diag['claim_trajectories_count']}(p1={stage_facts_diag['claim_trajectories_priority1']}) "
            f"narrative_len={stage_narrative_diag['result_length']}c "
            f"grounded={stage_narrative_diag['facts_grounded_count']}/"
            f"{stage_narrative_diag['facts_total_count']} "
            f"overlap={stage_narrative_diag['section1_section3_overlap']}"
        )

    artifact_id = replace_synthesis_artifact(
        topic_id=topic_id,
        artifact_type="evolution_report",
        title="Evolution Report",
        content=result,
        status="final",
        metadata={
            "source": "two_stage_evolution",
            "citations": citations,
            "diagnostics": {
                "stage_context": stage_context_diag,
                "stage_facts": stage_facts_diag,
                "stage_narrative": stage_narrative_diag,
            },
        },
        source_snapshot_ids=[row["id"] for row in snapshots],
        source_delta_ids=[row["id"] for row in bundle.snapshot_deltas],
        source_claim_ids=[],
    )
    add_artifact_document(
        artifact_id,
        result,
        {
            "topic_id": str(topic_id),
            "artifact_type": "evolution_report",
            "status": "final",
            "generated_at": stage_narrative_diag["generated_at"],
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
