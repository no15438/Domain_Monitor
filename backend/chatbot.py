import json
from llm_client import llm_chat, llm_chat_stream
from vector_store import search_multi_collection
from search_client import search as web_search
from database import (
    get_latest_temporal_snapshot,
    get_topics,
    get_synthesis_artifact,
)

ROUTE_TYPES = {
    "latest_update",
    "evidence_request",
    "background_explanation",
    "trend_evolution",
    "mixed",
}
COLLECTION_TYPES = {"events", "evidence", "claims", "snapshots", "artifacts"}
DEFAULT_COLLECTIONS = ["events", "evidence", "claims", "snapshots", "artifacts"]
ROUTE_COLLECTIONS = {
    "latest_update": ["events", "snapshots"],
    "evidence_request": ["evidence", "claims"],
    "background_explanation": ["claims", "artifacts", "snapshots"],
    "trend_evolution": ["snapshots", "artifacts", "claims"],
    "mixed": DEFAULT_COLLECTIONS,
}
ROUTE_CONFIDENCE_FLOOR = 0.45
TOPIC_CONTEXT_MAX_CHARS = 1800
ARTICLE_CONTEXT_MAX_CHARS = 800
FINAL_CONTEXT_MAX_CHARS = 5200
HISTORY_MESSAGE_LIMIT = 8
HISTORY_MESSAGE_MAX_CHARS = 500
EVENT_DOC_MAX_CHARS = 260
EVIDENCE_DOC_MAX_CHARS = 260
CLAIM_DOC_MAX_CHARS = 180
SNAPSHOT_DOC_MAX_CHARS = 320
ARTIFACT_DOC_MAX_CHARS = 320
WEB_DOC_MAX_CHARS = 180

SYSTEM_PROMPT = """You are an intelligent industry monitoring assistant.
You help users understand industry trends, news, and events based on a curated knowledge base and live web searches.

Rules:
1. Use provided context to give accurate, up-to-date answers.
2. Cite sources (title + URL) when possible.
3. If the context is insufficient, clearly say so.
4. Be concise but thorough.
5. ALWAYS respond in the same language as the user's question."""

ROUTE_PLANNER_SYSTEM = """You are a retrieval planner for a domain-monitoring assistant.

You must decide which knowledge route should be used before answering the user.

Allowed routes:
- latest_update
- evidence_request
- background_explanation
- trend_evolution
- mixed

Allowed collections:
- events
- evidence
- claims
- snapshots
- artifacts

Guidance:
- latest_update: recent developments, latest updates, short-horizon change
- evidence_request: asks why, basis, evidence, sources, proof
- background_explanation: asks for background, definition, long-term structure, overview
- trend_evolution: asks how the topic evolved across weeks/months, what strengthened/weakened over time
- mixed: combines multiple intents or is too ambiguous

Return JSON only with this exact shape:
{
  "route": "latest_update",
  "collections": ["events", "snapshots"],
  "reason": "short reason",
  "confidence": 0.0,
  "time_horizon": "short"
}

Rules:
- confidence must be a float between 0 and 1
- time_horizon must be one of: immediate, short, medium, long, unknown
- collections must only use the allowed values
- If uncertain, choose mixed
- Do not include markdown fences or any extra text"""


def _truncate_text(text: str | None, limit: int) -> str:
    value = (text or "").strip()
    if len(value) <= limit:
        return value
    return value[: max(limit - 3, 0)].rstrip() + "..."

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
    """Build a preamble string from the latest lineage snapshot and synthesis artifact."""
    snapshot = get_latest_temporal_snapshot(topic_id, window_type="daily")
    artifact = get_synthesis_artifact(topic_id, "global_overview")
    if not snapshot and not artifact:
        return None

    topic_name = ""
    for t in get_topics():
        if t["id"] == topic_id:
            topic_name = t["name"]
            break

    stats = {}
    try:
        stats = json.loads((snapshot or {}).get("stats_metadata") or "{}")
    except (json.JSONDecodeError, TypeError):
        pass

    result_parts: list[str] = []
    if snapshot and snapshot.get("summary_text"):
        result_parts.append(
            SNAPSHOT_PREAMBLE.format(
                topic_name=topic_name,
                date=snapshot.get("window_end") or snapshot.get("created_at") or "unknown",
                overview=snapshot["summary_text"],
            )
        )

    top_entities = stats.get("top_entities", [])
    if top_entities:
        result_parts.append(
            "Key entities recently tracked: " + ", ".join(e["entity"] for e in top_entities[:8])
        )

    if artifact and artifact.get("content", "").strip():
        result_parts.append(GLOBAL_OVERVIEW_PREAMBLE.format(overview=artifact["content"]))

    if not result_parts:
        return None
    return _truncate_text("\n\n".join(result_parts), TOPIC_CONTEXT_MAX_CHARS)


def _default_route_plan(reason: str = "fallback") -> dict:
    return {
        "route": "mixed",
        "collections": DEFAULT_COLLECTIONS.copy(),
        "reason": reason,
        "confidence": 0.0,
        "time_horizon": "unknown",
    }


def _normalize_route_plan(raw_text: str | None) -> dict:
    if not raw_text:
        return _default_route_plan("empty planner output")

    try:
        payload = json.loads(raw_text)
    except Exception:
        return _default_route_plan("invalid planner json")

    if not isinstance(payload, dict):
        return _default_route_plan("planner output is not object")

    route = payload.get("route")
    if route not in ROUTE_TYPES:
        return _default_route_plan("invalid route")

    raw_collections = payload.get("collections")
    if not isinstance(raw_collections, list):
        raw_collections = []
    collections = []
    for name in raw_collections:
        if name in COLLECTION_TYPES and name not in collections:
            collections.append(name)
    if not collections:
        collections = ROUTE_COLLECTIONS[route].copy()

    reason = str(payload.get("reason") or "").strip()[:160] or "llm route planner"

    confidence_raw = payload.get("confidence", 0)
    try:
        confidence = float(confidence_raw)
    except Exception:
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    time_horizon = str(payload.get("time_horizon") or "unknown").strip().lower()
    if time_horizon not in {"immediate", "short", "medium", "long", "unknown"}:
        time_horizon = "unknown"

    if confidence < ROUTE_CONFIDENCE_FLOOR:
        return _default_route_plan(f"low confidence route: {route}")

    return {
        "route": route,
        "collections": collections,
        "reason": reason,
        "confidence": confidence,
        "time_horizon": time_horizon,
    }


def _plan_route_with_llm(message: str, article_context: str | None = None, topic_id: int | None = None) -> dict:
    context_parts = [f"Question: {message}"]
    if topic_id is not None:
        context_parts.append(f"Topic ID: {topic_id}")
    if article_context:
        context_parts.append(f"Article context:\n{article_context[:1000]}")

    try:
        raw = llm_chat(
            [
                {"role": "system", "content": ROUTE_PLANNER_SYSTEM},
                {"role": "user", "content": "\n\n".join(context_parts)},
            ],
            temperature=0,
        )
    except Exception as exc:
        return _default_route_plan(f"planner exception: {exc}")

    return _normalize_route_plan(raw)


def _route_search(query: str, topic_id: int | None, route_plan: dict) -> dict[str, list[dict]]:
    where_filter = {"topic_id": str(topic_id)} if topic_id is not None else None
    route = route_plan.get("route", "mixed")
    kinds = route_plan.get("collections") or ROUTE_COLLECTIONS.get(route, DEFAULT_COLLECTIONS)
    hits = search_multi_collection(query, kinds, n_results_per_collection=4, where_filter=where_filter)
    grouped = {"events": [], "evidence": [], "claims": [], "snapshots": [], "artifacts": []}
    for hit in hits:
        collection = hit.get("collection", "")
        if collection.endswith("kb_hot_events"):
            grouped["events"].append(hit)
        elif collection.endswith("kb_evidence_sets"):
            grouped["evidence"].append(hit)
        elif collection.endswith("kb_claims"):
            grouped["claims"].append(hit)
        elif collection.endswith("kb_temporal_snapshots"):
            grouped["snapshots"].append(hit)
        elif collection.endswith("kb_synthesis_artifacts"):
            grouped["artifacts"].append(hit)
    return grouped


def _extract_title_from_ctx(article_context: str) -> str:
    """Extract the Title line from a formatted article_context string."""
    for line in article_context.splitlines():
        if line.startswith("Title:"):
            return line[6:].strip()
    return ""


def _build_final_context(parts: list[str]) -> str:
    if not parts:
        return ""
    ctx = "\n\n".join(part for part in parts if part.strip())
    return _truncate_text(ctx, FINAL_CONTEXT_MAX_CHARS)


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
        parts.append(f"[Current article context]\n{_truncate_text(article_context, ARTICLE_CONTEXT_MAX_CHARS)}")

    yield {"status": "searching_knowledge_base"}

    # Enrich vector search query with article title when available
    search_query = message
    if article_context:
        title = _extract_title_from_ctx(article_context)
        if title:
            search_query = f"{title} {message}"

    route_plan = _plan_route_with_llm(message, article_context, topic_id)
    route_hits = _route_search(search_query, topic_id, route_plan)
    parts.append(
        "[Knowledge route] "
        f"{route_plan['route']} | collections={','.join(route_plan['collections'])} "
        f"| confidence={route_plan['confidence']:.2f} | reason={route_plan['reason']}"
    )

    if route_hits["events"]:
        parts.append("[Recent events]")
        for i, r in enumerate(route_hits["events"][:4], 1):
            meta = r.get("metadata", {})
            parts.append(
                f"  [Event-{i}] {meta.get('title', 'Untitled')} "
                f"(status: {meta.get('event_status', '?')}, source: {meta.get('source', '?')})\n"
                f"  {_truncate_text(r['document'], EVENT_DOC_MAX_CHARS)}"
            )

    if route_hits["evidence"]:
        parts.append("[Evidence sets]")
        for i, r in enumerate(route_hits["evidence"][:4], 1):
            meta = r.get("metadata", {})
            parts.append(
                f"  [Evidence-{i}] {meta.get('title', 'Untitled')} "
                f"(claim: {meta.get('claim_id', '')}, url: {meta.get('url', '')})\n"
                f"  {_truncate_text(r['document'], EVIDENCE_DOC_MAX_CHARS)}"
            )

    if route_hits["claims"]:
        parts.append("[Claims]")
        for i, r in enumerate(route_hits["claims"][:4], 1):
            meta = r.get("metadata", {})
            parts.append(
                f"  [Claim-{i}] {_truncate_text(r['document'], CLAIM_DOC_MAX_CHARS)}\n"
                f"  type={meta.get('claim_type', '?')} status={meta.get('status', '?')}"
            )

    if route_hits["snapshots"]:
        parts.append("[Historical domain analysis snapshots]")
        for i, r in enumerate(route_hits["snapshots"][:4], 1):
            meta = r.get("metadata", {})
            parts.append(
                f"  [Snapshot-{i}] {meta.get('topic_name', '?')} ({meta.get('date', meta.get('window_end', '?'))})\n"
                f"  {_truncate_text(r['document'], SNAPSHOT_DOC_MAX_CHARS)}"
            )

    if route_hits["artifacts"]:
        parts.append("[Synthesis artifacts]")
        for i, r in enumerate(route_hits["artifacts"][:3], 1):
            meta = r.get("metadata", {})
            parts.append(
                f"  [Artifact-{i}] {meta.get('artifact_type', '?')}\n"
                f"  {_truncate_text(r['document'], ARTIFACT_DOC_MAX_CHARS)}"
            )

    primary_hits = (
        route_hits["events"]
        or route_hits["evidence"]
        or route_hits["claims"]
        or route_hits["snapshots"]
        or route_hits["artifacts"]
    )
    need_web = (not primary_hits) or (primary_hits and primary_hits[0].get("distance", 1) > 0.5)
    if need_web:
        yield {"status": "searching_web"}
        try:
            web = web_search(message, max_results=3)
            if web:
                parts.append("[Live web search results]")
                for i, r in enumerate(web, 1):
                    parts.append(
                        f"  [Web-{i}] {r['title']} ({r['url']})\n  {_truncate_text(r['content'], WEB_DOC_MAX_CHARS)}"
                    )
        except Exception:
            pass

    yield {"status": "generating"}

    ctx = _build_final_context(parts)

    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    # Inject prior conversation turns (max 20 messages to avoid token overflow)
    if history:
        # Only keep roles the LLM understands; strip any empty assistant placeholders
        valid_history = [
            {
                "role": h["role"],
                "content": _truncate_text(h.get("content", ""), HISTORY_MESSAGE_MAX_CHARS),
            }
            for h in history[-HISTORY_MESSAGE_LIMIT:]
            if h.get("role") in ("user", "assistant") and h.get("content", "").strip()
        ]
        messages.extend(valid_history)
    messages.append({"role": "user", "content": f"Context:\n{ctx}\n\nQuestion: {message}"})
    yield from llm_chat_stream(messages, temperature=0.5)
