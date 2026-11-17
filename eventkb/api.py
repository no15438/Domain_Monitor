"""Reusable FastAPI adapter, with a standalone app that never loads legacy code."""
from pathlib import Path
import sqlite3
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from .query import query_projection
from .store import Store

ROOT = Path(__file__).resolve().parent.parent
LOCAL_ORIGINS = {f"http://{host}:{port}" for host in ("localhost", "127.0.0.1")
                 for port in (3000, 3001, 3870, 8770)}


def boundary(request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    if request.url.hostname not in request.app.state.event_memory_hosts:
        raise HTTPException(403, "Event memory is available on localhost only")
    if request.method != "GET":
        origin = request.headers.get("origin")
        allowed = request.app.state.event_memory_origins | {str(request.base_url).rstrip("/")}
        if origin and origin not in allowed:
            raise HTTPException(403, "Cross-origin write rejected")


def get_store(request: Request) -> Store:
    return request.app.state.event_memory_store


DB = Annotated[Store, Depends(get_store)]
router = APIRouter(prefix="/api/event-memory", tags=["event-memory"], dependencies=[Depends(boundary)])


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class EventInput(StrictModel):
    event_id: str
    topic: str = Field(min_length=1)
    identity_key: str
    title: str
    kind: str = "event"


class EvidenceInput(StrictModel):
    source_key: str
    revision: str
    publisher: str
    url: str
    published_at: str = ""
    body: str


class AssertionInput(StrictModel):
    topic: str = Field(min_length=1)
    field: str
    value: Any
    valid_from: str
    evidence_id: str
    message_key: str
    valid_to: str | None = None
    confidence: float = Field(default=1, ge=0, le=1)
    relation: Literal["observation", "transition", "correction"] = "observation"
    target_id: str | None = None
    reason: str = ""
    reviewed: bool = Field(default=False, strict=True)


class MemoryInput(StrictModel):
    topic: str = Field(min_length=1)
    importance: float = Field(ge=0, le=1)
    mode: Literal["active", "summary", "archived"] = "active"
    pinned: bool = Field(default=False, strict=True)
    reason: str = Field(min_length=1, max_length=2000)


def invoke(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except KeyError:
        raise HTTPException(404, "Event not found in this scope") from None
    except (ValueError, TypeError, sqlite3.IntegrityError) as exc:
        raise HTTPException(400, str(exc)) from None


def scoped(store, event_id, topic, known_at=None):
    state = invoke(store.state, event_id, known_at=known_at)
    if state["event"]["topic"] != topic:
        raise HTTPException(404, "Event not found in this scope")


@router.get("/health")
def health():
    return {"ok": True, "schema_version": 1, "model_used": False}


@router.get("/topics")
def topics(store: DB):
    with store.connection() as db:
        return {"topics": [row[0] for row in db.execute("SELECT DISTINCT topic FROM events ORDER BY topic")]}


@router.get("/query")
def query(store: DB, topic: str = Query(min_length=1), q: str = "", event_id: str | None = None,
          valid_at: str | None = None, known_at: str | None = None,
          include_archived: bool = False, limit: int = Query(default=20, ge=1, le=100)):
    return invoke(query_projection, store, topic=topic, query=q, event_id=event_id,
                  valid_at=valid_at, known_at=known_at, include_archived=include_archived, limit=limit)


@router.get("/events/{event_id}/state")
def state(event_id: str, store: DB, topic: str = Query(min_length=1),
          valid_at: str | None = None, known_at: str | None = None):
    scoped(store, event_id, topic, known_at)
    return invoke(store.state, event_id, valid_at=valid_at, known_at=known_at)


@router.get("/events/{event_id}/history")
def history(event_id: str, store: DB, topic: str = Query(min_length=1), known_at: str | None = None):
    scoped(store, event_id, topic, known_at)
    return invoke(store.history, event_id, known_at=known_at)


@router.post("/events", status_code=201)
def create_event(body: EventInput, store: DB):
    return invoke(store.create_event, **body.model_dump())


@router.post("/evidence", status_code=201)
def evidence(body: EvidenceInput, store: DB):
    return invoke(store.add_evidence, **body.model_dump())


@router.post("/events/{event_id}/assertions", status_code=201)
def assertion(event_id: str, body: AssertionInput, store: DB):
    scoped(store, event_id, body.topic)
    return invoke(store.assert_fact, event_id, **body.model_dump(exclude={"topic"}))


@router.post("/events/{event_id}/memory")
def memory(event_id: str, body: MemoryInput, store: DB):
    scoped(store, event_id, body.topic)
    return invoke(store.set_memory, event_id, **body.model_dump(exclude={"topic"}))


def install(app: FastAPI, *, store: Store, allowed_origins=None, allowed_hosts=None):
    app.state.event_memory_store = store
    app.state.event_memory_origins = set(LOCAL_ORIGINS if allowed_origins is None else allowed_origins)
    app.state.event_memory_hosts = set(allowed_hosts or ("localhost", "127.0.0.1", "testserver"))
    app.include_router(router)


def create_app(store: Store):
    app = FastAPI(title="Domain Monitor Event Memory", docs_url=None, redoc_url=None)
    install(app, store=store)
    return app
