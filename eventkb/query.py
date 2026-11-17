"""Build a time-scoped answer payload from authoritative projections only.

Evidence bodies, old summaries, vectors, chat history and article selections are
deliberately absent. Evidence metadata is a citation, never a second fact source.
"""
from .store import Store, timestamp


def query_projection(store: Store, *, topic, query="", event_id=None,
                     valid_at=None, known_at=None, include_archived=False, limit=20):
    now = timestamp(store.clock())
    effective, cutoff = timestamp(valid_at or now), timestamp(known_at or now)
    items = store.search(query, topic=topic, valid_at=effective, known_at=cutoff,
                         include_archived=include_archived)
    if event_id is not None:
        items = [item for item in items if item["event"]["id"] == event_id]
    total = len(items)
    results = []
    for item in items[:limit]:
        history = store.history(item["event"]["id"], known_at=cutoff)
        ids = {eid for field in item["fields"].values() for eid in field["evidence_ids"]}
        citations = [{key: ev[key] for key in ("id", "source_key", "revision", "publisher", "url",
                     "published_at", "recorded_at", "body_sha256")}
                     for ev in history["evidence"] if ev["id"] in ids]
        fields = {}
        for name, field in item["fields"].items():
            fields[name] = {key: field[key] for key in ("status", "value", "assertion_ids", "evidence_ids")}
            # Conflicting values are explicit alternatives, never a confirmed answer.
            fields[name]["alternatives"] = [{key: alt[key] for key in
                ("id", "value", "evidence_id", "confidence", "valid_from", "valid_to")}
                for alt in field["alternatives"]]
        results.append({"event": item["event"], "fields": fields,
                        "has_conflicts": item["has_conflicts"], "memory": item["memory"],
                        "retrieval": item["retrieval"], "citations": citations})
    return {"scope": {"topic": topic, "valid_at": effective, "known_at": cutoff,
                       "mode": "historical" if valid_at or known_at else "current",
                       "include_archived": include_archived},
            "query": query, "total": total, "truncated": total > limit, "results": results,
            "answer_basis": "projected_fields_only", "model_used": False}
