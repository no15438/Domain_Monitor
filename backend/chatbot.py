"""chatbot.py — Time-aware, state-first RAG for domain monitoring chat.

Pipeline per query
  1. classify_query_intent()        — lightweight LLM call: which knowledge layers?
  2. retrieve_current_state()       — DB-first: fresh events, fresh claims, latest snapshot
  3. retrieve_timeline_context()    — DB-first: time-ordered events, deltas, claim evolution
  4. retrieve_archive_context()     — DB: superseded / inactive items (demoted)
  5. resolve_freshness_conflicts()  — label & filter before LLM sees anything
  6. _run_vector_supplement()       — Chroma fills gaps when DB data is thin
  7. Web search                     — last resort when both DB and vector are empty
  8. compose_answer_context()       — build final context string
  9. LLM streaming answer
"""
import json
import re
from datetime import datetime, timezone

from llm_client import llm_chat_stream
from vector_store import search_multi_collection
from search_client import search as web_search
from database import (
    get_latest_temporal_snapshot,
    get_temporal_snapshots,
    get_topics,
    get_synthesis_artifact,
    get_events_v2,
    get_events_since,
    get_fresh_claims,
    get_claims_v2,
    get_claim_evolution,
    get_snapshot_deltas,
)

# ── Limits & thresholds ────────────────────────────────────────────────────────

INTENT_CONFIDENCE_FLOOR = 0.40
ARTICLE_CONTEXT_MAX_CHARS = 800
FINAL_CONTEXT_MAX_CHARS = 6000
HISTORY_MESSAGE_LIMIT = 8
HISTORY_MESSAGE_MAX_CHARS = 500

# Per-section item limits
MAX_EVENTS_CURRENT = 8
MAX_EVENTS_TIMELINE = 12
MAX_FRESH_CLAIMS = 12
MAX_STALE_CLAIMS = 4
MAX_CLAIM_EVOLUTION = 15
MAX_DELTAS = 3
MAX_OLD_SNAPSHOTS = 2

# Vector supplemental per-collection limit
MAX_VEC_PER_COLLECTION = 4

# DB "thin" thresholds that trigger supplemental vector search
DB_THIN_EVENT_THRESHOLD = 2
DB_THIN_CLAIM_THRESHOLD = 2

# ── System prompts ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are an intelligent domain-monitoring assistant with access to a \
structured, time-aware knowledge base.

Context is organized in sections:
- [CURRENT STATE]: Most recent verified information. Always prioritize this.
- [RECENT EVOLUTION]: How the situation has changed over time.
- [HISTORICAL BACKGROUND]: Older context. Use only as background; never present as \
current fact.
- [SUPPLEMENTAL]: Vector-matched items that may not reflect the latest state.

Special markers in the context:
- [FRESH]: Actively supported by recent evidence.
- [STALE]: No new supporting signal recently; treat with caution.
- [SUPERSEDED]: Replaced by a newer finding.
- [INACTIVE]: No longer actively tracked.
- [ARCHIVED]: Resolved or no longer relevant.

Rules:
1. Answer from CURRENT STATE first. Add RECENT EVOLUTION when it enriches the answer.
2. When current and historical data conflict, clearly state the discrepancy and favor \
the newer information.
3. If current evidence is thin, say so explicitly rather than relying on historical \
data as if it were current.
4. When referencing a specific source, you MAY wrap its title in square brackets like \
[Some Event Title] so the UI can render it as a clickable citation button. Use this only \
for key facts — do NOT reference generic section names like [Current Claims], \
[Active Events], [Recent Evolution], [CURRENT STATE], [SUPPLEMENTAL], or internal \
system labels. Never invent titles; only use exact titles from the context provided.
5. ALWAYS respond in the same language as the user's question."""

INTENT_PLANNER_SYSTEM = """You are a query intent classifier for a domain-monitoring \
knowledge system.

Classify the user question to determine which knowledge layers are needed.

Return JSON only with this exact shape:
{
  "needs_current_state": true,
  "needs_timeline": false,
  "needs_archive": false,
  "time_window_days": 14,
  "reason": "short reason",
  "confidence": 0.0
}

Rules:
- needs_current_state: almost always true; false only for pure historical questions
- needs_timeline: true when asking about changes, evolution, trends, development over time
- needs_archive: true when asking about history, origins, what happened before, past state
- time_window_days: days to look back for timeline (7 / 14 / 30 / 60 / 90); default 14
- confidence: 0.0–1.0; use 0.5 if unsure
- Do not include markdown fences or extra text

Examples:
- "What is the latest on X?" → needs_current=true, timeline=false, archive=false, days=7
- "How has X evolved over the past month?" → current=true, timeline=true, archive=false, days=30
- "When did X start and how did it develop?" → current=true, timeline=true, archive=true, days=60
- "What was the situation with X last year?" → current=false, timeline=false, archive=true, days=365"""

# ── Intent classification ──────────────────────────────────────────────────────

_TIMELINE_KEYWORDS = re.compile(
    r"evolv|changed?|trend|develop|phase|stage|progression|over time"
    r"|past \d+|last \d+ (day|week|month)"
    r"|变化|演变|发展|趋势|经历|阶段|近\d+|最近\d+|过去\d+",
    re.IGNORECASE,
)
_ARCHIVE_KEYWORDS = re.compile(
    r"histor|origin|before|previous|used to|earliest|founded|back in|when did .* start"
    r"|历史|以前|最早|曾经|起源|最初|当初",
    re.IGNORECASE,
)


def _rule_based_intent(message: str) -> dict:
    """Fallback rule-based intent when LLM call fails or confidence is low."""
    needs_timeline = bool(_TIMELINE_KEYWORDS.search(message))
    needs_archive = bool(_ARCHIVE_KEYWORDS.search(message))
    time_window_days = 60 if needs_archive else (30 if needs_timeline else 14)
    return {
        "needs_current_state": not needs_archive or needs_timeline,
        "needs_timeline": needs_timeline,
        "needs_archive": needs_archive,
        "time_window_days": time_window_days,
        "reason": "rule-based fallback",
        "confidence": 0.55,
    }


def classify_query_intent(message: str, article_context: str | None = None) -> dict:
    """Return an intent dict describing which knowledge layers to activate.

    Interactive chat should not block on a separate planner model call before any
    progress is visible to the user. We therefore use the lightweight rule-based
    classifier here and reserve the main LLM call for answer generation.
    """
    return _rule_based_intent(message)


# ── Retrievers ─────────────────────────────────────────────────────────────────

def retrieve_current_state(topic_id: int) -> dict:
    """DB-first: freshest events, fresh/stale claims, latest snapshot, global overview."""
    active_events = get_events_since(topic_id, days=21, limit=MAX_EVENTS_CURRENT)
    if not active_events:
        # Fallback: any active events regardless of age
        active_events = get_events_v2(topic_id, status="active", limit=MAX_EVENTS_CURRENT)

    fresh_claims = get_fresh_claims(topic_id, limit=MAX_FRESH_CLAIMS)
    stale_claims = get_claims_v2(topic_id, status="stale", limit=MAX_STALE_CLAIMS)

    snapshot = get_latest_temporal_snapshot(topic_id, window_type="daily")
    artifact = get_synthesis_artifact(topic_id, "global_overview")

    return {
        "active_events": active_events,
        "fresh_claims": fresh_claims,
        "stale_claims": stale_claims,
        "snapshot": snapshot,
        "artifact": artifact,
    }


def retrieve_timeline_context(topic_id: int, days: int) -> dict:
    """Time-ordered DB retrieval: event timeline (ASC), snapshot deltas, claim evolution."""
    events = get_events_since(topic_id, days=days, limit=MAX_EVENTS_TIMELINE)
    if not events:
        events = get_events_v2(topic_id, limit=MAX_EVENTS_TIMELINE)
    # Sort ascending so the LLM reads oldest → newest
    timeline_events = sorted(
        events,
        key=lambda e: e.get("first_seen_at") or e.get("created_at") or "",
    )
    deltas = get_snapshot_deltas(topic_id, limit=MAX_DELTAS)
    claim_evo = get_claim_evolution(topic_id, limit=MAX_CLAIM_EVOLUTION)

    return {
        "timeline_events": timeline_events,
        "deltas": deltas,
        "claim_evolution": claim_evo,
    }


def retrieve_archive_context(topic_id: int) -> dict:
    """Historical context (demoted): superseded/inactive claims, older snapshots."""
    superseded = get_claims_v2(topic_id, status="superseded", limit=6)
    inactive = get_claims_v2(topic_id, status="inactive", limit=4)
    all_snaps = get_temporal_snapshots(topic_id, window_type="daily", limit=MAX_OLD_SNAPSHOTS + 1)
    # Skip index 0 (latest is already in current state); take older ones
    old_snapshots = all_snaps[1:MAX_OLD_SNAPSHOTS + 1] if len(all_snaps) > 1 else []

    return {
        "superseded_claims": superseded,
        "inactive_claims": inactive,
        "old_snapshots": old_snapshots,
    }


# ── Freshness resolver ─────────────────────────────────────────────────────────

def _age_label(dt_str: str | None) -> str:
    if not dt_str:
        return ""
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        days = int((datetime.now(timezone.utc) - dt).total_seconds() / 86400)
        if days == 0:
            return "today"
        if days == 1:
            return "1d ago"
        return f"{days}d ago"
    except Exception:
        return ""


def resolve_freshness_conflicts(
    current: dict,
    timeline: dict | None = None,
    archive: dict | None = None,
) -> dict[str, str]:
    """Label, filter and format each knowledge layer before the LLM sees it.

    Returns a dict with string values for keys: "current", "timeline", "archive".
    Missing sections are omitted from the returned dict.
    """
    sections: dict[str, str] = {}

    # ── Current state ─────────────────────────────────────────────────────────
    cur: list[str] = []

    snapshot = current.get("snapshot")
    artifact = current.get("artifact")
    if snapshot and snapshot.get("summary_text", "").strip():
        snap_date = (snapshot.get("window_end") or snapshot.get("created_at") or "unknown")[:10]
        cur.append(f"[Latest AI Briefing — {snap_date}]\n{snapshot['summary_text'][:1200]}")
    elif artifact and artifact.get("content", "").strip():
        cur.append(f"[Domain Overview]\n{artifact['content'][:1200]}")

    active_events = current.get("active_events", [])
    if active_events:
        cur.append("[Active Events]")
        for i, ev in enumerate(active_events[:MAX_EVENTS_CURRENT], 1):
            first = (ev.get("first_seen_at") or ev.get("created_at") or "")[:10]
            last = (ev.get("last_seen_at") or "")[:10]
            stability = round(ev.get("stability_score") or 0, 2)
            date_range = first + (f" → {last}" if last and last != first else "")
            cur.append(
                f"  {i}. [{date_range}] {ev['title']} (stability: {stability})\n"
                f"     {(ev.get('summary') or '')[:240]}"
            )

    fresh_claims = current.get("fresh_claims", [])
    if fresh_claims:
        cur.append("[Current Claims — Fresh]")
        for i, cl in enumerate(fresh_claims[:MAX_FRESH_CLAIMS], 1):
            kind = cl.get("claim_kind") or cl.get("claim_type", "")
            cur.append(
                f"  {i}. {cl['statement']} [FRESH · {kind}]\n"
                f"     {(cl.get('summary') or '')[:180]}"
            )

    stale_claims = current.get("stale_claims", [])
    if stale_claims:
        cur.append("[Current Claims — Aging]")
        for i, cl in enumerate(stale_claims[:MAX_STALE_CLAIMS], 1):
            last_seen = _age_label(cl.get("last_validated_at") or cl.get("updated_at"))
            age_note = f" · last signal: {last_seen}" if last_seen else ""
            cur.append(
                f"  {i}. {cl['statement']} [STALE{age_note}]\n"
                f"     {(cl.get('summary') or '')[:160]}"
            )

    if cur:
        sections["current"] = "\n".join(cur)

    # ── Timeline ──────────────────────────────────────────────────────────────
    if timeline:
        tl: list[str] = []

        deltas = timeline.get("deltas", [])
        if deltas:
            tl.append("[Snapshot Deltas — What Changed]")
            for d in deltas[:MAX_DELTAS]:
                ts = (d.get("created_at") or "")[:10]
                tl.append(f"  [{ts}] {d.get('change_summary', '')[:280]}")

        tl_events = timeline.get("timeline_events", [])
        if tl_events:
            tl.append("[Event Timeline — Oldest to Newest]")
            for i, ev in enumerate(tl_events[:MAX_EVENTS_TIMELINE], 1):
                first = (ev.get("first_seen_at") or "")[:10]
                status = ev.get("status", "active")
                tag = "" if status == "active" else f" [{status.upper()}]"
                tl.append(
                    f"  {i}. [{first}]{tag} {ev['title']}\n"
                    f"     {(ev.get('summary') or '')[:200]}"
                )

        evo = timeline.get("claim_evolution", [])
        if evo:
            tl.append("[Claim Evolution Signals]")
            for i, e in enumerate(evo[:MAX_CLAIM_EVOLUTION], 1):
                ts = (e.get("created_at") or "")[:10]
                rel = e.get("relation_type", "")
                tl.append(f"  {i}. [{ts}] {rel} — {e.get('reason', '')[:180]}")

        if tl:
            sections["timeline"] = "\n".join(tl)

    # ── Archive ───────────────────────────────────────────────────────────────
    if archive:
        arch: list[str] = []

        superseded = archive.get("superseded_claims", [])
        if superseded:
            arch.append("[Superseded Claims — Historical Only]")
            for i, cl in enumerate(superseded, 1):
                arch.append(
                    f"  {i}. [SUPERSEDED] {cl['statement']}\n"
                    f"     {(cl.get('summary') or '')[:140]}"
                )

        inactive = archive.get("inactive_claims", [])
        if inactive:
            arch.append("[Inactive Claims — No Recent Support]")
            for i, cl in enumerate(inactive, 1):
                last = _age_label(cl.get("last_validated_at") or cl.get("updated_at"))
                arch.append(f"  {i}. [INACTIVE · {last}] {cl['statement']}")

        old_snaps = archive.get("old_snapshots", [])
        if old_snaps:
            arch.append("[Earlier Snapshots]")
            for snap in old_snaps:
                snap_date = (snap.get("window_end") or snap.get("created_at") or "")[:10]
                arch.append(f"  [{snap_date}] {snap.get('summary_text', '')[:300]}")

        if arch:
            sections["archive"] = "\n".join(arch)

    return sections


# ── Vector supplement ──────────────────────────────────────────────────────────

def _needs_vector_supplement(current: dict, intent: dict, total_nodes: int = 0) -> bool:
    """True when DB data is too thin to answer reliably, or archive mode is active.

    If the combined structured retrieval across all layers already yielded enough
    nodes, skip vector supplement even if current_state alone is thin.
    """
    if intent.get("needs_archive"):
        return True
    # If any layer already returned substantial data, don't pile on with vectors
    if total_nodes >= 5:
        return False
    thin_events = len(current.get("active_events", [])) < DB_THIN_EVENT_THRESHOLD
    thin_claims = len(current.get("fresh_claims", [])) < DB_THIN_CLAIM_THRESHOLD
    return thin_events and thin_claims


def _has_structured_context(
    current: dict,
    timeline: dict | None = None,
    archive: dict | None = None,
) -> bool:
    return any(
        (
            current.get("active_events"),
            current.get("fresh_claims"),
            current.get("stale_claims"),
            current.get("snapshot"),
            current.get("artifact"),
            timeline and timeline.get("timeline_events"),
            timeline and timeline.get("deltas"),
            timeline and timeline.get("claim_evolution"),
            archive and archive.get("superseded_claims"),
            archive and archive.get("inactive_claims"),
            archive and archive.get("old_snapshots"),
        )
    )


def _run_vector_supplement(
    query: str,
    topic_id: int | None,
    intent: dict,
) -> dict[str, list[dict]]:
    """Run scoped Chroma search based on intent; filter out inactive items unless archive mode."""
    where_filter = {"topic_id": str(topic_id)} if topic_id is not None else None

    if intent.get("needs_archive"):
        kinds = ["snapshots", "artifacts", "claims"]
    elif intent.get("needs_timeline"):
        kinds = ["snapshots", "events", "claims"]
    else:
        kinds = ["events", "claims"]

    hits = search_multi_collection(
        query, kinds, n_results_per_collection=MAX_VEC_PER_COLLECTION,
        where_filter=where_filter,
    )
    grouped: dict[str, list[dict]] = {
        "events": [], "claims": [], "snapshots": [], "artifacts": [],
    }
    for hit in hits:
        col = hit.get("collection", "")
        meta = hit.get("metadata", {})
        # Suppress inactive/archived from supplemental unless archive mode is active
        if not intent.get("needs_archive") and meta.get("status") in ("inactive", "archived"):
            continue
        if col.endswith("kb_hot_events"):
            grouped["events"].append(hit)
        elif col.endswith("kb_claims"):
            grouped["claims"].append(hit)
        elif col.endswith("kb_temporal_snapshots"):
            grouped["snapshots"].append(hit)
        elif col.endswith("kb_synthesis_artifacts"):
            grouped["artifacts"].append(hit)
    return grouped


def _format_vector_supplement(hits: dict[str, list[dict]]) -> str | None:
    parts: list[str] = []

    events = hits.get("events", [])[:MAX_VEC_PER_COLLECTION]
    if events:
        parts.append("[SUPPLEMENTAL — Vector-Matched Events]")
        for i, r in enumerate(events, 1):
            meta = r.get("metadata", {})
            status = meta.get("status") or meta.get("event_status") or "?"
            last = (meta.get("last_seen_at") or "")[:10]
            parts.append(
                f"  {i}. {meta.get('title', 'Untitled')} [status={status}, last={last}]\n"
                f"     {r['document'][:260]}"
            )

    claims = hits.get("claims", [])[:MAX_VEC_PER_COLLECTION]
    if claims:
        parts.append("[SUPPLEMENTAL — Vector-Matched Claims]")
        for i, r in enumerate(claims, 1):
            meta = r.get("metadata", {})
            parts.append(
                f"  {i}. {r['document'][:200]} [status={meta.get('status', '?')}]"
            )

    snaps = hits.get("snapshots", [])[:2]
    if snaps:
        parts.append("[SUPPLEMENTAL — Historical Snapshots]")
        for i, r in enumerate(snaps, 1):
            meta = r.get("metadata", {})
            parts.append(f"  {i}. [{meta.get('date', '?')}] {r['document'][:300]}")

    artifacts = hits.get("artifacts", [])[:2]
    if artifacts:
        parts.append("[SUPPLEMENTAL — Synthesis Artifacts]")
        for i, r in enumerate(artifacts, 1):
            parts.append(f"  {i}. {r['document'][:320]}")

    return "\n".join(parts) if parts else None


# ── Context composer ───────────────────────────────────────────────────────────

def _truncate_text(text: str | None, limit: int) -> str:
    value = (text or "").strip()
    if len(value) <= limit:
        return value
    return value[: max(limit - 3, 0)].rstrip() + "..."


def compose_answer_context(
    sections: dict[str, str],
    topic_preamble: str | None = None,
    article_context: str | None = None,
    vector_supplement: str | None = None,
) -> str:
    parts: list[str] = []

    if topic_preamble:
        parts.append(topic_preamble)

    if article_context:
        parts.append(
            f"[Current article context]\n{_truncate_text(article_context, ARTICLE_CONTEXT_MAX_CHARS)}"
        )

    if sections.get("current"):
        parts.append("=== CURRENT STATE ===\n" + sections["current"])

    if sections.get("timeline"):
        parts.append("=== RECENT EVOLUTION ===\n" + sections["timeline"])

    if sections.get("archive"):
        parts.append(
            "=== HISTORICAL BACKGROUND (treat as background only) ===\n"
            + sections["archive"]
        )

    if vector_supplement:
        parts.append(vector_supplement)

    return _truncate_text("\n\n".join(p for p in parts if p.strip()), FINAL_CONTEXT_MAX_CHARS)


# ── Topic name helper ──────────────────────────────────────────────────────────

_topic_name_cache: dict[int, str] = {}


def _get_topic_name(topic_id: int) -> str:
    if topic_id not in _topic_name_cache:
        for t in get_topics():
            _topic_name_cache[t["id"]] = t.get("name", "")
    return _topic_name_cache.get(topic_id, "")


# ── Main entry point ───────────────────────────────────────────────────────────

def chat_stream_with_status(
    message: str,
    article_context: str | None = None,
    topic_id: int | None = None,
    history: list[dict] | None = None,
):
    """Yield status dicts and text chunks interleaved.

    The pipeline is fully automatic: users just send a question.  The system
    decides which knowledge layers to activate, retrieves structured data from
    the database first, resolves freshness/conflicts, supplements with vector
    search only when DB data is thin, and finally streams the LLM answer.
    """
    yield {"status": "searching_knowledge_base"}

    # ── 1. Classify query intent ──────────────────────────────────────────────
    intent = classify_query_intent(message, article_context)

    # Build route segments list and human-readable labels
    _LAYER_LABELS: dict[str, str] = {
        "current_state": "Current state",
        "timeline": "Timeline",
        "archive": "Historical background",
    }
    route_segments: list[str] = []
    if intent["needs_current_state"]:
        route_segments.append("current_state")
    if intent["needs_timeline"]:
        route_segments.append("timeline")
    if intent["needs_archive"]:
        route_segments.append("archive")

    route_label = (
        " → ".join(_LAYER_LABELS[s] for s in route_segments)
        if route_segments
        else "General retrieval"
    )

    yield {
        "trace": {
            "kind": "intent",
            "label": "Classify question",
            "state": "done",
            "meta": {
                "needs_current_state": intent["needs_current_state"],
                "needs_timeline": intent["needs_timeline"],
                "needs_archive": intent["needs_archive"],
                "time_window_days": intent["time_window_days"],
                # kept for backward compat
                "strategy_label": route_label,
                # new: explicit route info for UI
                "route_segments": route_segments,
                "route_label": route_label,
            }
        }
    }

    # ── 2. DB-first structured retrieval ──────────────────────────────────────
    current_data: dict = {}
    timeline_data: dict | None = None
    archive_data: dict | None = None

    if topic_id is not None:
        if intent["needs_current_state"]:
            current_data = retrieve_current_state(topic_id)
        if intent["needs_timeline"]:
            timeline_data = retrieve_timeline_context(topic_id, intent["time_window_days"])
        if intent["needs_archive"]:
            archive_data = retrieve_archive_context(topic_id)

    nodes = []
    if current_data:
        for ev in current_data.get("active_events", []):
            nodes.append({"id": f"event:{ev['id']}", "type": "event", "title": ev['title'], "status": "active"})
        for cl in current_data.get("fresh_claims", []):
            nodes.append({"id": f"claim:{cl['id']}", "type": "claim", "title": cl['statement'], "status": "fresh"})
        for cl in current_data.get("stale_claims", []):
            nodes.append({"id": f"claim:{cl['id']}", "type": "claim", "title": cl['statement'], "status": "stale"})
        if current_data.get("snapshot"):
            snap = current_data["snapshot"]
            nodes.append({"id": f"snapshot:{snap['id']}", "type": "snapshot", "title": "最新分析快照", "status": "active"})
        if current_data.get("artifact"):
            art = current_data["artifact"]
            nodes.append({"id": f"artifact:{art['id']}", "type": "artifact", "title": "全局概览", "status": "active"})
    
    if timeline_data:
        for ev in timeline_data.get("timeline_events", []):
            nodes.append({"id": f"event:{ev['id']}", "type": "event", "title": ev['title'], "status": "timeline"})
        for d in timeline_data.get("deltas", []):
            nodes.append({"id": f"delta:{d['id']}", "type": "snapshot", "title": "快照增量", "status": "timeline"})
        for e in timeline_data.get("claim_evolution", []):
            nodes.append({"id": f"evo:{e['id']}", "type": "claim", "title": e.get('reason', '')[:50] or "判断演化", "status": "timeline"})
            
    if archive_data:
        for cl in archive_data.get("superseded_claims", []):
            nodes.append({"id": f"claim:{cl['id']}", "type": "claim", "title": cl['statement'], "status": "superseded"})
        for cl in archive_data.get("inactive_claims", []):
            nodes.append({"id": f"claim:{cl['id']}", "type": "claim", "title": cl['statement'], "status": "inactive"})
            
    seen_ids = set()
    unique_nodes = []
    for n in nodes:
        if n["id"] not in seen_ids:
            seen_ids.add(n["id"])
            unique_nodes.append(n)

    # Track which retrieval layers actually returned data (for UI)
    retrieval_layers: list[str] = []
    hit_counts: dict[str, int] = {}
    if current_data:
        retrieval_layers.append("current_state")
        hit_counts["current_state"] = (
            len(current_data.get("active_events", []))
            + len(current_data.get("fresh_claims", []))
            + len(current_data.get("stale_claims", []))
        )
    if timeline_data:
        retrieval_layers.append("timeline")
        hit_counts["timeline"] = (
            len(timeline_data.get("timeline_events", []))
            + len(timeline_data.get("deltas", []))
            + len(timeline_data.get("claim_evolution", []))
        )
    if archive_data:
        retrieval_layers.append("archive")
        hit_counts["archive"] = (
            len(archive_data.get("superseded_claims", []))
            + len(archive_data.get("inactive_claims", []))
        )

    yield {
        "trace": {
            "kind": "kb_hits",
            "label": "Knowledge base hits",
            "state": "done",
            "nodes": unique_nodes,
            "meta": {
                "retrieval_layers": retrieval_layers,
                "hit_counts": hit_counts,
                "total_nodes": len(unique_nodes),
            },
        }
    }

    # ── 3. Freshness resolution ────────────────────────────────────────────────
    sections = resolve_freshness_conflicts(current_data, timeline_data, archive_data)

    # ── 4. Supplemental vector search (only when DB is thin) ──────────────────
    vector_supplement_text: str | None = None
    has_structured_context = _has_structured_context(current_data, timeline_data, archive_data)
    should_use_vector_supplement = (
        topic_id is not None
        and has_structured_context
        and _needs_vector_supplement(current_data, intent, len(unique_nodes))
    )

    if should_use_vector_supplement:
        yield {
            "trace": {
                "kind": "vector_supplement",
                "label": "Vector supplement",
                "state": "running",
                "meta": {"used": True},
            }
        }
        search_query = message
        if article_context:
            for line in (article_context or "").splitlines():
                if line.startswith("Title:"):
                    search_query = f"{line[6:].strip()} {message}"
                    break
        vec_hits = _run_vector_supplement(search_query, topic_id, intent)
        vector_supplement_text = _format_vector_supplement(vec_hits)
        _vec_used = bool(vector_supplement_text)
        yield {
            "trace": {
                "kind": "vector_supplement",
                "label": "Vector supplement",
                "state": "done" if _vec_used else "skipped",
                "meta": {"used": _vec_used},
            }
        }
    else:
        _vec_used = False
        skip_reason = "no_structured_context" if topic_id is not None and not has_structured_context else "not_needed"
        yield {
            "trace": {
                "kind": "vector_supplement",
                "label": "Vector supplement",
                "state": "skipped",
                "meta": {"used": False, "reason": skip_reason},
            }
        }

    # ── 5. Web search (last resort when both DB and vector are empty) ─────────
    web_text: str | None = None
    if not sections and not vector_supplement_text:
        yield {"status": "searching_web"}
        yield {
            "trace": {
                "kind": "web_fallback",
                "label": "Live web search",
                "state": "running",
                "meta": {"used": True},
            }
        }
        try:
            web = web_search(message, max_results=3)
            if web:
                web_lines = ["[Live web search results]"]
                for i, r in enumerate(web, 1):
                    web_lines.append(
                        f"  [Web-{i}] {r['title']} ({r['url']})\n"
                        f"  {_truncate_text(r['content'], 180)}"
                    )
                web_text = "\n".join(web_lines)
            _web_used = bool(web_text)
            yield {
                "trace": {
                    "kind": "web_fallback",
                    "label": "Live web search",
                    "state": "done" if _web_used else "skipped",
                    "meta": {"used": _web_used},
                }
            }
        except Exception:
            _web_used = False
            yield {
                "trace": {
                    "kind": "web_fallback",
                    "label": "Live web search",
                    "state": "skipped",
                    "meta": {"used": False},
                }
            }
    else:
        _web_used = False
        yield {
            "trace": {
                "kind": "web_fallback",
                "label": "Live web search",
                "state": "skipped",
                "meta": {"used": False},
            }
        }

    # ── 6. Compose context & stream answer ────────────────────────────────────
    # Build the final actual route label based on what was really executed
    _LAYER_LABELS_LOCAL: dict[str, str] = {
        "current_state": "Current state",
        "timeline": "Timeline",
        "archive": "Historical background",
    }
    final_route_parts: list[str] = []
    if retrieval_layers:
        kb_part = " + ".join(_LAYER_LABELS_LOCAL[l] for l in retrieval_layers)
        final_route_parts.append(f"Knowledge base ({kb_part})")
    if _vec_used:
        final_route_parts.append("Vector supplement")
    if _web_used:
        final_route_parts.append("Web search")
    if not final_route_parts:
        final_route_parts.append("General retrieval")
    final_route_parts.append("Generate answer")
    final_route_label = " → ".join(final_route_parts)

    yield {"status": "generating"}
    yield {
        "trace": {
            "kind": "answer_generation",
            "label": "Generate answer",
            "state": "running",
            "meta": {
                "final_route_label": final_route_label,
                "retrieval_layers": retrieval_layers,
                "vec_used": _vec_used,
                "web_used": _web_used,
            },
        }
    }

    preamble: str | None = None
    if topic_id is not None:
        topic_name = _get_topic_name(topic_id)
        if topic_name:
            preamble = f"[Topic: {topic_name}]"

    all_supplement = "\n\n".join(p for p in [vector_supplement_text, web_text] if p)
    ctx = compose_answer_context(
        sections,
        topic_preamble=preamble,
        article_context=article_context,
        vector_supplement=all_supplement or None,
    )

    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    if history:
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

    # ── 7. Emit structured sources for the UI source bar ─────────────────────
    sources: list[dict] = []
    seen_source_ids: set[str] = set()

    def _add_source(sid: str, title: str, url: str | None, kind: str) -> None:
        if sid not in seen_source_ids:
            seen_source_ids.add(sid)
            sources.append({"id": sid, "title": title, "url": url or "", "type": kind})

    if current_data:
        for ev in current_data.get("active_events", [])[:6]:
            _add_source(
                f"event:{ev['id']}",
                ev.get("title", "")[:80],
                ev.get("canonical_url") or ev.get("url"),
                "event",
            )
        if current_data.get("snapshot"):
            snap = current_data["snapshot"]
            _add_source(f"snapshot:{snap['id']}", "Latest analysis snapshot", None, "snapshot")
        if current_data.get("artifact"):
            art = current_data["artifact"]
            _add_source(f"artifact:{art['id']}", "Global overview", None, "artifact")
    if timeline_data:
        for ev in timeline_data.get("timeline_events", [])[:4]:
            _add_source(
                f"event:{ev['id']}",
                ev.get("title", "")[:80],
                ev.get("canonical_url") or ev.get("url"),
                "event",
            )
    if web_text:
        _add_source("web:0", "Live web search results", None, "web")

    if sources:
        yield {"sources": sources}

    yield from llm_chat_stream(messages, temperature=0.5)

    # Signal that answer generation is complete so the UI can stop the spinner
    yield {
        "trace": {
            "kind": "answer_generation",
            "label": "Generate answer",
            "state": "done",
            "meta": {
                "final_route_label": final_route_label,
            },
        }
    }
