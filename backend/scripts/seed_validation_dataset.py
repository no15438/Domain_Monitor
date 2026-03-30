import json
import sqlite3
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from config import settings
from claim_lifecycle import evaluate_claim_lifecycle
from database import (
    add_claim_evolution,
    create_topic,
    get_active_claims,
    get_claims_v2,
    get_events_v2,
    get_snapshot_deltas,
    get_synthesis_artifact,
    get_temporal_snapshots,
    init_db,
    insert_raw_news,
    list_evidence_sets,
    replace_event_sources,
    replace_synthesis_artifact,
    save_snapshot_delta,
    save_temporal_snapshot,
    update_topic,
    upsert_claim,
    upsert_evidence_set,
    upsert_event,
)
from vector_store import _rebuild_artifact_collection, _rebuild_snapshot_collection, add_artifact_document, add_claim_document, add_event_document, add_evidence_document


FIXTURE_PATH = BACKEND_DIR / "fixtures" / "validation_dataset.json"


def _db_path() -> str:
    raw = settings.database_path
    if Path(raw).is_absolute():
        return raw
    return str((BACKEND_DIR / raw).resolve())


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    return conn


def _load_fixture() -> dict:
    with FIXTURE_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def _get_or_create_topic(topic_name: str, color: str) -> int:
    conn = _conn()
    row = conn.execute("SELECT id, is_active FROM topics WHERE name = ?", (topic_name,)).fetchone()
    conn.close()
    if row:
        if not row["is_active"]:
            conn = _conn()
            conn.execute("UPDATE topics SET is_active = 1, color = ? WHERE id = ?", (color, row["id"]))
            conn.commit()
            conn.close()
        return int(row["id"])
    topic_id = create_topic(topic_name, color=color)
    if topic_id is None:
        raise RuntimeError(f"Unable to create topic: {topic_name}")
    return int(topic_id)


def _purge_topic_lineage(topic_id: int):
    conn = _conn()
    snapshot_rows = conn.execute("SELECT id FROM temporal_snapshots WHERE topic_id = ?", (topic_id,)).fetchall()
    snapshot_ids = [row["id"] for row in snapshot_rows]
    artifact_rows = conn.execute("SELECT id FROM synthesis_artifacts WHERE topic_id = ?", (topic_id,)).fetchall()
    artifact_ids = [row["id"] for row in artifact_rows]
    event_rows = conn.execute("SELECT id FROM events_v2 WHERE topic_id = ?", (topic_id,)).fetchall()
    event_ids = [row["id"] for row in event_rows]

    if artifact_ids:
        conn.executemany("DELETE FROM artifact_sources WHERE artifact_id = ?", [(artifact_id,) for artifact_id in artifact_ids])
    conn.execute("DELETE FROM synthesis_artifacts WHERE topic_id = ?", (topic_id,))

    if snapshot_ids:
        conn.executemany("DELETE FROM snapshot_events WHERE snapshot_id = ?", [(snapshot_id,) for snapshot_id in snapshot_ids])
        conn.executemany("DELETE FROM snapshot_claims WHERE snapshot_id = ?", [(snapshot_id,) for snapshot_id in snapshot_ids])
    conn.execute("DELETE FROM snapshot_deltas WHERE topic_id = ?", (topic_id,))
    conn.execute("DELETE FROM temporal_snapshots WHERE topic_id = ?", (topic_id,))

    conn.execute("DELETE FROM claim_evolution WHERE topic_id = ?", (topic_id,))
    conn.execute("DELETE FROM claims WHERE topic_id = ?", (topic_id,))
    conn.execute("DELETE FROM evidence_sets WHERE topic_id = ?", (topic_id,))
    if event_ids:
        conn.executemany("DELETE FROM event_sources WHERE event_id = ?", [(event_id,) for event_id in event_ids])
    conn.execute("DELETE FROM events_v2 WHERE topic_id = ?", (topic_id,))
    conn.execute("DELETE FROM raw_news WHERE topic_id = ?", (topic_id,))
    conn.commit()
    conn.close()


def _seed_raw_news(topic_id: int, fixture: dict):
    rows = []
    for item in fixture["raw_news"]:
        row = dict(item)
        row["topic_id"] = topic_id
        row["metadata_json"] = json.dumps(row.pop("metadata", {}), ensure_ascii=False)
        rows.append(row)
    insert_raw_news(rows)


def _seed_events(topic_id: int, fixture: dict):
    for event in fixture["events"]:
        upsert_event(
            topic_id=topic_id,
            event_id=event["id"],
            event_key=event["event_key"],
            title=event["title"],
            summary=event["summary"],
            status=event["status"],
            canonical_article_id=event.get("canonical_article_id"),
            first_seen_at=event.get("first_seen_at"),
            last_seen_at=event.get("last_seen_at"),
            novelty_window_end=event.get("novelty_window_end"),
            stability_score=event.get("stability_score", 0.0),
            fact_confidence=event.get("fact_confidence", 0.0),
            supersedes_event_id=event.get("supersedes_event_id"),
            metadata=event.get("metadata", {}),
        )
        replace_event_sources(
            event["id"],
            [
                {
                    **source,
                    "metadata_json": json.dumps(source.get("metadata", {}), ensure_ascii=False),
                }
                for source in event.get("sources", [])
            ],
        )
        add_event_document(
            event["id"],
            event.get("vector_text") or event["summary"],
            {
                "topic_id": str(topic_id),
                "title": event["title"],
                "event_status": event["status"],
                "source": event.get("metadata", {}).get("source", "fixture"),
            },
        )


def _seed_claims(topic_id: int, fixture: dict):
    for claim in fixture["claims"]:
        upsert_claim(
            topic_id=topic_id,
            claim_id=claim["id"],
            statement=claim["statement"],
            claim_type=claim.get("claim_type", "fact"),
            summary=claim.get("summary", ""),
            status=claim.get("status", "active"),
            supporting_evidence_ids=[],
            supersedes_claim_id=claim.get("supersedes_claim_id"),
            decay_policy=claim.get("decay_policy", "medium"),
            staleness_status=claim.get("staleness_status", "fresh"),
            metadata=claim.get("metadata", {}),
        )

    evidence_by_claim: dict[str, list[str]] = {}
    for evidence in fixture["evidence_sets"]:
        evidence_by_claim.setdefault(evidence["claim_id"], []).append(evidence["id"])

    for claim in fixture["claims"]:
        upsert_claim(
            topic_id=topic_id,
            claim_id=claim["id"],
            statement=claim["statement"],
            claim_type=claim.get("claim_type", "fact"),
            summary=claim.get("summary", ""),
            status=claim.get("status", "active"),
            supporting_evidence_ids=evidence_by_claim.get(claim["id"], []),
            supersedes_claim_id=claim.get("supersedes_claim_id"),
            decay_policy=claim.get("decay_policy", "medium"),
            staleness_status=claim.get("staleness_status", "fresh"),
            metadata=claim.get("metadata", {}),
        )
        add_claim_document(
            claim["id"],
            claim.get("vector_text") or claim["statement"],
            {
                "topic_id": str(topic_id),
                "claim_type": claim.get("claim_type", "fact"),
                "status": claim.get("status", "active"),
            },
        )

    for relation in fixture.get("claim_evolution", []):
        add_claim_evolution(
            topic_id=topic_id,
            claim_id=relation["claim_id"],
            previous_claim_id=relation.get("previous_claim_id"),
            relation_type=relation["relation_type"],
            reason=relation.get("reason", ""),
            metadata=relation.get("metadata", {}),
        )


def _seed_evidence(topic_id: int, fixture: dict):
    for evidence in fixture["evidence_sets"]:
        upsert_evidence_set(
            evidence_id=evidence["id"],
            topic_id=topic_id,
            event_id=evidence["event_id"],
            claim_id=evidence["claim_id"],
            title=evidence["title"],
            summary=evidence["summary"],
            evidence_type=evidence.get("evidence_type", "fact"),
            stance=evidence.get("stance", "supporting"),
            confidence=evidence.get("confidence", 0.0),
            freshness_half_life=evidence.get("freshness_half_life", 7.0),
            review_state=evidence.get("review_state", "machine_only"),
            supporting_event_ids=evidence.get("supporting_event_ids", []),
            contradicting_event_ids=evidence.get("contradicting_event_ids", []),
            metadata=evidence.get("metadata", {}),
        )
        add_evidence_document(
            evidence["id"],
            evidence.get("vector_text") or evidence["summary"],
            {
                "topic_id": str(topic_id),
                "title": evidence["title"],
                "claim_id": evidence["claim_id"],
                "url": evidence.get("metadata", {}).get("url", ""),
            },
        )


def _seed_snapshots_and_deltas(topic_id: int, topic_name: str, fixture: dict) -> tuple[dict[str, int], list[int]]:
    snapshot_ids: dict[str, int] = {}
    for snapshot in fixture["snapshots"]:
        snapshot_id = save_temporal_snapshot(
            topic_id=topic_id,
            summary_text=snapshot["summary_text"],
            stats_metadata=json.dumps(snapshot.get("stats_metadata", {}), ensure_ascii=False),
            window_type=snapshot.get("window_type", "daily"),
            window_start=snapshot.get("window_start"),
            window_end=snapshot.get("window_end"),
            snapshot_status=snapshot.get("snapshot_status", "final"),
            event_ids=snapshot.get("event_ids", []),
            claim_ids=snapshot.get("claim_ids", []),
        )
        snapshot_ids[snapshot["key"]] = snapshot_id

    _rebuild_snapshot_collection()

    delta_ids: list[int] = []
    for delta in fixture.get("snapshot_deltas", []):
        delta_id = save_snapshot_delta(
            topic_id=topic_id,
            from_snapshot_id=snapshot_ids.get(delta.get("from_key")),
            to_snapshot_id=snapshot_ids[delta["to_key"]],
            change_summary=delta["change_summary"],
            new_event_ids=delta.get("new_event_ids", []),
            resolved_event_ids=delta.get("resolved_event_ids", []),
            strengthened_claim_ids=delta.get("strengthened_claim_ids", []),
            weakened_claim_ids=delta.get("weakened_claim_ids", []),
            superseded_claim_ids=delta.get("superseded_claim_ids", []),
            metadata=delta.get("metadata", {}),
        )
        delta_ids.append(delta_id)

    _rebuild_snapshot_collection()
    return snapshot_ids, delta_ids


def _seed_artifacts(topic_id: int, fixture: dict, snapshot_ids: dict[str, int], delta_ids: list[int]):
    for artifact in fixture.get("artifacts", []):
        artifact_id = replace_synthesis_artifact(
            topic_id=topic_id,
            artifact_type=artifact["artifact_type"],
            title=artifact["title"],
            content=artifact["content"],
            status=artifact.get("status", "final"),
            metadata=artifact.get("metadata", {}),
            source_snapshot_ids=[snapshot_ids[key] for key in artifact.get("source_snapshot_keys", [])],
            source_delta_ids=[delta_ids[index] for index in artifact.get("source_delta_indexes", [])],
            source_claim_ids=artifact.get("source_claim_ids", []),
        )
        add_artifact_document(
            artifact_id,
            artifact.get("vector_text") or artifact["content"],
            {
                "topic_id": str(topic_id),
                "artifact_type": artifact["artifact_type"],
                "status": artifact.get("status", "final"),
                "generated_at": "fixture",
            },
        )
    _rebuild_artifact_collection()


def main():
    init_db(_db_path())
    fixture = _load_fixture()
    topic_cfg = fixture["topic"]
    topic_id = _get_or_create_topic(topic_cfg["name"], topic_cfg["color"])

    update_topic(
        topic_id,
        color=topic_cfg["color"],
        research_brief=topic_cfg.get("research_brief", ""),
        research_config=json.dumps(topic_cfg.get("research_config", {}), ensure_ascii=False),
        pipeline_config=json.dumps(topic_cfg.get("pipeline_config", {}), ensure_ascii=False),
    )
    _purge_topic_lineage(topic_id)

    _seed_raw_news(topic_id, fixture)
    _seed_events(topic_id, fixture)
    _seed_claims(topic_id, fixture)
    _seed_evidence(topic_id, fixture)
    lifecycle_audit = evaluate_claim_lifecycle(topic_id, source="seed_validation_dataset")
    snapshot_ids, delta_ids = _seed_snapshots_and_deltas(topic_id, topic_cfg["name"], fixture)
    _seed_artifacts(topic_id, fixture, snapshot_ids, delta_ids)

    summary = {
        "topic_id": topic_id,
        "topic_name": topic_cfg["name"],
        "raw_news": len(fixture["raw_news"]),
        "events": len(get_events_v2(topic_id, limit=100)),
        "evidence_sets": len(list_evidence_sets(topic_id, limit=100)),
        "claims": len(get_claims_v2(topic_id, limit=100)),
        "snapshots": len(get_temporal_snapshots(topic_id, limit=100)),
        "snapshot_deltas": len(get_snapshot_deltas(topic_id, limit=100)),
        "global_overview_ready": bool(get_synthesis_artifact(topic_id, "global_overview")),
        "evolution_report_ready": bool(get_synthesis_artifact(topic_id, "evolution_report")),
        "lifecycle_updated_claims": lifecycle_audit["updated_claims"],
        "lifecycle_audit": lifecycle_audit["audit"],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
