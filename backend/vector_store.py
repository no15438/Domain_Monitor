import logging
import os
import threading

import chromadb

from config import settings

log = logging.getLogger("vector_store")

COLLECTIONS = {
    "events": "kb_hot_events",
    "evidence": "kb_evidence_sets",
    "claims": "kb_claims",
    "snapshots": "kb_temporal_snapshots",
    "artifacts": "kb_synthesis_artifacts",
}

_client = None
_collections: dict[str, object] = {}
_write_lock = threading.Lock()  # chromadb HNSW is not thread-safe; serialise all writes


def _get_client():
    global _client
    if _client is None:
        os.makedirs(settings.chroma_persist_dir, exist_ok=True)
        _client = chromadb.PersistentClient(path=settings.chroma_persist_dir)
    return _client


def get_collection(name: str):
    if name not in _collections:
        client = _get_client()
        _collections[name] = client.get_or_create_collection(
            name=name, metadata={"hnsw:space": "cosine"}
        )
    return _collections[name]


def _reset_collection(name: str):
    with _write_lock:
        client = _get_client()
        try:
            client.delete_collection(name)
        except Exception:
            pass
        _collections.pop(name, None)
    return get_collection(name)


def _normalize_metadata(metadata: dict | None, doc_type: str) -> dict:
    meta = dict(metadata or {})
    meta.setdefault("doc_type", doc_type)
    return meta


def _upsert(collection_name: str, doc_id: str, text: str, metadata: dict | None = None, doc_type: str = "document"):
    with _write_lock:
        col = get_collection(collection_name)
        col.upsert(ids=[doc_id], documents=[text], metadatas=[_normalize_metadata(metadata, doc_type)])


def add_event_document(event_id: str, text: str, metadata: dict):
    _upsert(COLLECTIONS["events"], event_id, text, metadata, doc_type="event")


def add_evidence_document(evidence_id: str, text: str, metadata: dict):
    _upsert(COLLECTIONS["evidence"], evidence_id, text, metadata, doc_type="evidence")


def add_claim_document(claim_id: str, text: str, metadata: dict):
    _upsert(COLLECTIONS["claims"], claim_id, text, metadata, doc_type="claim")


def add_snapshot_document(snapshot_id: str, text: str, metadata: dict):
    _upsert(COLLECTIONS["snapshots"], snapshot_id, text, metadata, doc_type="snapshot")


def add_artifact_document(artifact_id: str, text: str, metadata: dict):
    _upsert(COLLECTIONS["artifacts"], artifact_id, text, metadata, doc_type="artifact")


def _rebuild_snapshot_collection():
    from database import get_temporal_snapshots, get_topics

    collection_name = COLLECTIONS["snapshots"]
    _reset_collection(collection_name)
    topics = get_topics()
    total = 0
    for topic in topics:
        topic_id = topic["id"]
        topic_name = topic.get("name", "")
        snapshots = get_temporal_snapshots(topic_id, window_type=None, limit=500)
        for snapshot in snapshots:
            snapshot_id = f"temporal-snapshot-{topic_id}-{snapshot['id']}"
            text = snapshot.get("summary_text", "") or ""
            if not text.strip():
                continue
            add_snapshot_document(
                snapshot_id,
                text,
                {
                    "topic_id": str(topic_id),
                    "topic_name": topic_name,
                    "snapshot_id": str(snapshot["id"]),
                    "window_type": snapshot.get("window_type", ""),
                    "window_end": snapshot.get("window_end", "") or "",
                    "status": snapshot.get("snapshot_status", ""),
                    "date": (snapshot.get("window_end") or snapshot.get("created_at") or "")[:10],
                },
            )
            total += 1
    log.warning("rebuilt snapshot collection with %d documents", total)


def _rebuild_artifact_collection():
    from database import get_synthesis_artifact, get_topics

    collection_name = COLLECTIONS["artifacts"]
    _reset_collection(collection_name)
    total = 0
    for topic in get_topics():
        topic_id = topic["id"]
        for artifact_type in ("global_overview", "evolution_report"):
            artifact = get_synthesis_artifact(topic_id, artifact_type)
            if not artifact or not (artifact.get("content") or "").strip():
                continue
            add_artifact_document(
                artifact["id"],
                artifact["content"],
                {
                    "topic_id": str(topic_id),
                    "artifact_type": artifact_type,
                    "status": artifact.get("status", ""),
                    "generated_at": artifact.get("generated_at", "") or "",
                },
            )
            total += 1
    log.warning("rebuilt artifact collection with %d documents", total)


def _rebuild_collection_for_query(collection_name: str):
    if collection_name == COLLECTIONS["snapshots"]:
        _rebuild_snapshot_collection()
        return
    if collection_name == COLLECTIONS["artifacts"]:
        _rebuild_artifact_collection()
        return


def delete_document(doc_id: str, collection_name: str | None = None):
    with _write_lock:
        if collection_name:
            get_collection(collection_name).delete(ids=[doc_id])
            return
        for name in COLLECTIONS.values():
            try:
                get_collection(name).delete(ids=[doc_id])
            except Exception:
                pass


def delete_vector_documents_for_topic(topic_id: int) -> None:
    """Remove KB vectors tagged with this topic_id from all collections."""
    tid = str(int(topic_id))
    with _write_lock:
        for name in COLLECTIONS.values():
            try:
                get_collection(name).delete(where={"topic_id": tid})
            except Exception as exc:
                log.warning("chroma delete where topic_id=%s in %s: %s", tid, name, exc)


def _query_collection(collection_name: str, query: str, n_results: int = 5, where_filter: dict | None = None) -> list[dict]:
    kwargs: dict = {"query_texts": [query]}
    if where_filter:
        kwargs["where"] = where_filter

    last_error = None
    for attempt in range(2):
        try:
            col = get_collection(collection_name)
            total = col.count()
            if total == 0:
                return []
            kwargs["n_results"] = min(n_results, total)
            results = col.query(**kwargs)
            items = []
            for i in range(len(results["ids"][0])):
                items.append(
                    {
                        "id": results["ids"][0][i],
                        "document": results["documents"][0][i],
                        "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                        "distance": results["distances"][0][i] if results["distances"] else 0,
                        "collection": collection_name,
                    }
                )
            return items
        except Exception as exc:
            last_error = exc
            _collections.pop(collection_name, None)
            if attempt == 0:
                _rebuild_collection_for_query(collection_name)
            log.warning(
                "query failed for collection %s on attempt %d: %s",
                collection_name,
                attempt + 1,
                exc,
            )
    log.error("query failed for collection %s after retry: %s", collection_name, last_error)
    return []


def search_collection(kind: str, query: str, n_results: int = 5, where_filter: dict | None = None) -> list[dict]:
    collection_name = COLLECTIONS.get(kind, kind)
    return _query_collection(collection_name, query, n_results=n_results, where_filter=where_filter)


def search_multi_collection(
    query: str,
    kinds: list[str],
    n_results_per_collection: int = 4,
    where_filter: dict | None = None,
) -> list[dict]:
    merged: list[dict] = []
    for kind in kinds:
        merged.extend(search_collection(kind, query, n_results=n_results_per_collection, where_filter=where_filter))
    return sorted(merged, key=lambda item: item.get("distance", 1))[: max(n_results_per_collection, 1) * max(len(kinds), 1)]
