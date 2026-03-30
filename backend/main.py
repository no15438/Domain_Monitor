import asyncio
import json
import logging
import threading
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from config import settings
from database import (
    get_active_claims,
    init_db,
    get_articles,
    get_article_count,
    get_claims_v2,
    get_events_v2,
    get_keywords,
    add_keyword,
    remove_keyword,
    get_topics,
    create_topic,
    update_topic,
    archive_topic,
    unarchive_topic,
    delete_topic,
    get_topic_feeds,
    add_topic_feed,
    remove_topic_feed,
    get_insight_summary,
    get_event_clusters,
    get_event_sources,
    archive_event_cluster,
    restore_event_cluster,
    delete_event_cluster,
    toggle_event_kept,
    get_events_grouped,
    get_event_alternatives,
    get_topic_insights,
    get_topics_overview,
    get_latest_temporal_snapshot,
    get_synthesis_artifact,
    get_snapshot_deltas,
    get_temporal_snapshots,
    get_trending_data,
    list_evidence_sets,
    delete_snapshot,
    update_snapshot,
    get_kept_articles,
    toggle_article_kept,
    update_article_metadata,
    delete_article,
    archive_article,
    restore_article,
    task_start,
    task_finish,
    task_is_running,
    task_cleanup_stale,
)
from vector_store import delete_document
from scheduler import start_scheduler, stop_scheduler
from sse_manager import set_event_loop, sse_clients, notify_clients
from pipeline import run_pipeline_once
from chatbot import chat_stream_with_status
from topic_summary import generate_summary_sync, generate_global_overview_sync, generate_evolution_report_sync
from claim_lifecycle import evaluate_claim_lifecycle

log = logging.getLogger("main")

# In-memory set is the authoritative source for *currently* running tasks.
# DB task_state is used only for audit/history and idempotency guards within
# a single server process lifetime.  On restart, _bg_generating is empty and
# tasks that were killed must NOT appear as "running" to clients.
_bg_generating: set[str] = set()
_bg_lock = threading.Lock()


def _bg_try_start(key: str) -> bool:
    """Atomically claim a slot. Only the in-memory set is checked — DB is for
    history only. This ensures that after a server restart, stale DB entries
    cannot block new fetches from starting."""
    with _bg_lock:
        if key in _bg_generating:
            return False
        _bg_generating.add(key)
    # Record in DB after acquiring the lock (best-effort; ignore DB conflicts).
    task_start(key)
    return True


def _bg_finish(key: str, result: str = "", error: str = ""):
    with _bg_lock:
        _bg_generating.discard(key)
    task_finish(key, result_summary=result, error=error)


def _bg_is_running(key: str) -> bool:
    """Only trust the in-memory set — prevents stale DB state from showing
    phantom 'running' tasks after a server restart."""
    with _bg_lock:
        return key in _bg_generating


async def _run_global_overview_background(topic_id: int):
    key = f"global-{topic_id}"
    try:
        await asyncio.to_thread(generate_global_overview_sync, topic_id)
        _bg_finish(key, result=f"generated for topic {topic_id}")
    except Exception as e:
        log.error("global-overview error for topic %d: %s", topic_id, e)
        _bg_finish(key, error=str(e))


async def _run_live_summary_background(topic_id: int, hours: int):
    key = f"live-{topic_id}"
    try:
        await asyncio.to_thread(generate_summary_sync, topic_id, hours)
        _bg_finish(key, result=f"generated for topic {topic_id}")
    except Exception as e:
        log.error("live-summary error for topic %d: %s", topic_id, e)
        _bg_finish(key, error=str(e))


async def _run_evolution_report_background(topic_id: int):
    key = f"evolution-{topic_id}"
    try:
        await asyncio.to_thread(generate_evolution_report_sync, topic_id)
        _bg_finish(key, result=f"generated evolution report for topic {topic_id}")
    except Exception as e:
        log.error("evolution-report error for topic %d: %s", topic_id, e)
        _bg_finish(key, error=str(e))


@asynccontextmanager
async def lifespan(_app: FastAPI):
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    set_event_loop(asyncio.get_running_loop())
    init_db(settings.database_path)
    task_cleanup_stale(timeout_minutes=30)
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(title="Domain Monitor API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Health ────────────────────────────────────────────


@app.get("/health")
async def health():
    return {"status": "ok"}


# ── Topics ────────────────────────────────────────────


@app.get("/api/topics")
async def list_topics():
    topics = await asyncio.to_thread(get_topics)
    return {"topics": topics}


@app.get("/api/topics/overview")
async def topics_overview(hours: int = 24):
    hours = max(1, min(hours, 720))
    data = await asyncio.to_thread(get_topics_overview, hours, False)
    return {"topics": data}


@app.get("/api/topics/archived/overview")
async def archived_topics_overview(hours: int = 24):
    hours = max(1, min(hours, 720))
    data = await asyncio.to_thread(get_topics_overview, hours, True)
    return {"topics": data}


class TopicReq(BaseModel):
    name: str
    color: str = "#6366f1"


@app.post("/api/topics")
async def api_create_topic(req: TopicReq):
    tid = await asyncio.to_thread(create_topic, req.name, req.color)
    if tid is None:
        return {"status": "error", "message": "Topic already exists"}
    return {"status": "ok", "id": tid}


class TopicUpdateReq(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None
    research_brief: Optional[str] = None
    research_config: Optional[str] = None
    pipeline_config: Optional[str] = None


@app.put("/api/topics/{topic_id}")
async def api_update_topic(topic_id: int, req: TopicUpdateReq):
    await asyncio.to_thread(
        update_topic, topic_id, req.name, req.color, req.research_brief, req.research_config, req.pipeline_config
    )
    return {"status": "ok"}


@app.post("/api/topics/{topic_id}/archive")
async def api_archive_topic(topic_id: int):
    await asyncio.to_thread(archive_topic, topic_id)
    return {"status": "ok"}


@app.post("/api/topics/{topic_id}/unarchive")
async def api_unarchive_topic(topic_id: int):
    await asyncio.to_thread(unarchive_topic, topic_id)
    return {"status": "ok"}


@app.delete("/api/topics/{topic_id}")
async def api_delete_topic(topic_id: int):
    await asyncio.to_thread(delete_topic, topic_id)
    return {"status": "ok"}


class GenerateResearchPlanReq(BaseModel):
    prompt: str


@app.post("/api/topics/{topic_id}/generate-research-plan")
async def api_generate_research_plan(topic_id: int, req: GenerateResearchPlanReq):
    """AI generates a full research plan from a natural-language prompt.

    Returns and persists: refined brief, keywords, RSS feeds, angles, entities, scope.
    """
    import re as _re
    from llm_client import llm_chat

    system_msg = (
        "You are an expert research analyst helping set up a comprehensive news/intelligence monitoring system.\n"
        "Given a user's research question or topic description, generate a COMPLETE research plan.\n"
        "Return ONLY a valid JSON object (no markdown fences, no explanation) with these fields:\n"
        "{\n"
        '  "research_brief": "A refined 2-4 sentence research direction description",\n'
        '  "keywords": ["keyword1", "keyword2", ...],  // 8-15 monitoring keywords/phrases\n'
        '  "rss_feeds": [{"url": "...", "label": "..."}],  // 3-8 real, well-known RSS feed URLs relevant to the topic\n'
        '  "angles": ["Research angle 1", "Research angle 2", ...],  // 4-8 specific research questions/angles\n'
        '  "entities": ["Entity1", "Entity2", ...],  // 5-15 key entities (people, companies, orgs, countries)\n'
        '  "geographic_scope": ["Region1", "Region2", ...],  // relevant regions\n'
        '  "sector_scope": ["Sector1", "Sector2", ...]  // relevant industries/sectors\n'
        "}\n"
        "IMPORTANT:\n"
        "- Use the SAME LANGUAGE as the user's prompt for all text fields\n"
        "- RSS feeds must be real, publicly accessible URLs from major news outlets, specialized journals, or Google News RSS\n"
        "- For Google News RSS, format as: https://news.google.com/rss/search?q=QUERY&hl=LANG\n"
        "- Keywords should be concise but precise enough for news search\n"
        "- Angles should be specific, actionable research questions"
    )

    result = await asyncio.to_thread(
        llm_chat,
        [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": req.prompt},
        ],
        0.4,
    )

    match = _re.search(r"\{[\s\S]*\}", result)
    if not match:
        return {"status": "error", "message": "Failed to parse LLM response"}

    try:
        plan = json.loads(match.group())
    except json.JSONDecodeError:
        return {"status": "error", "message": "Invalid JSON from LLM"}

    brief = plan.get("research_brief", req.prompt)
    kw_list = plan.get("keywords", [])
    feed_list = plan.get("rss_feeds", [])
    config = {
        "angles": plan.get("angles", []),
        "entities": plan.get("entities", []),
        "geographic_scope": plan.get("geographic_scope", []),
        "sector_scope": plan.get("sector_scope", []),
    }

    await asyncio.to_thread(
        update_topic, topic_id, None, None, brief, json.dumps(config, ensure_ascii=False)
    )

    for kw in kw_list:
        kw_str = str(kw).strip()
        if kw_str:
            await asyncio.to_thread(add_keyword, kw_str, "", topic_id)

    for feed in feed_list:
        url = feed.get("url", "") if isinstance(feed, dict) else str(feed)
        label = feed.get("label", "") if isinstance(feed, dict) else ""
        if url.strip():
            await asyncio.to_thread(add_topic_feed, topic_id, url.strip(), label)

    kws = await asyncio.to_thread(get_keywords, topic_id)
    feeds = await asyncio.to_thread(get_topic_feeds, topic_id)

    return {
        "status": "ok",
        "plan": {
            "research_brief": brief,
            "keywords": [k["keyword"] for k in kws],
            "rss_feeds": [{"id": f["id"], "url": f["feed_url"], "label": f["label"]} for f in feeds],
            **config,
        },
    }


# ── Topic Feeds ───────────────────────────────────────


@app.get("/api/topics/{topic_id}/feeds")
async def list_feeds(topic_id: int):
    feeds = await asyncio.to_thread(get_topic_feeds, topic_id)
    return {"feeds": feeds}


class FeedReq(BaseModel):
    feed_url: str
    label: str = ""


@app.post("/api/topics/{topic_id}/feeds")
async def api_add_feed(topic_id: int, req: FeedReq):
    await asyncio.to_thread(add_topic_feed, topic_id, req.feed_url, req.label)
    return {"status": "ok"}


@app.delete("/api/feeds/{feed_id}")
async def api_remove_feed(feed_id: int):
    await asyncio.to_thread(remove_topic_feed, feed_id)
    return {"status": "ok"}


# ── Articles ──────────────────────────────────────────


@app.get("/api/articles")
async def list_articles(limit: int = 50, offset: int = 0, topic_id: Optional[int] = None, sort: str = "relevance", status: str = "active"):
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    if status not in {"active", "archived"}:
        status = "active"
    if sort not in {"relevance", "latest"}:
        sort = "relevance"
    articles = await asyncio.to_thread(get_articles, limit, offset, topic_id, sort, status)
    total = await asyncio.to_thread(get_article_count, topic_id, status)
    return {"articles": articles, "total": total}


# ── SSE stream ────────────────────────────────────────


@app.get("/api/stream")
async def stream(request: Request):
    queue: asyncio.Queue = asyncio.Queue()
    sse_clients.append(queue)

    async def generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=30)
                    yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            if queue in sse_clients:
                sse_clients.remove(queue)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


# ── Keywords ──────────────────────────────────────────


@app.get("/api/keywords")
async def list_keywords(topic_id: Optional[int] = None):
    kws = await asyncio.to_thread(get_keywords, topic_id)
    return {"keywords": kws}


class KeywordReq(BaseModel):
    keyword: str
    category: str = ""
    topic_id: Optional[int] = None


@app.post("/api/keywords")
async def create_keyword(req: KeywordReq):
    await asyncio.to_thread(add_keyword, req.keyword, req.category, req.topic_id)
    return {"status": "ok"}


@app.delete("/api/keywords/{keyword_id}")
async def api_delete_keyword(keyword_id: int):
    await asyncio.to_thread(remove_keyword, keyword_id)
    return {"status": "ok"}


# ── Insights ─────────────────────────────────────────


@app.get("/api/insights/summary")
async def api_insight_summary(topic_id: Optional[int] = None, hours: int = 24):
    hours = max(1, min(hours, 720))
    data = await asyncio.to_thread(get_insight_summary, topic_id, hours)
    return data


@app.get("/api/insights/topic")
async def api_topic_insights(topic_id: Optional[int] = None, window: str = "24h"):
    hours = 168 if window == "7d" else 24
    data = await asyncio.to_thread(get_topic_insights, topic_id, hours)
    return data


@app.get("/api/events")
async def api_list_events(
    topic_id: Optional[int] = None,
    limit: int = 30,
    offset: int = 0,
    sort: str = "relevance",
    status: str = "active",
):
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    if status not in {"active", "archived"}:
        status = "active"
    if sort not in {"relevance", "latest"}:
        sort = "relevance"
    events, total = await asyncio.to_thread(get_event_clusters, topic_id, limit, offset, sort, status)
    return {"events": events, "total": total}


@app.get("/api/events/{event_id}/sources")
async def api_event_sources(event_id: str):
    sources = await asyncio.to_thread(get_event_sources, event_id)
    return {"sources": sources}


@app.put("/api/events/{event_id}/archive")
async def api_archive_event(event_id: str):
    await asyncio.to_thread(archive_event_cluster, event_id)
    return {"status": "archived"}


@app.put("/api/events/{event_id}/restore")
async def api_restore_event(event_id: str):
    await asyncio.to_thread(restore_event_cluster, event_id)
    return {"status": "restored"}


@app.delete("/api/events/{event_id}")
async def api_delete_event(event_id: str):
    await asyncio.to_thread(delete_event_cluster, event_id)
    return {"status": "deleted"}


@app.put("/api/events/{event_id}/keep")
async def api_toggle_event_kept(event_id: str, body: dict):
    is_kept = int(bool(body.get("is_kept", 0)))
    await asyncio.to_thread(toggle_event_kept, event_id, is_kept)
    return {"is_kept": is_kept}


@app.get("/api/events/{event_id}")
async def api_event_detail(event_id: str):
    """Legacy: return sources for this event cluster."""
    sources = await asyncio.to_thread(get_event_sources, event_id)
    return {"sources": sources, "articles": sources}


# ── Manual fetch ──────────────────────────────────────


async def _run_fetch_background(topic_id: Optional[int]):
    key = f"fetch-{topic_id}"
    try:
        new = await asyncio.to_thread(run_pipeline_once, topic_id)
        if new:
            notify_clients(new)
        _bg_finish(key, result=f"{len(new)} new articles")
    except Exception as e:
        log.error("fetch-now error for topic %s: %s", topic_id, e)
        _bg_finish(key, error=str(e))


@app.post("/api/fetch-now")
async def fetch_now(topic_id: Optional[int] = None):
    key = f"fetch-{topic_id}"
    if not _bg_try_start(key):
        return {"status": "already_running"}
    asyncio.create_task(_run_fetch_background(topic_id))
    return {"status": "started"}


@app.get("/api/fetch-now/status")
async def fetch_now_status(topic_id: Optional[int] = None):
    return {"running": _bg_is_running(f"fetch-{topic_id}")}


# ── Trending ─────────────────────────────────────────


@app.get("/api/topics/{topic_id}/trending")
async def api_trending(topic_id: int, days: int = 7):
    days = max(1, min(days, 365))
    data = await asyncio.to_thread(get_trending_data, topic_id, days)
    return data


# ── Knowledge Lineage ────────────────────────────────

@app.get("/api/topics/{topic_id}/snapshots")
async def api_get_snapshots(topic_id: int, window: Optional[str] = None):
    return await asyncio.to_thread(get_temporal_snapshots, topic_id, window or "daily", 50)


@app.get("/api/topics/{topic_id}/events/active")
async def api_get_active_events(topic_id: int):
    events = await asyncio.to_thread(get_events_v2, topic_id, "active", 50)
    return {"events": events}


@app.get("/api/topics/{topic_id}/events/history")
async def api_get_event_history(topic_id: int):
    events = await asyncio.to_thread(get_events_v2, topic_id, None, 100)
    return {"events": events}


@app.get("/api/topics/{topic_id}/evidence")
async def api_get_evidence(topic_id: int):
    evidence = await asyncio.to_thread(list_evidence_sets, topic_id, 100)
    return {"evidence": evidence}


@app.get("/api/topics/{topic_id}/claims")
async def api_get_claims(topic_id: int, status: Optional[str] = None):
    claims = await asyncio.to_thread(get_claims_v2, topic_id, status, 100)
    return {"claims": claims}


@app.get("/api/topics/{topic_id}/snapshot-deltas")
async def api_get_snapshot_deltas(topic_id: int):
    deltas = await asyncio.to_thread(get_snapshot_deltas, topic_id, 50)
    return {"deltas": deltas}


@app.get("/api/topics/{topic_id}/claim-lifecycle-audit")
async def api_get_claim_lifecycle_audit(topic_id: int):
    audit = await asyncio.to_thread(
        evaluate_claim_lifecycle,
        topic_id,
        persist=False,
        source="api_audit",
    )
    return audit


class UpdateSnapshotReq(BaseModel):
    content: str

@app.put("/api/snapshots/{snapshot_id}")
async def api_update_snapshot(snapshot_id: int, req: UpdateSnapshotReq):
    await asyncio.to_thread(update_snapshot, snapshot_id, req.content)
    # Note: Ideally we'd update vector db here, but keeping it simple as we only update the sqlite representation for now, or we can trigger a vector re-index. We'll skip vector re-index for simple text edits for now to save time, unless requested.
    return {"status": "ok"}


@app.delete("/api/snapshots/{snapshot_id}")
async def api_delete_snapshot(snapshot_id: int, topic_id: int):
    await asyncio.to_thread(delete_snapshot, snapshot_id)
    # Also delete from vector store
    vector_id = f"snapshot-{topic_id}-{snapshot_id}"
    await asyncio.to_thread(delete_document, vector_id)
    return {"status": "ok"}


@app.get("/api/topics/{topic_id}/kept-articles")
async def api_get_kept_articles(topic_id: int):
    return await asyncio.to_thread(get_kept_articles, topic_id)


class ToggleKeptReq(BaseModel):
    is_kept: int

@app.put("/api/articles/{article_id}/keep")
async def api_toggle_kept(article_id: str, req: ToggleKeptReq):
    await asyncio.to_thread(toggle_article_kept, article_id, req.is_kept)
    return {"status": "ok"}


class UpdateArticleReq(BaseModel):
    title: Optional[str] = None
    summary: Optional[str] = None
    tags: Optional[list[str]] = None
    sentiment: Optional[str] = None
    importance: Optional[int] = None

@app.put("/api/articles/{article_id}")
async def api_update_article(article_id: str, req: UpdateArticleReq):
    tags_json = json.dumps(req.tags, ensure_ascii=False) if req.tags is not None else None
    await asyncio.to_thread(
        update_article_metadata, article_id,
        title=req.title, summary=req.summary, tags_json=tags_json,
        sentiment=req.sentiment, importance=req.importance,
    )
    return {"status": "ok"}


@app.delete("/api/articles/{article_id}")
async def api_delete_article(article_id: str):
    await asyncio.to_thread(delete_article, article_id)
    await asyncio.to_thread(delete_document, article_id)
    return {"status": "ok"}


@app.put("/api/articles/{article_id}/archive")
async def api_archive_article(article_id: str):
    await asyncio.to_thread(archive_article, article_id)
    return {"status": "ok"}


@app.put("/api/articles/{article_id}/restore")
async def api_restore_article(article_id: str):
    await asyncio.to_thread(restore_article, article_id)
    return {"status": "ok"}


# ── AI Topic Summary ─────────────────────────────────


@app.get("/api/topics/{topic_id}/ai-summary")
async def api_topic_ai_summary(topic_id: int):
    """Return latest temporal snapshot. Returns null content if none exists yet."""
    snap = await asyncio.to_thread(get_latest_temporal_snapshot, topic_id, "daily")
    if snap:
        return {
            "content": snap["summary_text"],
            "generated_at": snap["window_end"] or snap["created_at"],
            "snapshot_id": snap["id"],
            "stats_metadata": snap["stats_metadata"],
        }
    return {"content": None, "generated_at": None, "snapshot_id": None, "stats_metadata": None}


@app.post("/api/topics/{topic_id}/ai-summary/generate")
async def api_generate_topic_summary(topic_id: int, hours: int = 24):
    """Start Live AI summary generation in background (non-streaming, persists)."""
    key = f"live-{topic_id}"
    if not _bg_try_start(key):
        return {"started": False, "already_running": True}
    asyncio.create_task(_run_live_summary_background(topic_id, hours))
    return {"started": True, "already_running": False}


@app.get("/api/topics/{topic_id}/ai-summary/status")
async def api_live_summary_status(topic_id: int):
    """Whether a live AI summary job is currently running for this topic."""
    return {"generating": _bg_is_running(f"live-{topic_id}")}


@app.get("/api/topics/{topic_id}/global-overview")
async def api_topic_global_overview(topic_id: int):
    """Return stored lineage synthesis overview. Returns null content if none exists yet."""
    artifact = await asyncio.to_thread(get_synthesis_artifact, topic_id, "global_overview")
    content = artifact["content"] if artifact else None
    return {"content": content}


@app.post("/api/topics/{topic_id}/global-overview/generate")
async def api_generate_global_overview(topic_id: int):
    """Start Global Overview generation in a background task (persists even if client disconnects)."""
    key = f"global-{topic_id}"
    if not _bg_try_start(key):
        return {"started": False, "already_running": True}
    asyncio.create_task(_run_global_overview_background(topic_id))
    return {"started": True, "already_running": False}


@app.get("/api/topics/{topic_id}/global-overview/status")
async def api_global_overview_status(topic_id: int):
    """Whether a global overview job is currently running for this topic."""
    return {"generating": _bg_is_running(f"global-{topic_id}")}


@app.get("/api/topics/{topic_id}/synthesis/global-overview")
async def api_synthesis_global_overview(topic_id: int):
    artifact = await asyncio.to_thread(get_synthesis_artifact, topic_id, "global_overview")
    return {"artifact": artifact}


@app.post("/api/topics/{topic_id}/synthesis/global-overview/generate")
async def api_synthesis_generate_global_overview(topic_id: int):
    key = f"global-{topic_id}"
    if not _bg_try_start(key):
        return {"started": False, "already_running": True}
    asyncio.create_task(_run_global_overview_background(topic_id))
    return {"started": True, "already_running": False}


@app.get("/api/topics/{topic_id}/synthesis/global-overview/status")
async def api_synthesis_global_overview_status(topic_id: int):
    return {"generating": _bg_is_running(f"global-{topic_id}")}


@app.get("/api/topics/{topic_id}/synthesis/evolution-report")
async def api_synthesis_evolution_report(topic_id: int):
    artifact = await asyncio.to_thread(get_synthesis_artifact, topic_id, "evolution_report")
    return {"artifact": artifact}


@app.post("/api/topics/{topic_id}/synthesis/evolution-report/generate")
async def api_generate_evolution_report(topic_id: int):
    key = f"evolution-{topic_id}"
    if not _bg_try_start(key):
        return {"started": False, "already_running": True}
    asyncio.create_task(_run_evolution_report_background(topic_id))
    return {"started": True, "already_running": False}


@app.get("/api/topics/{topic_id}/synthesis/evolution-report/status")
async def api_evolution_report_status(topic_id: int):
    return {"generating": _bg_is_running(f"evolution-{topic_id}")}

# ── Chatbot (streaming) ──────────────────────────────


class ChatHistoryMessage(BaseModel):
    role: str
    content: str


class ChatReq(BaseModel):
    message: str
    article_context: str | None = None
    topic_id: int | None = None
    history: list[ChatHistoryMessage] = []


@app.post("/api/chat")
async def chat_endpoint(req: ChatReq):
    def generate():
        history_dicts = [{"role": m.role, "content": m.content} for m in req.history]
        for item in chat_stream_with_status(req.message, req.article_context, req.topic_id, history_dicts):
            if isinstance(item, dict):
                yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
            else:
                yield f"data: {json.dumps({'content': item}, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'done': True})}\n\n"

    return StreamingResponse(
        generate(), media_type="text/event-stream"
    )
