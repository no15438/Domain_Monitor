import json
from datetime import datetime, timezone, timedelta

from database import (
    add_claim_evolution,
    get_claim_evolution,
    get_claims_v2,
    get_evidence_sets_for_claim,
    update_claim_lifecycle,
)
from vector_store import add_claim_document


ACTIVE_WINDOW_DAYS = {
    "fast": 3,
    "medium": 7,
    "slow": 21,
}

INACTIVE_WINDOW_DAYS = {
    "fast": 7,
    "medium": 21,
    "slow": 45,
}


def _parse_dt(raw: str | None) -> datetime | None:
    if not raw:
        return None
    value = str(raw).strip()
    if not value:
        return None
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(value, fmt)
                break
            except ValueError:
                dt = None
        if dt is None:
            return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _pick_latest_signal(claim: dict, evidence_rows: list[dict]) -> datetime | None:
    primary_candidates: list[datetime] = []
    fallback_candidates: list[datetime] = []
    for evidence in evidence_rows:
        metadata_raw = evidence.get("metadata_json") or evidence.get("metadata") or "{}"
        if isinstance(metadata_raw, str):
            try:
                metadata = json.loads(metadata_raw)
            except Exception:
                metadata = {}
        else:
            metadata = metadata_raw or {}
        for raw in (metadata.get("published_at"), metadata.get("last_seen_at")):
            parsed = _parse_dt(raw)
            if parsed:
                primary_candidates.append(parsed)
        for raw in (evidence.get("updated_at"), evidence.get("created_at")):
            parsed = _parse_dt(raw)
            if parsed:
                fallback_candidates.append(parsed)
    if primary_candidates:
        return max(primary_candidates)
    if fallback_candidates:
        return max(fallback_candidates)
    return _parse_dt(claim.get("last_refreshed_at") or claim.get("last_validated_at"))


def _build_claim_text(claim: dict) -> str:
    statement = claim.get("statement", "")
    summary = claim.get("summary", "")
    return f"{statement}\n{summary}".strip()


def evaluate_claim_lifecycle(
    topic_id: int,
    *,
    now: datetime | None = None,
    touched_claim_ids: list[str] | None = None,
    persist: bool = True,
    source: str = "scheduler",
) -> dict:
    now = now or datetime.now(timezone.utc)
    all_claims = get_claims_v2(topic_id, limit=500)
    if not all_claims:
        return {"topic_id": topic_id, "evaluated_claims": 0, "updated_claims": 0, "audit": []}

    touched = set(touched_claim_ids or [])
    reverse_supersedes = {
        claim.get("supersedes_claim_id"): claim
        for claim in all_claims
        if claim.get("supersedes_claim_id")
    }
    evolution_rows = get_claim_evolution(topic_id, limit=500)
    supersede_relations = {
        row.get("previous_claim_id"): row
        for row in evolution_rows
        if row.get("relation_type") == "supersedes" and row.get("previous_claim_id")
    }

    updated_claims = 0
    audit_rows: list[dict] = []
    for claim in all_claims:
        claim_id = claim["id"]
        if touched and claim_id not in touched and claim_id not in reverse_supersedes:
            continue

        evidence_rows = get_evidence_sets_for_claim(topic_id, claim_id)
        latest_signal = _pick_latest_signal(claim, evidence_rows)
        policy = claim.get("decay_policy", "medium")
        active_window = ACTIVE_WINDOW_DAYS.get(policy, ACTIVE_WINDOW_DAYS["medium"])
        inactive_window = INACTIVE_WINDOW_DAYS.get(policy, INACTIVE_WINDOW_DAYS["medium"])

        replacement_claim = reverse_supersedes.get(claim_id)
        supersede_relation = supersede_relations.get(claim_id)
        next_status = claim.get("status", "active")
        next_freshness = claim.get("staleness_status", "fresh")
        reason = "no lifecycle change"

        if replacement_claim:
            next_status = "superseded"
            next_freshness = "replaced"
            reason = f"replaced by {replacement_claim['id']}"
        else:
            if latest_signal is None:
                age_days = inactive_window + 1
            else:
                age_days = max((now - latest_signal).total_seconds() / 86400, 0.0)
            if age_days <= active_window:
                next_status = "active"
                next_freshness = "fresh"
                reason = f"recent supporting signal within {active_window}d"
            elif age_days <= inactive_window:
                next_status = "stale"
                next_freshness = "stale"
                reason = f"no new supporting signal for {round(age_days, 1)}d"
            else:
                next_status = "inactive"
                next_freshness = "stale"
                reason = f"support expired after {round(age_days, 1)}d"

        refresh_at = (
            latest_signal.astimezone(timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")
            if latest_signal
            else claim.get("last_refreshed_at")
            or claim.get("last_validated_at")
        )
        changed = (
            next_status != claim.get("status")
            or next_freshness != claim.get("staleness_status")
        )
        if persist:
            raw_metadata = claim.get("metadata_json") or {}
            if isinstance(raw_metadata, str):
                try:
                    metadata = json.loads(raw_metadata)
                except Exception:
                    metadata = {}
            elif isinstance(raw_metadata, dict):
                metadata = dict(raw_metadata)
            else:
                metadata = {}
            metadata["lifecycle"] = {
                "reason": reason,
                "evaluated_at": now.isoformat(),
                "source": source,
            }
            update_claim_lifecycle(
                claim_id,
                status=next_status,
                staleness_status=next_freshness,
                last_validated_at=refresh_at,
                metadata=metadata,
            )
            add_claim_document(
                claim_id,
                _build_claim_text(claim),
                {
                    "topic_id": str(topic_id),
                    "status": next_status,
                    "claim_type": claim.get("claim_kind") or claim.get("claim_type", ""),
                    "title": claim.get("statement", "")[:120],
                },
            )
            if changed and next_status == "superseded" and replacement_claim and not supersede_relation:
                add_claim_evolution(
                    topic_id=topic_id,
                    claim_id=replacement_claim["id"],
                    previous_claim_id=claim_id,
                    relation_type="supersedes",
                    reason="lifecycle evaluator marked prior claim as replaced",
                    metadata={"source": source},
                )
        if changed:
            updated_claims += 1
        audit_rows.append(
            {
                "claim_id": claim_id,
                "statement": claim.get("statement", ""),
                "claim_kind": claim.get("claim_kind") or claim.get("claim_type", ""),
                "previous_status": claim.get("status", ""),
                "current_status": next_status,
                "freshness": next_freshness,
                "last_refreshed_at": refresh_at,
                "reason": reason,
                "supporting_evidence_count": len(evidence_rows),
            }
        )

    return {
        "topic_id": topic_id,
        "evaluated_claims": len(audit_rows),
        "updated_claims": updated_claims,
        "audit": audit_rows,
    }


def refresh_recent_topic_lifecycles(topic_ids: list[int], *, source: str = "scheduler") -> list[dict]:
    return [evaluate_claim_lifecycle(topic_id, source=source) for topic_id in topic_ids]
