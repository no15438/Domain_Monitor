"""
Data Pipeline — Recall -> Cluster -> Score -> Enrich -> Store

  Stage 1  COLLECT       Cheap, fast, cast wide net (no LLM) — parallel HTTP
  Stage 2  URL DEDUP     Remove exact URL duplicates
  Stage 3  RELEVANCE     Topic keyword gate (no LLM)
  Stage 4  EVENT CLUSTER Group similar articles into events
  Stage 5  CANONICAL     Pick best representative per event (multi-signal scoring)
  Stage 6  ENRICH        LLM summarize/tag/sentiment (batch: 4 articles/call)
  Stage 7  STORE         SQLite + ChromaDB
"""

import json
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

log = logging.getLogger("pipeline")


def _normalize_date(raw: str) -> str:
    """Convert any date string to ISO 8601 (YYYY-MM-DD HH:MM:SS) for consistent SQLite sorting."""
    if not raw:
        return ""
    for fmt in (
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%a, %d %b %Y %H:%M:%S %z",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            dt = datetime.strptime(raw, fmt)
            if dt.tzinfo:
                dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            continue
    return raw

from llm_client import llm_chat
from database import (
    add_claim_evolution,
    get_recent_urls,
    get_recent_article_stubs,
    get_recent_event_stubs,
    get_claims_v2,
    insert_article,
    insert_raw_news,
    get_keywords,
    get_topics,
    get_topic_feeds,
    replace_event_sources,
    update_article_event_fields,
    upsert_claim,
    upsert_evidence_set,
    upsert_event,
)
from claim_lifecycle import evaluate_claim_lifecycle
from vector_store import add_claim_document, add_evidence_document, add_event_document
from relevance import (
    normalize_url,
    dedup_by_similarity,
    filter_by_relevance,
    cluster_by_event,
    select_representatives,
)
from config import settings

from collectors import newsapi_collector, rss_collector, googlenews_collector, eventregistry_collector

BATCH_ENRICH_PROMPT = """You are a research analyst. Analyze the following {n} articles against the research context.

=== RESEARCH CONTEXT ===
Topic: {topic_name}
Research Direction: {research_brief}
Keywords: {topic_keywords}
Key Entities: {entities}
Geographic Scope: {geographic_scope}
Sector Scope: {sector_scope}
Research Angles:
{angles}
========================

{articles_block}

Return a JSON array of exactly {n} objects, one per article, in the SAME ORDER as listed above.
Each object must have:
- "summary": 1-2 sentence summary, max 120 chars, same language as article
- "tags": array of 2-5 topic tags, same language as article
- "sentiment": "positive" | "negative" | "neutral" — from this research direction's perspective
- "importance": integer 1-10 (10 = directly addresses a key research angle)
- "topic_relevance": float 0.0-1.0
- "signal_type": short plain-language label for the evidence signal, e.g. "market signal", "policy signal", "capacity signal"
- "key_entities": array of up to 5 relevant entities
- "topic_analysis": 1 sentence on how the article relates to the research, same language
- "claims": array of 2-4 key analytical claims extracted from this article. Each claim must have:
    - "kind": "observation" | "forecast" | "trend" | "structural"
    - "statement": a concise, self-contained claim sentence (max 160 chars), same language as article
    - "summary": 1 sentence expanding on the statement (max 160 chars), same language as article
  Rules for claims:
  - Cover different analytical angles — do NOT repeat the same point with different words
  - At least one "observation" (what happened) and one forward-looking kind ("forecast" or "trend") when the article supports it
  - If the article only supports one clear claim, return 1 item (minimum 1, maximum 4)

Return ONLY a valid JSON array. No markdown fences, no explanation."""

# How many articles to send per LLM batch call.
# MLX runs inference sequentially; batching reduces call overhead dramatically.
BATCH_SIZE = 4
MAX_ENRICH = 12

# Cluster synthesis — one call per batch of clusters (only for multi-article events)
CLUSTER_SYNTHESIS_BATCH_SIZE = 8

CLUSTER_SYNTHESIS_PROMPT = """You are a research analyst creating event cards for a news monitoring system.
For each cluster below, synthesize ALL sources into ONE unified event card.

Research Context:
Topic: {topic_name}
Research Brief: {research_brief}

{clusters_block}

Return a JSON array of exactly {n} objects (SAME ORDER as clusters above).
Each object must have:
- "event_title": 10-15 word title that describes WHAT HAPPENED specifically (not generic)
- "event_summary": 2-3 sentences synthesizing key facts across ALL sources in this cluster

Write in the same language as the source articles.
Return ONLY a valid JSON array. No markdown fences, no explanation."""


def _synthesize_cluster_events(
    items: list[dict],
    context_params: dict,
) -> list[dict]:
    """Generate event-level title and summary by synthesizing all articles in each cluster.

    Takes canonical items that have _cluster_alts populated (event_size > 1).
    Returns a list of dicts (same length as items), each with keys:
      - "event_title": AI-synthesized event title
      - "event_summary": AI-synthesized multi-source summary
    Falls back to empty dict on error so callers can use article-level fallbacks.
    """
    results: list[dict] = [{} for _ in items]

    for batch_start in range(0, len(items), CLUSTER_SYNTHESIS_BATCH_SIZE):
        batch = items[batch_start: batch_start + CLUSTER_SYNTHESIS_BATCH_SIZE]

        cluster_blocks: list[str] = []
        for i, item in enumerate(batch):
            alts = item.get("_cluster_alts") or []
            title = item.get("title") or ""
            source = item.get("source") or "unknown"
            primary_line = f'Primary: "{title}" ({source})'
            alt_lines = [
                f'Also: "{alt.get("title", "")}" ({alt.get("source", "unknown")})'
                for alt in alts[:4]
                if alt.get("title")
            ]
            block = f"Cluster {i + 1} ({item.get('_event_size', 1)} sources):\n{primary_line}"
            if alt_lines:
                block += "\n" + "\n".join(alt_lines)
            cluster_blocks.append(block)

        clusters_block = "\n\n".join(cluster_blocks)
        prompt = CLUSTER_SYNTHESIS_PROMPT.format(
            n=len(batch),
            clusters_block=clusters_block,
            topic_name=context_params.get("topic_name", "General"),
            research_brief=context_params.get("research_brief", "(not specified)"),
        )

        try:
            raw = llm_chat([{"role": "user", "content": prompt}])
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
            parsed_list = json.loads(raw)
            if isinstance(parsed_list, list) and len(parsed_list) == len(batch):
                for j, synth in enumerate(parsed_list):
                    results[batch_start + j] = synth if isinstance(synth, dict) else {}
            else:
                log.warning(
                    "cluster synthesis returned %s items, expected %d — skipping",
                    len(parsed_list) if isinstance(parsed_list, list) else type(parsed_list).__name__,
                    len(batch),
                )
        except Exception as e:
            log.error("cluster synthesis LLM error: %s", e)

        log.info("cluster synthesis: processed %d cluster(s)", len(batch))

    return results


def _coerce_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _serialize_raw_news(topic_id: int, items: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for item in items:
        raw_id = item.get("_raw_news_id") or str(uuid.uuid4())
        item["_raw_news_id"] = raw_id
        rows.append(
            {
                "id": raw_id,
                "topic_id": topic_id,
                "article_id": None,
                "url": item.get("url", ""),
                "normalized_url": item.get("url", ""),
                "title": item.get("title", ""),
                "content": item.get("content", "") or "",
                "source": item.get("source", ""),
                "source_type": item.get("_source_type", ""),
                "published_at": _normalize_date(item.get("published_date", "")),
                "fetched_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                "novelty_score": _coerce_float(item.get("_source_score"), 0.0),
                "noise_score": 0.0,
                "authority_score": _coerce_float((item.get("_source_breakdown") or {}).get("authority"), 0.0),
                "freshness_state": "hot",
                "retention_until": None,
                "metadata_json": json.dumps(
                    {
                        "source_breakdown": item.get("_source_breakdown", {}),
                        "event_id": item.get("_event_id"),
                        "event_size": item.get("_event_size", 1),
                    },
                    ensure_ascii=False,
                ),
            }
        )
    return rows


def _build_claim_text(item: dict, parsed: dict) -> tuple[str, str]:
    statement = (parsed.get("topic_analysis") or parsed.get("summary") or item.get("title") or "").strip()
    summary = (parsed.get("summary") or parsed.get("topic_analysis") or item.get("title") or "").strip()
    if not statement:
        statement = item.get("title", "").strip()
    if len(statement) > 240:
        statement = statement[:237].rstrip() + "..."
    if len(summary) > 240:
        summary = summary[:237].rstrip() + "..."
    return statement, summary


def _statement_key(text: str) -> str:
    return " ".join((text or "").strip().lower().split())


# ── Stage 1: COLLECT (Recall — no LLM, parallel HTTP) ────────────


def _collect_for_keywords(keyword_list: list[str], max_per_source: int) -> list[dict]:
    """Dispatch all (keyword × source) requests in parallel using a thread pool.
    HTTP I/O is the bottleneck here; parallelism cuts wall-clock time from
    O(keywords × 3) sequential calls down to roughly one round-trip."""

    def _fetch(source: str, kw: str) -> list[dict]:
        try:
            if source == "googlenews":
                return _tag(googlenews_collector.collect(kw, max_results=max_per_source), "googlenews")
            if source == "newsapi":
                return _tag(newsapi_collector.collect(kw, max_results=max_per_source), "newsapi")
            # eventregistry
            return _tag(eventregistry_collector.collect(kw, max_events=max_per_source), "eventregistry")
        except Exception as e:
            log.warning("collect error [%s/%s]: %s", source, kw, e)
            return []

    tasks = [(src, kw) for kw in keyword_list for src in ("googlenews", "newsapi", "eventregistry")]
    raw: list[dict] = []
    # Cap workers: each task is pure network I/O, 8–12 concurrent is safe
    workers = min(len(tasks), 12)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_fetch, src, kw): (src, kw) for src, kw in tasks}
        for future in as_completed(futures):
            raw.extend(future.result())
    return raw


def _collect_rss(feed_urls: list[str]) -> list[dict]:
    items = rss_collector.collect_multiple(feed_urls, max_per_feed=30)
    return _tag(items, "rss")


def _tag(items: list[dict], source_type: str) -> list[dict]:
    for item in items:
        item["_source_type"] = source_type
    return items


# ── Stage 2: URL DEDUP (with normalization) ──────────


def _url_dedup(items: list[dict], existing_urls: set[str]) -> list[dict]:
    """Exact URL dedup using normalized URLs.

    Also rewrites item["url"] to its canonical form so downstream stages
    and the database always store a clean URL.
    """
    seen: set[str] = set()
    # Pre-normalise the existing URL set once
    norm_existing = {normalize_url(u) for u in existing_urls}
    unique: list[dict] = []
    for item in items:
        raw_url = item.get("url", "")
        if not raw_url:
            continue
        norm = normalize_url(raw_url)
        if norm in norm_existing or norm in seen:
            continue
        seen.add(norm)
        item["url"] = norm  # store canonical form
        unique.append(item)
    return unique


# ── Stage 2.5: SEMANTIC DEDUP ─────────────────────────


def _semantic_dedup(
    items: list[dict],
    existing_stubs: list[dict] | None = None,
    within_threshold: float = 0.72,
    cross_threshold: float = 0.88,
) -> list[dict]:
    """Remove near-duplicate articles using TF-IDF cosine similarity."""
    if not items:
        return items

    items = dedup_by_similarity(items, threshold=within_threshold)

    if not existing_stubs or not items:
        return items

    for s in existing_stubs:
        s["_is_existing"] = True
    combined = existing_stubs + items
    deduped = dedup_by_similarity(combined, threshold=cross_threshold)
    result = [a for a in deduped if not a.get("_is_existing")]
    for s in existing_stubs:
        s.pop("_is_existing", None)
    return result


# ── Stage 3: RELEVANCE FILTER ────────────────────────


def _relevance_filter(items: list[dict], keyword_list: list[str], min_score: float = 0.1) -> list[dict]:
    if not keyword_list:
        return items
    return filter_by_relevance(items, keyword_list, min_score=min_score)


# ── Stage 4+5: EVENT CLUSTER + CANONICAL SELECTION ───


def _parse_weights() -> dict:
    """Parse scoring_weights from config string like 'authority=0.35,coverage=0.25,...'"""
    try:
        pairs = settings.scoring_weights.split(",")
        return {k.strip(): float(v.strip()) for k, v in (p.split("=") for p in pairs)}
    except Exception:
        return {}


def _reconcile_event_id(item: dict, recent_stubs: list[dict], title_threshold: float = 0.40) -> str | None:
    """Return an existing event_id if this canonical item matches a recent event.

    Priority order:
    1. Exact canonical URL match (same story, different run)
    2. Title similarity above threshold within a 7-day window

    Returns None if no match is found, caller should fall back to item['_event_id'].
    """
    from relevance import _title_similarity, _normalize, _time_close

    item_url = (item.get("url") or "").strip()
    item_title_norm = _normalize(item.get("title") or "")
    item_date = item.get("published_date") or item.get("published_at") or ""

    for stub in recent_stubs:
        # Direct URL match
        if item_url and stub.get("canonical_url") and item_url == stub["canonical_url"]:
            return stub["id"]

        # Title similarity
        if not item_title_norm:
            continue
        stub_title_norm = _normalize(stub.get("title") or "")
        if not stub_title_norm:
            continue
        if _title_similarity(item_title_norm, stub_title_norm) >= title_threshold:
            return stub["id"]

    return None


def _cluster_and_select(items: list[dict], cluster_threshold: float | None = None) -> tuple[list[list[dict]], list[dict]]:
    """Cluster items by event, then pick best representative per cluster."""
    total = len(items)

    for idx, item in enumerate(items):
        item["_collect_idx"] = idx

    threshold = cluster_threshold if cluster_threshold is not None else settings.event_cluster_threshold
    clusters = cluster_by_event(items, title_threshold=threshold, time_window_hours=72)

    weights = _parse_weights() or None
    canonicals = select_representatives(
        clusters,
        total_collected=total,
        weights=weights,
        max_canonicals=MAX_ENRICH,
    )
    return clusters, canonicals


# ── Stage 6: ENRICH (LLM batch — only canonicals) ────────────────

_DEFAULT_PARSED = {
    "summary": "",
    "tags": [],
    "sentiment": "neutral",
    "importance": 5,
    "topic_relevance": 0.5,
    "claim_kind": "observation",
    "signal_type": "market signal",
    "key_entities": [],
    "topic_analysis": "",
}


ALLOWED_CLAIM_KINDS = {"observation", "forecast", "trend", "structural"}


def _normalize_claim_kind(value: str | None) -> str:
    candidate = (value or "").strip().lower()
    return candidate if candidate in ALLOWED_CLAIM_KINDS else "observation"


def _call_batch_llm(
    batch: list[dict],
    context_params: dict,
) -> list[dict]:
    """Send one LLM call for a batch of articles. Returns a list of parsed dicts
    (same length as batch). Falls back to defaults if parsing fails."""
    articles_block = "\n\n".join(
        f"[Article {i + 1}]\nTitle: {item['title']}\nContent: {(item.get('content') or '')[:700]}"
        for i, item in enumerate(batch)
    )
    prompt = BATCH_ENRICH_PROMPT.format(n=len(batch), articles_block=articles_block, **context_params)
    try:
        raw = llm_chat([{"role": "user", "content": prompt}])
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
        parsed_list = json.loads(raw)
        if isinstance(parsed_list, list) and len(parsed_list) == len(batch):
            return parsed_list
        log.warning("batch LLM returned %s items, expected %d — using defaults",
                    len(parsed_list) if isinstance(parsed_list, list) else type(parsed_list), len(batch))
    except Exception as e:
        log.error("batch LLM parse error: %s", e)
    # Fallback: fill with defaults (no extra LLM call — keeps MLX happy)
    return [{**_DEFAULT_PARSED, "summary": (item.get("content") or "")[:120]} for item in batch]


def _enrich_and_store(
    canonicals: list[dict],
    topic_id: int | None,
    existing_urls: set[str],
    topic_name: str = "",
    topic_keywords: list[str] | None = None,
    research_brief: str = "",
    research_config: dict | None = None,
) -> list[dict]:
    cfg = research_config or {}
    context_params = {
        "topic_name": topic_name or "General",
        "research_brief": research_brief or "(not specified)",
        "topic_keywords": ", ".join(topic_keywords) if topic_keywords else "general",
        "entities": ", ".join(cfg.get("entities", [])) or "(not specified)",
        "geographic_scope": ", ".join(cfg.get("geographic_scope", [])) or "(not specified)",
        "sector_scope": ", ".join(cfg.get("sector_scope", [])) or "(not specified)",
        "angles": "\n".join(
            f"  {i+1}. {a}" for i, a in enumerate(cfg.get("angles", []))
        ) or "  (not specified)",
    }

    # Load recent event stubs once per _enrich_and_store call for reconciliation
    recent_event_stubs: list[dict] = (
        get_recent_event_stubs(topic_id, days=7) if topic_id is not None else []
    )
    # Snapshot IDs of events that existed BEFORE this batch — used to detect brand-new events
    existing_event_ids_before_batch: set[str] = {s["id"] for s in recent_event_stubs}

    # Filter out already-seen URLs first so we only enrich genuinely new articles
    new_items: list[dict] = []
    for item in canonicals:
        if item["url"] in existing_urls:
            # Article already in DB — keep event_size in sync so the badge
            # stays accurate even if the cluster size grew since first insert.
            # Also reconcile the event_id in case the cluster seed changed.
            reconciled = _reconcile_event_id(item, recent_event_stubs)
            effective_event_id = reconciled or item.get("_event_id", "")
            update_article_event_fields(
                url=item["url"],
                event_id=effective_event_id,
                is_canonical=1,
                event_size=item.get("_event_size", 1),
            )
            continue
        existing_urls.add(item["url"])
        new_items.append(item)

    if not new_items:
        return []

    # Pre-compute cluster-level title/summary for multi-article events.
    # Uses raw article titles (available before LLM enrichment) so synthesis can
    # run concurrently with — or before — the per-article enrichment loop.
    multi_article_items = [item for item in new_items if item.get("_event_size", 1) > 1]
    cluster_synthesis_list: list[dict] = []
    # Build index: _event_id → synthesis result
    cluster_synthesis_by_event_id: dict[str, dict] = {}
    if multi_article_items:
        log.info("synthesizing titles/summaries for %d multi-article cluster(s)", len(multi_article_items))
        cluster_synthesis_list = _synthesize_cluster_events(multi_article_items, context_params)
        for item, synth in zip(multi_article_items, cluster_synthesis_list):
            if item.get("_event_id"):
                cluster_synthesis_by_event_id[item["_event_id"]] = synth

    # Track impacted event ids for delta-refresh (accumulated during this store pass)
    impacted_event_ids: list[str] = []

    # Process in batches of BATCH_SIZE — each batch = one LLM call
    new_articles: list[dict] = []
    touched_claim_ids: list[str] = []
    existing_claims = get_claims_v2(topic_id, limit=300) if topic_id is not None else []
    claim_index = {_statement_key(c.get("statement", "")): c for c in existing_claims}
    for batch_start in range(0, len(new_items), BATCH_SIZE):
        batch = new_items[batch_start: batch_start + BATCH_SIZE]
        parsed_list = _call_batch_llm(batch, context_params)
        log.info("enriched batch %d (%d articles)", batch_start // BATCH_SIZE + 1, len(batch))

        for item, parsed in zip(batch, parsed_list):
            # #region agent log
            try:
                import json as _json2, time as _time2
                with open("/Users/no15438/Desktop/Domain_Monitor/.cursor/debug-c3cf2d.log","a") as _f2:
                    _f2.write(_json2.dumps({"sessionId":"c3cf2d","hypothesisId":"H-B","location":"pipeline.py:557","message":"item_loop_entry","data":{"title":(item.get("title") or "")[:60]},"timestamp":int(_time2.time()*1000)})+"\n")
            except Exception:
                pass
            # #endregion
            article_id = str(uuid.uuid4())
            breakdown = item.get("_source_breakdown", {})

            # Reconcile event_id against recent events to avoid id drift
            reconciled_event_id = _reconcile_event_id(item, recent_event_stubs)
            effective_event_id = reconciled_event_id or item.get("_event_id") or f"evt-{uuid.uuid4().hex[:12]}"
            if reconciled_event_id:
                log.debug("reconciled event_id %s → %s for '%s'", item.get("_event_id"), reconciled_event_id, item.get("title", "")[:60])

            article = {
                "id": article_id,
                "title": item["title"],
                "summary": parsed.get("summary", ""),
                "content": item["content"],
                "source": item.get("source", ""),
                "url": item["url"],
                "tags": json.dumps(parsed.get("tags", []), ensure_ascii=False),
                "sentiment": parsed.get("sentiment", "neutral"),
                "importance": int(parsed.get("importance", 5)),
                "source_type": item.get("_source_type", "search"),
                "topic_id": topic_id,
                "published_at": _normalize_date(item.get("published_date", "")),
                "event_id": effective_event_id,
                "is_canonical": item.get("_is_canonical", 1),
                "event_size": item.get("_event_size", 1),
                "source_score": item.get("_source_score", 0),
                "source_breakdown": json.dumps(breakdown, ensure_ascii=False),
                "topic_relevance": float(parsed.get("topic_relevance", 0.5)),
                "key_entities": json.dumps(parsed.get("key_entities", []), ensure_ascii=False),
                "topic_analysis": parsed.get("topic_analysis", ""),
            }
            insert_article(article)
            impacted_event_ids.append(effective_event_id)

            vector_text = (
                f"{item['title']}. {parsed.get('summary', '')}. "
                f"{(item.get('content') or '')[:500]}"
            )
            new_articles.append(article)

            if topic_id is not None:
                event_id = effective_event_id
                last_seen_at = article["published_at"] or datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

                # Use cluster-level synthesis for multi-article events; fall back to
                # canonical article title/summary for single-article events.
                cluster_synth = cluster_synthesis_by_event_id.get(item.get("_event_id", ""), {})
                event_title = (
                    cluster_synth.get("event_title")
                    or item.get("title")
                    or parsed.get("summary")
                    or "Untitled event"
                )
                event_summary = (
                    cluster_synth.get("event_summary")
                    or parsed.get("summary")
                    or parsed.get("topic_analysis")
                    or ""
                )

                event_size = item.get("_event_size", 1)
                # Only create/update an event record for multi-source clusters (2+ articles).
                # Single-article entries remain as plain articles in the news feed only.
                if event_size >= 2:
                    event_status = "stabilized" if event_size >= 3 else "active"
                    upsert_event(
                        topic_id=topic_id,
                        event_id=event_id,
                        event_key=event_id,
                        title=event_title,
                        summary=event_summary,
                        status=event_status,
                        canonical_article_id=article_id,
                        first_seen_at=last_seen_at,
                        last_seen_at=last_seen_at,
                        novelty_window_end=last_seen_at,
                        stability_score=min(1.0, event_size / 5),
                        fact_confidence=min(1.0, _coerce_float(parsed.get("topic_relevance"), 0.5)),
                        metadata={
                            "source_score": item.get("_source_score", 0),
                            "importance": article["importance"],
                            "sentiment": article["sentiment"],
                        },
                    )
                    # Mark whether this event is brand-new (not previously known in stubs)
                    if event_id not in existing_event_ids_before_batch:
                        article["_is_new_event"] = True
                # Add to reconciliation stubs so subsequent items in same batch can match
                recent_event_stubs.append({"id": event_id, "title": event_title, "canonical_url": article["url"]})

                # Build the list of claims to store for this event.
                # New format: parsed["claims"] is a list of {kind, statement, summary}.
                # Fallback to old single-claim format for backward compatibility.
                raw_claims_list = parsed.get("claims") or []
                if not isinstance(raw_claims_list, list) or not raw_claims_list:
                    fallback_statement, fallback_summary = _build_claim_text(item, parsed)
                    raw_claims_list = [
                        {
                            "kind": parsed.get("claim_kind", "observation"),
                            "statement": fallback_statement,
                            "summary": fallback_summary,
                        }
                    ]

                signal_type = (parsed.get("signal_type") or "market signal").strip()[:40] or "market signal"
                claim_confidence = min(1.0, _coerce_float(parsed.get("topic_relevance"), 0.5))
                claim_half_life = 14.0 if article["importance"] >= 8 else 7.0

                # #region agent log
                import json as _json, time as _time
                try:
                    with open("/Users/no15438/Desktop/Domain_Monitor/.cursor/debug-c3cf2d.log","a") as _f:
                        _f.write(_json.dumps({"sessionId":"c3cf2d","hypothesisId":"H-A","location":"pipeline.py:666","message":"claim_loop_entry","data":{"num_claims":len(raw_claims_list),"event_id":event_id},"timestamp":int(_time.time()*1000)})+"\n")
                except Exception:
                    pass
                # #endregion
                for idx, raw_claim in enumerate(raw_claims_list[:4]):
                    c_statement = str(raw_claim.get("statement") or "").strip()
                    c_summary = str(raw_claim.get("summary") or parsed.get("summary") or "").strip()
                    c_kind = _normalize_claim_kind(raw_claim.get("kind"))
                    if not c_statement:
                        continue
                    if len(c_statement) > 240:
                        c_statement = c_statement[:237].rstrip() + "..."
                    if len(c_summary) > 240:
                        c_summary = c_summary[:237].rstrip() + "..."

                    claim_key = _statement_key(c_statement)
                    previous_claim = claim_index.get(claim_key)
                    evidence_id = f"evidence-{event_id}-{idx}"
                    claim_id = upsert_claim(
                        topic_id=topic_id,
                        statement=c_statement,
                        claim_type=c_kind,
                        summary=c_summary,
                        status="active",
                        supporting_evidence_ids=[evidence_id],
                        decay_policy="slow" if article["importance"] >= 8 else "medium",
                        staleness_status="fresh",
                        metadata={
                            "event_id": event_id,
                            "article_id": article_id,
                            "topic_analysis": parsed.get("topic_analysis", ""),
                        },
                    )
                    if previous_claim:
                        add_claim_evolution(
                            topic_id=topic_id,
                            claim_id=claim_id,
                            previous_claim_id=previous_claim["id"],
                            relation_type="strengthened",
                            reason="new supporting evidence from fresh event coverage",
                            metadata={"event_id": event_id, "article_id": article_id},
                        )
                    claim_index[claim_key] = {
                        "id": claim_id,
                        "statement": c_statement,
                    }
                    if claim_id not in touched_claim_ids:
                        touched_claim_ids.append(claim_id)

                    upsert_evidence_set(
                        evidence_id=evidence_id,
                        topic_id=topic_id,
                        event_id=event_id,
                        claim_id=claim_id,
                        title=event_title,
                        summary=c_summary,
                        evidence_type=signal_type,
                        stance="supporting",
                        confidence=claim_confidence,
                        freshness_half_life=claim_half_life,
                        supporting_event_ids=[event_id],
                        contradicting_event_ids=[],
                        metadata={
                            "article_id": article_id,
                            "source": article["source"],
                            "url": article["url"],
                            "published_at": article["published_at"],
                            "last_seen_at": last_seen_at,
                        },
                    )

                    add_evidence_document(
                        evidence_id,
                        f"{event_title}\n{c_summary}\nEvidence from {article['source']}\n{vector_text}",
                        {
                            "topic_id": str(topic_id),
                            "status": "active",
                            "claim_id": claim_id,
                            "event_id": event_id,
                            "title": event_title,
                            "url": article["url"],
                        },
                    )
                    add_claim_document(
                        claim_id,
                        f"{c_statement}\n{c_summary}\nEvent: {event_title}",
                        {
                            "topic_id": str(topic_id),
                            "status": "active",
                            "claim_type": c_kind,
                            "event_id": event_id,
                            "title": event_title,
                        },
                    )

                event_source_rows = [
                    {
                        "event_id": event_id,
                        "raw_news_id": item.get("_raw_news_id"),
                        "article_id": article_id,
                        "source_rank": 1,
                        "source_role": "canonical",
                        "is_canonical": 1,
                        "metadata_json": json.dumps({"url": article["url"]}, ensure_ascii=False),
                    }
                ]

                add_event_document(
                    event_id,
                    f"{event_title}\n{event_summary}\nSource: {article['source']}\nSentiment: {article['sentiment']}",
                    {
                        "topic_id": str(topic_id),
                        "status": event_status,
                        "event_status": event_status,
                        "title": event_title,
                        "source": article["source"],
                        "url": article["url"],
                        "last_seen_at": last_seen_at,
                        "novelty_score": str(item.get("_source_score", 0)),
                    },
                )

            # Store non-canonical cluster members (no LLM enrichment)
            for alt in item.get("_cluster_alts", []):
                if alt["url"] in existing_urls:
                    # Article already in DB — update event linkage so
                    # get_event_alternatives() can find it by the current event_id.
                    update_article_event_fields(
                        url=alt["url"],
                        event_id=alt.get("_event_id", ""),
                        is_canonical=0,
                        event_size=alt.get("_event_size", 1),
                    )
                    continue
                existing_urls.add(alt["url"])
                alt_breakdown = alt.get("_source_breakdown", {})
                insert_article({
                    "id": str(uuid.uuid4()),
                    "title": alt["title"],
                    "summary": "",
                    "content": alt["content"],
                    "source": alt.get("source", ""),
                    "url": alt["url"],
                    "tags": "[]",
                    "sentiment": "neutral",
                    "importance": 0,
                    "source_type": alt.get("_source_type", "search"),
                    "topic_id": topic_id,
                    "published_at": _normalize_date(alt.get("published_date", "")),
                    "event_id": alt.get("_event_id", ""),
                    "is_canonical": 0,
                    "event_size": alt.get("_event_size", 1),
                    "source_score": alt.get("_source_score", 0),
                    "source_breakdown": json.dumps(alt_breakdown, ensure_ascii=False),
                    "topic_relevance": 0.0,
                    "key_entities": "[]",
                    "topic_analysis": "",
                })
                if topic_id is not None:
                    event_source_rows.append(
                        {
                            "event_id": event_id,
                            "raw_news_id": alt.get("_raw_news_id"),
                            "article_id": None,
                            "source_rank": len(event_source_rows) + 1,
                            "source_role": "supporting",
                            "is_canonical": 0,
                            "metadata_json": json.dumps(
                                {
                                    "url": alt.get("url"),
                                    "source": alt.get("source", ""),
                                },
                                ensure_ascii=False,
                            ),
                        }
                    )
            if topic_id is not None:
                replace_event_sources(event_id, event_source_rows)

    if topic_id is not None and touched_claim_ids:
        evaluate_claim_lifecycle(topic_id, touched_claim_ids=touched_claim_ids, source="pipeline")

    # Attach impacted event ids to each article for SSE delta consumers
    for art in new_articles:
        art.setdefault("_impacted_event_id", art.get("event_id", ""))

    return new_articles


# ── Orchestrator ──────────────────────────────────────


def _run_for_topic(topic_id: int, existing_urls: set[str]) -> list[dict]:
    kws = get_keywords(topic_id)
    keyword_list = [kw["keyword"] for kw in kws]

    topics = get_topics()
    topic_name = ""
    research_brief = ""
    research_config: dict = {}
    pipeline_cfg: dict = {}
    for t in topics:
        if t["id"] == topic_id:
            topic_name = t["name"]
            research_brief = t.get("research_brief") or ""
            try:
                raw_cfg = t.get("research_config") or "{}"
                research_config = json.loads(raw_cfg) if isinstance(raw_cfg, str) else (raw_cfg or {})
            except Exception:
                research_config = {}
            try:
                raw_pcfg = t.get("pipeline_config") or "{}"
                pipeline_cfg = json.loads(raw_pcfg) if isinstance(raw_pcfg, str) else (raw_pcfg or {})
            except Exception:
                pipeline_cfg = {}
            break

    # Topic-level overrides for pipeline thresholds
    relevance_min = float(pipeline_cfg.get("relevance_min_score", 0.05))
    cluster_threshold = float(pipeline_cfg.get("cluster_threshold", settings.event_cluster_threshold))
    dedup_threshold = float(pipeline_cfg.get("dedup_threshold", 0.82))
    crossrun_dedup_threshold = float(pipeline_cfg.get("crossrun_dedup_threshold", 0.88))

    entities = research_config.get("entities", [])
    geo_scope = research_config.get("geographic_scope", [])
    extra_search_terms = [e for e in entities[:5]]

    # Stage 1: COLLECT
    raw: list[dict] = []
    all_search_terms = keyword_list + extra_search_terms
    if all_search_terms:
        raw.extend(_collect_for_keywords(all_search_terms, max_per_source=10))
    feed_rows = get_topic_feeds(topic_id)
    feed_urls = [f["feed_url"] for f in feed_rows]
    global_feeds = [u.strip() for u in settings.global_rss_feeds.split(",") if u.strip()]
    all_feeds = feed_urls + global_feeds
    if all_feeds:
        raw.extend(_collect_rss(all_feeds))

    # Stage 2: URL DEDUP (normalized)
    url_unique = _url_dedup(raw, existing_urls)

    # Stage 2.5: SEMANTIC DEDUP — uses topic-level thresholds
    existing_stubs = get_recent_article_stubs(topic_id=topic_id, hours=48)
    sem_unique = _semantic_dedup(url_unique, existing_stubs=existing_stubs,
                                  within_threshold=dedup_threshold,
                                  cross_threshold=crossrun_dedup_threshold)

    # Persist normalized ingest records before relevance/canonical selection so
    # downstream entities can keep provenance to the source material.
    insert_raw_news(_serialize_raw_news(topic_id, sem_unique))

    # Stage 3: RELEVANCE FILTER — uses topic-level min score
    relevance_terms = keyword_list + [e for e in entities] + [g for g in geo_scope]
    relevant = _relevance_filter(sem_unique, relevance_terms, min_score=relevance_min) if relevance_terms else sem_unique

    # Stage 4+5: EVENT CLUSTER + CANONICAL SELECTION — uses topic-level cluster threshold
    clusters, canonicals = _cluster_and_select(relevant, cluster_threshold=cluster_threshold)

    log.info(
        "topic=%d: %d collected → %d url-unique → %d sem-unique → %d relevant → %d events → %d canonicals → enriching",
        topic_id, len(raw), len(url_unique), len(sem_unique), len(relevant), len(clusters), len(canonicals),
    )

    # Stage 6+7: ENRICH & STORE (full research context)
    return _enrich_and_store(
        canonicals, topic_id, existing_urls,
        topic_name, keyword_list,
        research_brief, research_config,
    )


def run_pipeline_once(topic_id: int | None = None) -> list[dict]:
    existing_urls = get_recent_urls(hours=72)
    all_new: list[dict] = []

    if topic_id is not None:
        all_new.extend(_run_for_topic(topic_id, existing_urls))
    else:
        topics = get_topics()
        if topics:
            for topic in topics:
                all_new.extend(_run_for_topic(topic["id"], existing_urls))
        else:
            keyword_list = [k.strip() for k in settings.monitor_keywords.split(",") if k.strip()]
            if keyword_list:
                raw = _collect_for_keywords(keyword_list, max_per_source=15)
                global_feeds = [u.strip() for u in settings.global_rss_feeds.split(",") if u.strip()]
                if global_feeds:
                    raw.extend(_collect_rss(global_feeds))
                url_unique = _url_dedup(raw, existing_urls)
                existing_stubs = get_recent_article_stubs(topic_id=None, hours=48)
                sem_unique = _semantic_dedup(url_unique, existing_stubs=existing_stubs)
                relevant = _relevance_filter(sem_unique, keyword_list)
                clusters, canonicals = _cluster_and_select(relevant)
                log.info(
                    "global: %d collected → %d url-unique → %d sem-unique → %d relevant → %d events → %d canonicals → enriching",
                    len(raw), len(url_unique), len(sem_unique), len(relevant), len(clusters), len(canonicals),
                )
                all_new.extend(_enrich_and_store(canonicals, None, existing_urls))

    return all_new
