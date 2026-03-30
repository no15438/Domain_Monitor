import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
SCRIPTS_DIR = BACKEND_DIR / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from claim_lifecycle import evaluate_claim_lifecycle
from database import get_claims_v2, get_temporal_snapshots, get_topics, init_db
from config import settings
from topic_summary import _build_delta_summary
from seed_validation_dataset import main as seed_validation_dataset_main


TARGET_TOPIC = "Validation Dataset - AI Infrastructure"


def _topic_id() -> int:
    for topic in get_topics():
        if topic["name"] == TARGET_TOPIC:
            return int(topic["id"])
    raise RuntimeError(f"Unable to locate topic: {TARGET_TOPIC}")


def main():
    init_db(settings.database_path)
    seed_validation_dataset_main()
    topic_id = _topic_id()
    audit = evaluate_claim_lifecycle(topic_id, source="verify_claim_lifecycle")
    claims = {claim["id"]: claim for claim in get_claims_v2(topic_id, limit=100)}
    snapshots = get_temporal_snapshots(topic_id, window_type="daily", limit=10)
    snapshot_ids = sorted([row["id"] for row in snapshots])
    if len(snapshot_ids) < 3:
        raise RuntimeError("Expected at least 3 snapshots in validation dataset")
    delta = _build_delta_summary(snapshot_ids[-2], snapshot_ids[-1], topic_id)

    assert claims["validation-claim-001"]["status"] == "active"
    assert claims["validation-claim-002"]["status"] == "superseded"
    assert claims["validation-claim-003"]["status"] == "active"
    assert claims["validation-claim-004"]["status"] == "inactive"
    assert "validation-claim-002" in delta["superseded_claim_ids"]

    print(json.dumps({
        "status": "ok",
        "topic_id": topic_id,
        "claim_statuses": {
            claim_id: claims[claim_id]["status"]
            for claim_id in (
                "validation-claim-001",
                "validation-claim-002",
                "validation-claim-003",
                "validation-claim-004",
            )
        },
        "delta_superseded_claim_ids": delta["superseded_claim_ids"],
        "lifecycle_updated_claims": audit["updated_claims"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
