"""
End-to-end pipeline tests covering all major generation paths and gate scenarios.

These tests use in-memory SQLite fixtures (tmp_path_factory), mock all LLM
and vector-store calls, and let real DB functions run against the test DB.

Test classes:
  TestGateSuppressionScenarios  — adequacy gate logic (no LLM calls expected)
  TestFullEvolutionE2E          — full evolution pipeline (gate passes, artifact written)
  TestGlobalOverviewE2E         — global overview generation
  TestDailySummaryE2E           — daily snapshot generation
  TestAssessAdequacyUnit        — unit tests for _assess_evolution_adequacy edge cases

Run with:
    cd backend && python -m pytest tests/test_pipeline_e2e.py -v
"""

import json
import sqlite3
import sys
import os
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database
import topic_summary
from topic_summary import (
    _assess_evolution_adequacy,
    _load_evolution_fact_bundle,
    EvolutionFactBundle,
)


# ── Timestamps ────────────────────────────────────────────────────────────────

_NOW = datetime.now(timezone.utc)


def _ts(delta_days: float = 0) -> str:
    """ISO timestamp relative to now (negative = past)."""
    return (_NOW + timedelta(days=delta_days)).isoformat()


# ── DB helpers ────────────────────────────────────────────────────────────────

def _insert_topic(conn: sqlite3.Connection, topic_id: int, name: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO topics (id, name, is_active) VALUES (?, ?, 1)",
        (topic_id, name),
    )


def _insert_article(
    conn: sqlite3.Connection,
    article_id: str,
    topic_id: int,
    title: str,
    published_days_ago: float = 0.5,
) -> None:
    pub = _ts(-published_days_ago)
    conn.execute(
        """INSERT INTO articles
           (id, title, summary, source, url, topic_id, importance, status, created_at, published_at)
           VALUES (?,?,?,?,?,?,9,'active',?,?)""",
        (
            article_id,
            title,
            f"Detailed summary of: {title}",
            "E2E Test Source",
            f"https://e2e.test/{article_id}",
            topic_id,
            pub,
            pub,
        ),
    )


def _insert_event(
    conn: sqlite3.Connection,
    event_id: str,
    topic_id: int,
    title: str,
    days_ago: float = 2,
) -> None:
    ts = _ts(-days_ago)
    conn.execute(
        """INSERT INTO events_v2
           (id, topic_id, event_key, title, summary, status, first_seen_at, last_seen_at, created_at)
           VALUES (?,?,?,?,?,'active',?,?,?)""",
        (
            event_id,
            topic_id,
            f"key-{event_id}",
            title,
            f"Detailed description of {title}.",
            ts,
            _ts(-1),
            ts,
        ),
    )


def _insert_claim(
    conn: sqlite3.Connection,
    claim_id: str,
    topic_id: int,
    statement: str,
) -> None:
    conn.execute(
        """INSERT INTO claims
           (id, topic_id, statement, status, staleness_status, claim_type, created_at, updated_at)
           VALUES (?,?,?,'active','fresh','observation',?,?)""",
        (claim_id, topic_id, statement, _ts(-3), _ts(-1)),
    )


def _insert_claim_evolution(
    conn: sqlite3.Connection,
    topic_id: int,
    claim_id: str,
    previous_claim_id: str | None,
    relation_type: str,
    reason: str,
) -> None:
    conn.execute(
        """INSERT INTO claim_evolution
           (topic_id, claim_id, previous_claim_id, relation_type, reason, created_at)
           VALUES (?,?,?,?,?,?)""",
        (topic_id, claim_id, previous_claim_id, relation_type, reason, _ts(-1)),
    )


def _insert_snapshot(
    conn: sqlite3.Connection,
    topic_id: int,
    window_end_days_ago: float = 0,
) -> int:
    return conn.execute(
        """INSERT INTO temporal_snapshots
           (topic_id, summary_text, window_type, snapshot_status, window_end, created_at)
           VALUES (?,?,'daily','final',?,?)""",
        (
            topic_id,
            "Test snapshot: domain signals observed during this monitoring window.",
            _ts(-window_end_days_ago),
            _ts(-window_end_days_ago),
        ),
    ).lastrowid  # type: ignore[return-value]


def _link_event(conn: sqlite3.Connection, snapshot_id: int, event_id: str) -> None:
    conn.execute(
        "INSERT INTO snapshot_events (snapshot_id, event_id) VALUES (?,?)",
        (snapshot_id, event_id),
    )


def _link_claim(conn: sqlite3.Connection, snapshot_id: int, claim_id: str) -> None:
    conn.execute(
        "INSERT INTO snapshot_claims (snapshot_id, claim_id) VALUES (?,?)",
        (snapshot_id, claim_id),
    )


# ── Fake LLM responses ────────────────────────────────────────────────────────

_FAKE_EXTRACTOR_JSON = json.dumps({
    "top_changes": [
        {
            "change_id": "TC1",
            "priority": 1,
            "entity_type": "event",
            "novelty": "emerged_cluster",
            "narrative_role": "observed_change",
            "statement": "A new policy event emerged while the prior one resolved, marking a structural shift.",
            "context": "Primary change observed this monitoring period.",
            "citation_ids": [],
            "source_entity_ids": ["NE-0"],
        }
    ],
    "event_transitions": [
        {
            "change_id": "EV1",
            "priority": 1,
            "narrative_role": "event_shift",
            "kind": "emerged",
            "entity_id": "e2e-evt-new",
            "title": "New Structural Event Emerged",
            "statement": "The new structural event appeared in the current snapshot, signaling a directional change.",
            "citation_ids": [],
            "derived_from_change_ids": ["TC1"],
        }
    ],
    "claim_trajectories": [
        {
            "change_id": "CL1",
            "priority": 1,
            "narrative_role": "claim_shift",
            "kind": "emerged",
            "entity_id": "e2e-clm-new",
            "statement": "A new structural claim emerged reflecting the observed event shift.",
            "context": "Emerged in the current snapshot.",
            "citation_ids": [],
            "supported_by_event_ids": ["EV1"],
        }
    ],
    "strategic_implications": [
        {
            "change_id": "SI1",
            "narrative_role": "implication",
            "statement": "The shift from the prior event cluster to the new one suggests a durable structural realignment.",
            "derived_from_change_ids": ["TC1"],
            "citation_ids": [],
        }
    ],
})

_FAKE_NARRATOR_RESPONSE = """## 1. Observed Changes
A new structural event emerged [E1] while the prior monitoring focus resolved, confirming a directional shift in the domain.

## 2. Event-Level Shifts
New Structural Event Emerged: this event appeared in the current monitoring window [E1], indicating that the prior policy framing has been superseded by new capacity signals.

## 3. Claim Trajectories
A new structural claim appeared [E1], directly supported by the emerging event and replacing the earlier forecast that lacked confirming evidence.

## 4. Strategic Implications
The shift from the prior event cluster to the new one suggests a durable structural realignment [E1]. Monitoring should continue to confirm whether the new framing holds.
"""

_FAKE_GLOBAL_OVERVIEW = """## 1. Domain Definition & Scope
This domain tracks structural shifts in technology procurement and access patterns.

## 2. Historical Evolution (The Story So Far)
Early signals were dominated by policy speculation. As capacity data arrived, the narrative shifted toward hard constraints and cloud substitution.

## 3. Key Entities & Power Dynamics
Key players include leading GPU manufacturers and hyperscaler buyers who prepay for capacity, with regional cloud operators absorbing overflow demand.

## 4. Persistent Themes & Long-Term Trends
Supply constraints and cloud intermediation appear consistently across monitoring windows.

## 5. Timeliness Assessment & Verification Gaps
Capacity claims are fresh; policy-timing claims need re-verification as the environment evolves.
"""

_FAKE_DAILY_SUMMARY = """## Key Developments
New capacity signals emerged [E1] during this monitoring period, reinforcing the view that supply remains constrained.

## Notable Signals
Distribution lead times [A1] remain elevated across major enterprise channels.

## Outlook
Continued monitoring warranted [E1]; the situation remains fluid.
"""


# ── Fixture: rich DB (gate passes) ───────────────────────────────────────────

@pytest.fixture(scope="class")
def rich_db(tmp_path_factory):
    """Two snapshots with clear event+claim diff + claim_evolution. Gate must pass."""
    path = str(tmp_path_factory.mktemp("rich") / "rich.db")
    database.init_db(path)
    conn = sqlite3.connect(path)

    _insert_topic(conn, 301, "E2E Rich Topic")

    # Four articles (published recently so citation catalog picks them up)
    for i in range(1, 5):
        _insert_article(conn, f"rich-art-{i}", 301, f"Rich Article {i}: structural domain signal", published_days_ago=i)

    # Two events: old (in T1 only) and new (in TN only)
    _insert_event(conn, "rich-evt-old", 301, "Old Policy Announcement Event", days_ago=5)
    _insert_event(conn, "rich-evt-new", 301, "New Compliance Crackdown Event", days_ago=1)

    # Two claims: old (in T1 only) and new (in TN only)
    _insert_claim(conn, "rich-clm-old", 301, "Immediate demand collapse expected from policy enforcement.")
    _insert_claim(conn, "rich-clm-new", 301, "Demand rerouted to regional cloud alternatives at scale.")

    # claim_evolution: new claim supersedes old
    _insert_claim_evolution(conn, 301, "rich-clm-new", "rich-clm-old", "supersedes",
                            "Regional alternatives replaced immediate collapse thesis.")

    # Snapshot T1 (baseline): old event + old claim
    s1 = _insert_snapshot(conn, 301, window_end_days_ago=3)
    _link_event(conn, s1, "rich-evt-old")
    _link_claim(conn, s1, "rich-clm-old")

    # Snapshot TN (current): new event + new claim  ← clear diff vs T1
    s2 = _insert_snapshot(conn, 301, window_end_days_ago=0)
    _link_event(conn, s2, "rich-evt-new")
    _link_claim(conn, s2, "rich-clm-new")

    conn.commit()
    conn.close()
    return path


# ── Fixture: no-diff DB (gate suppressed) ────────────────────────────────────

@pytest.fixture(scope="class")
def no_diff_db(tmp_path_factory):
    """Two snapshots sharing IDENTICAL events and claims — no diff signals."""
    path = str(tmp_path_factory.mktemp("nodiff") / "nodiff.db")
    database.init_db(path)
    conn = sqlite3.connect(path)

    _insert_topic(conn, 302, "E2E No-Diff Topic")
    _insert_article(conn, "nd-art-1", 302, "Stable domain article one", published_days_ago=1)
    _insert_article(conn, "nd-art-2", 302, "Stable domain article two", published_days_ago=2)
    _insert_event(conn, "nd-evt-1", 302, "Persistent Steady-State Event", days_ago=5)
    _insert_claim(conn, "nd-clm-1", 302, "The domain remains in a stable steady-state configuration.")

    # T1 and TN share SAME event and claim → has_diff_signals = False
    s1 = _insert_snapshot(conn, 302, window_end_days_ago=3)
    s2 = _insert_snapshot(conn, 302, window_end_days_ago=0)
    for s in (s1, s2):
        _link_event(conn, s, "nd-evt-1")
        _link_claim(conn, s, "nd-clm-1")

    conn.commit()
    conn.close()
    return path


# ── Fixture: articles-only DB (provisional, gate suppressed) ─────────────────

@pytest.fixture(scope="class")
def articles_only_db(tmp_path_factory):
    """Articles exist but no temporal_snapshots → provisional with no diff signals."""
    path = str(tmp_path_factory.mktemp("artonly") / "artonly.db")
    database.init_db(path)
    conn = sqlite3.connect(path)

    _insert_topic(conn, 303, "E2E Articles-Only Topic")
    _insert_article(conn, "ao-art-1", 303, "Early signal: new startup raises capital", published_days_ago=0.5)
    _insert_article(conn, "ao-art-2", 303, "Second early signal: analyst coverage begins", published_days_ago=0.3)
    # No temporal_snapshots inserted

    conn.commit()
    conn.close()
    return path


# ── Fixture: empty DB (skip tier) ────────────────────────────────────────────

@pytest.fixture(scope="class")
def empty_db(tmp_path_factory):
    """No articles, no snapshots → tier=skip."""
    path = str(tmp_path_factory.mktemp("empty") / "empty.db")
    database.init_db(path)
    conn = sqlite3.connect(path)
    _insert_topic(conn, 304, "E2E Empty Topic")
    conn.commit()
    conn.close()
    return path


# ── Fixture: global overview DB ───────────────────────────────────────────────

@pytest.fixture(scope="class")
def overview_db(tmp_path_factory):
    """3 articles + 2 events + 2 claims + 2 snapshots → global overview should generate."""
    path = str(tmp_path_factory.mktemp("overview") / "overview.db")
    database.init_db(path)
    conn = sqlite3.connect(path)

    _insert_topic(conn, 401, "E2E Overview Topic")
    for i in range(1, 4):
        _insert_article(conn, f"ov-art-{i}", 401, f"Overview domain article {i}", published_days_ago=i)
    _insert_event(conn, "ov-evt-1", 401, "Key Infrastructure Capacity Event", days_ago=7)
    _insert_event(conn, "ov-evt-2", 401, "Secondary Policy Development Event", days_ago=3)
    _insert_claim(conn, "ov-clm-1", 401, "Market access remains structurally constrained.")
    _insert_claim(conn, "ov-clm-2", 401, "Cloud-based substitution is accelerating measurably.")

    # Two snapshots
    s1 = _insert_snapshot(conn, 401, window_end_days_ago=7)
    s2 = _insert_snapshot(conn, 401, window_end_days_ago=0)
    _link_event(conn, s1, "ov-evt-1")
    _link_event(conn, s2, "ov-evt-1")
    _link_event(conn, s2, "ov-evt-2")
    _link_claim(conn, s1, "ov-clm-1")
    _link_claim(conn, s2, "ov-clm-1")
    _link_claim(conn, s2, "ov-clm-2")

    conn.commit()
    conn.close()
    return path


# ── Fixture: daily summary DB ─────────────────────────────────────────────────

@pytest.fixture(scope="class")
def summary_db(tmp_path_factory):
    """Recent articles + event + claim → daily summary should generate and persist a snapshot."""
    path = str(tmp_path_factory.mktemp("summary") / "summary.db")
    database.init_db(path)
    conn = sqlite3.connect(path)

    _insert_topic(conn, 501, "E2E Daily Summary Topic")
    # Published within 48h so they appear in get_insight_summary(hours=48)
    _insert_article(conn, "sum-art-1", 501, "Breaking: supply chain bottleneck worsens", published_days_ago=0.1)
    _insert_article(conn, "sum-art-2", 501, "Confirmed: 20-week GPU lead times persist", published_days_ago=0.3)
    _insert_event(conn, "sum-evt-1", 501, "Supply Chain Bottleneck Worsens This Quarter", days_ago=1)
    _insert_claim(conn, "sum-clm-1", 501, "GPU lead times remain elevated at 18-24 weeks for enterprise buyers.")

    conn.commit()
    conn.close()
    return path


# ═══════════════════════════════════════════════════════════════════════════════
# TestGateSuppressionScenarios
# ═══════════════════════════════════════════════════════════════════════════════

class TestGateSuppressionScenarios:
    """Verify that the adequacy gate correctly suppresses low-signal runs.

    These tests do NOT expect any LLM calls — the gate fires before the narrator.
    """

    @patch("topic_summary.llm_chat")
    @patch("topic_summary.add_artifact_document")
    @patch("topic_summary.replace_synthesis_artifact", return_value="would-not-reach")
    def test_no_diff_snapshots_suppressed(self, mock_repl, mock_add, mock_llm, no_diff_db):
        """Two snapshots with identical events/claims: LLM must NOT be called."""
        database.init_db(no_diff_db)
        result = topic_summary.generate_evolution_report_sync(302)

        assert mock_llm.call_count == 0, (
            f"LLM (narrator/extractor) must NOT be called when gate suppresses. "
            f"Got {mock_llm.call_count} calls."
        )
        assert mock_repl.call_count == 0, (
            "replace_synthesis_artifact must NOT be called when gate suppresses."
        )
        assert not result.startswith("## "), (
            f"Suppressed result must not start with '## '. Got: {result[:80]!r}"
        )

    @patch("topic_summary.llm_chat")
    @patch("topic_summary.add_artifact_document")
    @patch("topic_summary.replace_synthesis_artifact", return_value="would-not-reach")
    def test_articles_only_provisional_suppressed(self, mock_repl, mock_add, mock_llm, articles_only_db):
        """Articles with no snapshots → provisional tier → gate must suppress."""
        database.init_db(articles_only_db)
        result = topic_summary.generate_evolution_report_sync(303)

        assert mock_llm.call_count == 0, (
            f"LLM must NOT be called for provisional with no diff signals. "
            f"Got {mock_llm.call_count} calls."
        )
        assert mock_repl.call_count == 0, "Artifact must NOT be persisted."
        assert isinstance(result, str) and not result.startswith("## ")

    @patch("topic_summary.llm_chat")
    @patch("topic_summary.add_artifact_document")
    @patch("topic_summary.replace_synthesis_artifact", return_value="would-not-reach")
    def test_empty_topic_skip_tier(self, mock_repl, mock_add, mock_llm, empty_db):
        """No articles, no snapshots → tier=skip, returns explanation without LLM."""
        database.init_db(empty_db)
        result = topic_summary.generate_evolution_report_sync(304)

        assert mock_llm.call_count == 0, "LLM must NOT be called for skip tier."
        assert mock_repl.call_count == 0, "Artifact must NOT be persisted for skip."
        assert isinstance(result, str) and len(result) > 10
        assert not result.startswith("## "), (
            f"Skip result must not start with '## '. Got: {result[:80]!r}"
        )

    def test_no_diff_bundle_has_correct_tier(self, no_diff_db):
        """Bundle loaded from no-diff DB must have tier=full (snapshots exist) but no diff signals."""
        database.init_db(no_diff_db)
        bundle = _load_evolution_fact_bundle(302)
        # Snapshots exist → tier could be 'full' (if diff signals) or 'provisional' (if none)
        # Since T1 and TN share same events/claims → has_diff_signals=False → provisional
        assert bundle.tier in ("provisional", "full"), f"Unexpected tier: {bundle.tier}"
        # Verify no diff signals
        assert not bundle.new_events, "No new events expected in no-diff scenario"
        assert not bundle.resolved_events, "No resolved events expected in no-diff scenario"
        assert not bundle.new_claims, "No new claims expected in no-diff scenario"
        assert not bundle.dropped_claims, "No dropped claims expected in no-diff scenario"

    def test_articles_only_bundle_tier(self, articles_only_db):
        """Articles-only DB should give provisional tier."""
        database.init_db(articles_only_db)
        bundle = _load_evolution_fact_bundle(303)
        assert bundle.tier == "provisional", f"Expected provisional, got: {bundle.tier}"

    def test_empty_topic_bundle_tier(self, empty_db):
        """Empty topic must give skip tier."""
        database.init_db(empty_db)
        bundle = _load_evolution_fact_bundle(304)
        assert bundle.tier == "skip"
        assert bundle.error is not None


# ═══════════════════════════════════════════════════════════════════════════════
# TestFullEvolutionE2E
# ═══════════════════════════════════════════════════════════════════════════════

class TestFullEvolutionE2E:
    """Full two-stage evolution pipeline: gate passes, narrator runs, artifact written."""

    @patch("topic_summary.add_snapshot_document")
    @patch("topic_summary.add_artifact_document")
    @patch("topic_summary.llm_chat", side_effect=[_FAKE_EXTRACTOR_JSON, _FAKE_NARRATOR_RESPONSE])
    def test_gate_passes_two_llm_calls(self, mock_llm, mock_add_art, mock_add_snap, rich_db):
        """Rich topic: exactly 2 LLM calls (extractor + narrator)."""
        database.init_db(rich_db)
        topic_summary.generate_evolution_report_sync(301)
        assert mock_llm.call_count == 2, (
            f"Expected exactly 2 LLM calls (extractor + narrator). Got {mock_llm.call_count}."
        )

    @patch("topic_summary.add_snapshot_document")
    @patch("topic_summary.add_artifact_document")
    @patch("topic_summary.llm_chat", side_effect=[_FAKE_EXTRACTOR_JSON, _FAKE_NARRATOR_RESPONSE])
    def test_gate_passes_result_is_markdown(self, mock_llm, mock_add_art, mock_add_snap, rich_db):
        """Rich topic: returned result must be valid markdown starting with '## 1.'"""
        database.init_db(rich_db)
        result = topic_summary.generate_evolution_report_sync(301)
        assert result.startswith("## 1."), (
            f"Result must start with '## 1.'. Got: {result[:80]!r}"
        )

    @patch("topic_summary.add_snapshot_document")
    @patch("topic_summary.add_artifact_document")
    @patch("topic_summary.llm_chat", side_effect=[_FAKE_EXTRACTOR_JSON, _FAKE_NARRATOR_RESPONSE])
    def test_gate_passes_artifact_written_to_db(self, mock_llm, mock_add_art, mock_add_snap, rich_db):
        """Rich topic: evolution_report artifact must be persisted in the test DB."""
        database.init_db(rich_db)
        topic_summary.generate_evolution_report_sync(301)
        artifact = database.get_synthesis_artifact(301, "evolution_report")
        assert artifact is not None, "evolution_report artifact must be present in DB after generation."
        assert artifact["status"] == "final"
        assert artifact["content"].startswith("## 1.")

    @patch("topic_summary.add_snapshot_document")
    @patch("topic_summary.add_artifact_document")
    @patch("topic_summary.llm_chat", side_effect=[_FAKE_EXTRACTOR_JSON, _FAKE_NARRATOR_RESPONSE])
    def test_gate_passes_artifact_has_diagnostics(self, mock_llm, mock_add_art, mock_add_snap, rich_db):
        """Persisted artifact must include all three stage diagnostics keys."""
        database.init_db(rich_db)
        topic_summary.generate_evolution_report_sync(301)
        artifact = database.get_synthesis_artifact(301, "evolution_report")
        assert artifact is not None
        metadata = json.loads(artifact.get("metadata_json") or "{}")
        diag = metadata.get("diagnostics", {})
        for key in ("stage_context", "stage_facts", "stage_narrative"):
            assert key in diag, f"Diagnostics missing key '{key}'"

    @patch("topic_summary.add_snapshot_document")
    @patch("topic_summary.add_artifact_document")
    @patch("topic_summary.llm_chat")
    def test_no_diff_artifact_not_written(self, mock_llm, mock_add_art, mock_add_snap, no_diff_db):
        """No-diff topic: gate must suppress, zero LLM calls, no artifact in DB."""
        database.init_db(no_diff_db)
        mock_llm.return_value = "should not be reached"
        topic_summary.generate_evolution_report_sync(302)
        assert mock_llm.call_count == 0
        artifact = database.get_synthesis_artifact(302, "evolution_report")
        assert artifact is None, (
            "No evolution_report artifact should exist in DB when gate suppresses."
        )

    @patch("topic_summary.add_snapshot_document")
    @patch("topic_summary.add_artifact_document")
    @patch("topic_summary.llm_chat", side_effect=[_FAKE_EXTRACTOR_JSON, _FAKE_NARRATOR_RESPONSE])
    def test_rich_bundle_diff_signals_present(self, mock_llm, mock_add_art, mock_add_snap, rich_db):
        """Rich DB bundle must contain new_events and new_claims as expected."""
        database.init_db(rich_db)
        bundle = _load_evolution_fact_bundle(301)
        assert bundle.tier == "full", f"Expected full tier, got {bundle.tier}"
        assert len(bundle.new_events) >= 1, "Expected at least one new event in rich scenario"
        assert len(bundle.new_claims) >= 1, "Expected at least one new claim in rich scenario"
        assert len(bundle.resolved_events) >= 1, "Expected at least one resolved event in rich scenario"


# ═══════════════════════════════════════════════════════════════════════════════
# TestGlobalOverviewE2E
# ═══════════════════════════════════════════════════════════════════════════════

class TestGlobalOverviewE2E:
    """Global overview generation: with sufficient data the report is written to DB."""

    @patch("topic_summary.add_artifact_document")
    @patch("topic_summary.llm_chat", return_value=_FAKE_GLOBAL_OVERVIEW)
    def test_global_overview_calls_llm_once(self, mock_llm, mock_add, overview_db):
        """With snapshots + events + claims: exactly 1 LLM call."""
        database.init_db(overview_db)
        topic_summary.generate_global_overview_sync(401)
        assert mock_llm.call_count == 1, (
            f"Expected exactly 1 LLM call for global overview. Got {mock_llm.call_count}."
        )

    @patch("topic_summary.add_artifact_document")
    @patch("topic_summary.llm_chat", return_value=_FAKE_GLOBAL_OVERVIEW)
    def test_global_overview_result_is_markdown(self, mock_llm, mock_add, overview_db):
        """Returned result must start with a markdown section header."""
        database.init_db(overview_db)
        result = topic_summary.generate_global_overview_sync(401)
        assert result.startswith("## 1."), (
            f"Result must start with '## 1.'. Got: {result[:80]!r}"
        )

    @patch("topic_summary.add_artifact_document")
    @patch("topic_summary.llm_chat", return_value=_FAKE_GLOBAL_OVERVIEW)
    def test_global_overview_artifact_persisted(self, mock_llm, mock_add, overview_db):
        """global_overview artifact must be written to DB with status=final."""
        database.init_db(overview_db)
        topic_summary.generate_global_overview_sync(401)
        artifact = database.get_synthesis_artifact(401, "global_overview")
        assert artifact is not None, "global_overview artifact must be present in DB."
        assert artifact["status"] == "final"
        assert len(artifact["content"]) > 50

    @patch("topic_summary.add_artifact_document")
    @patch("topic_summary.llm_chat", return_value=_FAKE_GLOBAL_OVERVIEW)
    def test_global_overview_source_is_temporal_snapshots(self, mock_llm, mock_add, overview_db):
        """Artifact metadata must indicate temporal_snapshots as source."""
        database.init_db(overview_db)
        topic_summary.generate_global_overview_sync(401)
        artifact = database.get_synthesis_artifact(401, "global_overview")
        assert artifact is not None
        metadata = json.loads(artifact.get("metadata_json") or "{}")
        assert metadata.get("source") == "temporal_snapshots", (
            f"Expected source='temporal_snapshots'. Got: {metadata.get('source')!r}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# TestDailySummaryE2E
# ═══════════════════════════════════════════════════════════════════════════════

class TestDailySummaryE2E:
    """Daily snapshot summary generation: runs with events/claims and persists a snapshot.

    Note: generate_summary_sync re-imports llm_chat from llm_client inside the function
    body (lazy import pattern), so we must patch 'llm_client.llm_chat' rather than
    'topic_summary.llm_chat' to intercept the call.
    """

    @patch("topic_summary.add_snapshot_document")
    @patch("llm_client.llm_chat", return_value=_FAKE_DAILY_SUMMARY)
    def test_summary_sync_calls_llm_once(self, mock_llm, mock_snap, summary_db):
        """With events and claims present: exactly 1 LLM call via llm_client."""
        database.init_db(summary_db)
        topic_summary.generate_summary_sync(501, hours=48)
        assert mock_llm.call_count == 1, (
            f"Expected exactly 1 LLM call for daily summary. Got {mock_llm.call_count}."
        )

    @patch("topic_summary.add_snapshot_document")
    @patch("llm_client.llm_chat", return_value=_FAKE_DAILY_SUMMARY)
    def test_summary_sync_returns_non_empty_string(self, mock_llm, mock_snap, summary_db):
        """Result must be a non-empty string."""
        database.init_db(summary_db)
        result = topic_summary.generate_summary_sync(501, hours=48)
        assert isinstance(result, str) and len(result) > 20, (
            f"Expected non-empty summary string. Got: {result!r}"
        )

    @patch("topic_summary.add_snapshot_document")
    @patch("llm_client.llm_chat", return_value=_FAKE_DAILY_SUMMARY)
    def test_summary_sync_creates_temporal_snapshot(self, mock_llm, mock_snap, summary_db):
        """_persist_and_vectorize must create a new temporal_snapshot in the test DB."""
        database.init_db(summary_db)
        result = topic_summary.generate_summary_sync(501, hours=48)
        snapshots = database.get_temporal_snapshots(501, window_type="daily", limit=5)
        assert len(snapshots) >= 1, "At least one temporal snapshot must have been created."
        latest = snapshots[0]
        assert latest["summary_text"] == result, (
            "The snapshot summary_text must match the returned result."
        )
        assert latest["snapshot_status"] == "final"

    @patch("topic_summary.add_snapshot_document")
    @patch("llm_client.llm_chat")
    def test_summary_sync_empty_topic_returns_empty(self, mock_llm, mock_snap, empty_db):
        """Empty topic (no events, claims, articles): generate_summary_sync returns ''."""
        database.init_db(empty_db)
        result = topic_summary.generate_summary_sync(304, hours=24)
        assert mock_llm.call_count == 0, "LLM must not be called when no context can be built."
        assert result == "", f"Expected empty string, got: {result!r}"


# ═══════════════════════════════════════════════════════════════════════════════
# TestAssessAdequacyUnit
# ═══════════════════════════════════════════════════════════════════════════════

class TestAssessAdequacyUnit:
    """Unit tests for _assess_evolution_adequacy covering all three gate rules."""

    def _diag(
        self,
        top_changes: int = 2,
        event_transitions: int = 2,
        p1_claims: int = 1,
        claim_trajectories: int = 1,
        is_fallback: bool = False,
    ) -> dict:
        return {
            "top_changes_count": top_changes,
            "event_transitions_count": event_transitions,
            "claim_trajectories_priority1": p1_claims,
            "claim_trajectories_count": claim_trajectories,
            "is_fallback": is_fallback,
            "validation_errors": ["some error"] if is_fallback else [],
            "raw_extractor_hash": "abc12345",
            "event_transitions_reframed": 0,
            "claim_trajectories_bound_to_events": 0,
            "strategic_implications_count": 0,
        }

    def _bundle(self, tier: str = "full", **kwargs) -> EvolutionFactBundle:
        defaults = dict(
            topic_id=1,
            tier=tier,
            error=None,
            research_context={"brief": "", "angles": [], "entities": [], "geographic_scope": []},
            baseline_snapshot={"id": 1, "summary_text": "Baseline", "window_end": "2024-01-01T00:00:00"},
            current_snapshot={"id": 2, "summary_text": "Current", "window_end": "2024-01-02T00:00:00"},
            intermediate_snapshots=[],
            baseline_events=[],
            current_events=[],
            baseline_claims=[],
            current_claims=[],
            new_events=[{"id": "e1", "title": "New Event", "summary": "New.", "event_status": "active",
                         "first_seen_at": "", "last_seen_at": ""}],
            resolved_events=[],
            new_claims=[],
            dropped_claims=[],
            persisted_claims=[],
            claim_evolution_records=[],
            snapshot_deltas=[],
            evidence_sets=[],
        )
        defaults.update(kwargs)
        return EvolutionFactBundle(**defaults)

    # Rule 1: provisional with no diff signals

    def test_rule1_provisional_no_signals_suppressed(self):
        bundle = self._bundle(
            tier="provisional",
            new_events=[], resolved_events=[], new_claims=[], dropped_claims=[],
            claim_evolution_records=[],
        )
        diag = self._diag(top_changes=0, event_transitions=0, p1_claims=0)
        should_emit, reason = _assess_evolution_adequacy(bundle, diag)
        assert should_emit is False
        assert reason is not None
        assert "provisional" in reason

    def test_rule1_provisional_with_new_event_passes(self):
        bundle = self._bundle(tier="provisional")  # new_events is non-empty by default
        diag = self._diag()
        should_emit, reason = _assess_evolution_adequacy(bundle, diag)
        assert should_emit is True, f"Provisional with new event should pass. Reason: {reason}"

    # Rule 2: all structured fact dimensions zero

    def test_rule2_all_facts_zero_suppressed(self):
        bundle = self._bundle(tier="full")
        diag = self._diag(top_changes=0, event_transitions=0, p1_claims=0)
        should_emit, reason = _assess_evolution_adequacy(bundle, diag)
        assert should_emit is False
        assert "insufficient structured facts" in reason

    def test_rule2_only_event_transitions_passes(self):
        """Having event_transitions alone should pass Rule 2."""
        bundle = self._bundle(tier="full")
        diag = self._diag(top_changes=0, event_transitions=1, p1_claims=0)
        should_emit, reason = _assess_evolution_adequacy(bundle, diag)
        assert should_emit is True, f"event_transitions=1 should pass gate. Reason: {reason}"

    def test_rule2_only_p1_claims_passes(self):
        """Having only p1 claim trajectories should pass Rule 2."""
        bundle = self._bundle(tier="full")
        diag = self._diag(top_changes=0, event_transitions=0, p1_claims=1)
        should_emit, reason = _assess_evolution_adequacy(bundle, diag)
        assert should_emit is True, f"p1_claims=1 should pass gate. Reason: {reason}"

    # Rule 3: full tier, fallback, and empty transitions+trajectories

    def test_rule3_full_fallback_empty_everything_suppressed(self):
        bundle = self._bundle(tier="full")
        diag = self._diag(
            top_changes=0,
            event_transitions=0,
            p1_claims=0,
            claim_trajectories=0,
            is_fallback=True,
        )
        should_emit, reason = _assess_evolution_adequacy(bundle, diag)
        assert should_emit is False

    def test_rule3_full_fallback_but_has_trajectories_passes(self):
        """Full-tier fallback with some claim_trajectories still passes Rule 3 (checked by Rule 2)."""
        bundle = self._bundle(tier="full")
        diag = self._diag(
            top_changes=0,
            event_transitions=0,
            p1_claims=1,
            claim_trajectories=1,
            is_fallback=True,
        )
        should_emit, reason = _assess_evolution_adequacy(bundle, diag)
        # Rule 2 passes (p1_claims=1), Rule 3 passes (claim_trajectories=1)
        assert should_emit is True, f"Fallback with p1_claims=1 should pass. Reason: {reason}"

    # Suppression reason must not start with '## '

    def test_suppression_reason_not_markdown(self):
        bundle = self._bundle(tier="full")
        diag = self._diag(top_changes=0, event_transitions=0, p1_claims=0)
        should_emit, reason = _assess_evolution_adequacy(bundle, diag)
        assert should_emit is False
        assert not reason.startswith("## "), (
            "Suppression reason must not start with '## ' — background task uses this to detect suppression."
        )


# ═══════════════════════════════════════════════════════════════════════════════
# TestCitationSanitizationE2E
# ═══════════════════════════════════════════════════════════════════════════════

class TestCitationSanitizationE2E:
    """Regression: _normalize_citations is applied to narrator output at the pipeline
    endpoint, so even a 'bad' narrator response must arrive clean at the artifact layer.

    The rich_db fixture has topic 301 with 2 events → E1/E2 in catalog, and
    4 articles → A1–A4 in catalog.
    """

    # Extractor returns a valid DiffFacts with E1 as a known citation
    _BAD_EXTRACTOR = json.dumps({
        "top_changes": [
            {
                "change_id": "TC1",
                "priority": 1,
                "entity_type": "event",
                "novelty": "emerged_cluster",
                "narrative_role": "observed_change",
                "statement": "A new compliance event emerged while the prior policy resolved.",
                "context": "Primary change this period.",
                "citation_ids": ["E1"],
                "source_entity_ids": ["EV1"],
            }
        ],
        "event_transitions": [
            {
                "change_id": "EV1",
                "priority": 1,
                "narrative_role": "event_shift",
                "kind": "emerged",
                "entity_id": "rich-evt-new",
                "title": "New Compliance Crackdown Event",
                "statement": "New compliance crackdown emerged.",
                "citation_ids": ["E1"],
                "derived_from_change_ids": ["TC1"],
            }
        ],
        "claim_trajectories": [
            {
                "change_id": "CL1",
                "priority": 1,
                "narrative_role": "claim_shift",
                "kind": "emerged",
                "entity_id": "rich-clm-new",
                "statement": "Demand rerouted to regional alternatives.",
                "context": "New claim this period.",
                "citation_ids": ["A1"],
                "supported_by_event_ids": ["EV1"],
            }
        ],
        "strategic_implications": [
            {
                "change_id": "SI1",
                "narrative_role": "implication",
                "statement": "Regional supply chain realignment is now structural.",
                "derived_from_change_ids": ["TC1"],
                "citation_ids": ["E1"],
            }
        ],
    })

    # Narrator output deliberately contains:
    # - TC1, EV1 (internal DiffFacts IDs leaked into prose)
    # - bare E2, A1 (valid catalog IDs but missing brackets)
    # - [E99] (invalid ID not in catalog)
    # - [E1] (valid, must be kept)
    _BAD_NARRATOR = (
        "## 1. Observed Changes\n"
        "Policy enforcement scope broadened [E1]. "
        "Logistic restrictions tightened E2, closing alternative routes.\n\n"
        "## 2. Event-Level Shifts\n"
        "Event EV1 emerged, shifting prior framing to hard constraints. "
        "The crackdown reframed border controls as systematic A1.\n\n"
        "## 3. Claim Trajectories\n"
        "Demand rerouted to regional alternatives emerged, backed by EV1 [E1]. "
        "An invalid citation appeared [E99].\n\n"
        "## 4. Strategic Implications\n"
        "Kicking off from TC1 and TC2, regional realignment is now structural E2 [E1].\n"
    )

    @patch("topic_summary.add_snapshot_document")
    @patch("topic_summary.add_artifact_document")
    @patch("topic_summary.llm_chat")
    def test_internal_ids_stripped_from_final_artifact(
        self, mock_llm, mock_add_art, mock_add_snap, rich_db
    ):
        """TC1, TC2, EV1 must NOT appear in the persisted evolution_report content."""
        database.init_db(rich_db)
        mock_llm.side_effect = [self._BAD_EXTRACTOR, self._BAD_NARRATOR]
        topic_summary.generate_evolution_report_sync(301)
        artifact = database.get_synthesis_artifact(301, "evolution_report")
        assert artifact is not None
        content = artifact["content"]
        for token in ("TC1", "TC2", "TC3", "EV1", "EV2", "CL1", "SI1"):
            assert token not in content, (
                f"Internal DiffFacts label {token!r} must not appear in final artifact content. "
                f"Got snippet: {content[:300]!r}"
            )

    @patch("topic_summary.add_snapshot_document")
    @patch("topic_summary.add_artifact_document")
    @patch("topic_summary.llm_chat")
    def test_bare_catalog_ids_bracketed_in_final_artifact(
        self, mock_llm, mock_add_art, mock_add_snap, rich_db
    ):
        """Bare E2 and A1 in narrator output must become [E2] and [A1] in the artifact."""
        import re
        database.init_db(rich_db)
        mock_llm.side_effect = [self._BAD_EXTRACTOR, self._BAD_NARRATOR]
        topic_summary.generate_evolution_report_sync(301)
        artifact = database.get_synthesis_artifact(301, "evolution_report")
        assert artifact is not None
        content = artifact["content"]
        # No bare E-digit or A-digit (without surrounding brackets)
        bare_e = re.search(r"(?<!\[)\bE\d+\b(?!\])", content)
        bare_a = re.search(r"(?<!\[)\bA\d+\b(?!\])", content)
        assert bare_e is None, (
            f"Bare event citation found in final content: {bare_e.group()!r}. "
            f"Snippet: {content[:300]!r}"
        )
        assert bare_a is None, (
            f"Bare article citation found in final content: {bare_a.group()!r}. "
            f"Snippet: {content[:300]!r}"
        )

    @patch("topic_summary.add_snapshot_document")
    @patch("topic_summary.add_artifact_document")
    @patch("topic_summary.llm_chat")
    def test_invalid_catalog_id_removed_from_final_artifact(
        self, mock_llm, mock_add_art, mock_add_snap, rich_db
    ):
        """[E99] is not in the catalog and must be stripped from the final artifact."""
        database.init_db(rich_db)
        mock_llm.side_effect = [self._BAD_EXTRACTOR, self._BAD_NARRATOR]
        topic_summary.generate_evolution_report_sync(301)
        artifact = database.get_synthesis_artifact(301, "evolution_report")
        assert artifact is not None
        content = artifact["content"]
        assert "E99" not in content, (
            f"Invalid citation E99 must not appear in final content. Snippet: {content[:300]!r}"
        )

    @patch("topic_summary.add_snapshot_document")
    @patch("topic_summary.add_artifact_document")
    @patch("topic_summary.llm_chat")
    def test_valid_catalog_id_kept_in_final_artifact(
        self, mock_llm, mock_add_art, mock_add_snap, rich_db
    ):
        """[E1] is valid and must remain in the final artifact as [E1]."""
        database.init_db(rich_db)
        mock_llm.side_effect = [self._BAD_EXTRACTOR, self._BAD_NARRATOR]
        topic_summary.generate_evolution_report_sync(301)
        artifact = database.get_synthesis_artifact(301, "evolution_report")
        assert artifact is not None
        content = artifact["content"]
        assert "[E1]" in content, (
            f"Valid citation [E1] must be present in final content. Snippet: {content[:300]!r}"
        )
