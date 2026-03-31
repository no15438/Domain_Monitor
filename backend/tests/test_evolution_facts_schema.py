"""
Tests for the extractor stage (Stage B) of the two-stage evolution pipeline.

Covers:
- _build_extractor_user_message: correct diff signals injected
- _extract_diff_facts_llm: valid JSON parsed correctly, invalid JSON falls back
- _build_rule_based_diff_facts: rule-based construction from bundle
- DiffFacts schema: required fields present

Run with:
    cd backend && python -m pytest tests/test_evolution_facts_schema.py -v
"""

import json
import os
import sqlite3
import sys
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database
import topic_summary
from topic_summary import (
    EvolutionFactBundle,
    DiffFacts,
    _build_extractor_user_message,
    _build_rule_based_diff_facts,
    _extract_diff_facts_llm,
    _load_evolution_fact_bundle,
    _collect_stage_context_diagnostics,
    _collect_stage_facts_diagnostics,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def db_path(tmp_path_factory):
    path = str(tmp_path_factory.mktemp("db") / "test_facts.db")
    database.init_db(path)

    conn = sqlite3.connect(path)
    now = datetime.now(timezone.utc)

    conn.execute("INSERT INTO topics (id, name, is_active) VALUES (88, 'Facts Test Topic', 1)")

    for i in range(1, 3):
        conn.execute(
            """INSERT INTO articles
               (id, title, summary, source, url, topic_id, importance, status, created_at)
               VALUES (?,?,?,?,?,88,9,'active',?)""",
            (f"art-{i}", f"Article {i}", f"Summary {i}", "S", f"https://x.com/{i}", now.isoformat()),
        )

    for i in range(1, 3):
        conn.execute(
            """INSERT INTO events_v2
               (id, topic_id, event_key, title, summary, status, first_seen_at, last_seen_at, created_at)
               VALUES (?,88,?,?,?,'active',?,?,?)""",
            (
                f"ev{i}", f"key{i}", f"Test Event {i}", f"Event {i} summary",
                now.isoformat(), now.isoformat(), now.isoformat(),
            ),
        )

    claim_ids = [str(uuid.uuid4()) for _ in range(3)]
    for i, cid in enumerate(claim_ids, 1):
        conn.execute(
            """INSERT INTO claims
               (id, topic_id, statement, status, staleness_status, claim_type, created_at, updated_at)
               VALUES (?,88,?,'active','fresh','observation',?,?)""",
            (cid, f"Claim {i} assertion about the domain.", now.isoformat(), now.isoformat()),
        )

    snap1_id = conn.execute(
        """INSERT INTO temporal_snapshots
           (topic_id, summary_text, window_type, snapshot_status, window_end, created_at)
           VALUES (88,'Baseline text.','daily','final',?,?)""",
        ((now - timedelta(hours=4)).isoformat(), (now - timedelta(hours=4)).isoformat()),
    ).lastrowid

    snap2_id = conn.execute(
        """INSERT INTO temporal_snapshots
           (topic_id, summary_text, window_type, snapshot_status, window_end, created_at)
           VALUES (88,'Current text.','daily','final',?,?)""",
        (now.isoformat(), now.isoformat()),
    ).lastrowid

    # ev1 in T1 only → resolved; ev2 in TN only → new
    conn.execute("INSERT INTO snapshot_events (snapshot_id, event_id) VALUES (?,?)", (snap1_id, "ev1"))
    conn.execute("INSERT INTO snapshot_events (snapshot_id, event_id) VALUES (?,?)", (snap2_id, "ev2"))

    # claim_ids[0] in T1 only → dropped; claim_ids[1] in TN only → new; claim_ids[2] in both
    conn.execute("INSERT INTO snapshot_claims (snapshot_id, claim_id) VALUES (?,?)", (snap1_id, claim_ids[0]))
    conn.execute("INSERT INTO snapshot_claims (snapshot_id, claim_id) VALUES (?,?)", (snap2_id, claim_ids[1]))
    conn.execute("INSERT INTO snapshot_claims (snapshot_id, claim_id) VALUES (?,?)", (snap1_id, claim_ids[2]))
    conn.execute("INSERT INTO snapshot_claims (snapshot_id, claim_id) VALUES (?,?)", (snap2_id, claim_ids[2]))

    conn.commit()
    conn.close()
    return path


@pytest.fixture(autouse=True)
def use_test_db(db_path):
    database.init_db(db_path)
    yield


# ── Helper: minimal bundle ────────────────────────────────────────────────────

_DEFAULT_NEW_EVENTS = [
    {"id": "ev2", "title": "New Event", "summary": "new summary",
     "event_status": "active", "first_seen_at": "", "last_seen_at": ""},
]
_DEFAULT_RESOLVED_EVENTS = [
    {"id": "ev1", "title": "Old Event", "summary": "old summary",
     "event_status": "resolved", "first_seen_at": "", "last_seen_at": ""},
]
_DEFAULT_NEW_CLAIMS = [
    {"id": "cl2", "statement": "New current claim",
     "staleness_status": "fresh", "claim_type": "observation", "summary": ""},
]
_DEFAULT_DROPPED_CLAIMS = [
    {"id": "cl1", "statement": "Baseline claim",
     "staleness_status": "stale", "claim_type": "observation"},
]


def _make_minimal_bundle(
    *,
    tier: str = "full",
    new_events: list | None = None,
    resolved_events: list | None = None,
    new_claims: list | None = None,
    dropped_claims: list | None = None,
    persisted_claims: list | None = None,
) -> EvolutionFactBundle:
    """Build a minimal EvolutionFactBundle for unit tests.

    Pass an explicit empty list [] to get an empty field; pass None to get
    the default populated list.
    """
    return EvolutionFactBundle(
        topic_id=1,
        tier=tier,
        error=None,
        research_context={"brief": "", "angles": [], "entities": [], "geographic_scope": []},
        baseline_snapshot={"id": 1, "summary_text": "Baseline", "window_end": "2024-01-01T00:00:00"},
        current_snapshot={"id": 2, "summary_text": "Current", "window_end": "2024-01-02T00:00:00"},
        intermediate_snapshots=[],
        baseline_events=[{"id": "ev1", "title": "Old Event", "summary": "old summary",
                          "event_status": "resolved", "first_seen_at": "", "last_seen_at": ""}],
        current_events=[{"id": "ev2", "title": "New Event", "summary": "new summary",
                         "event_status": "active", "first_seen_at": "", "last_seen_at": ""}],
        baseline_claims=[{"id": "cl1", "statement": "Baseline claim", "staleness_status": "stale",
                          "claim_type": "observation", "summary": ""}],
        current_claims=[{"id": "cl2", "statement": "New current claim", "staleness_status": "fresh",
                         "claim_type": "observation", "summary": ""}],
        new_events=new_events if new_events is not None else _DEFAULT_NEW_EVENTS,
        resolved_events=resolved_events if resolved_events is not None else _DEFAULT_RESOLVED_EVENTS,
        new_claims=new_claims if new_claims is not None else _DEFAULT_NEW_CLAIMS,
        dropped_claims=dropped_claims if dropped_claims is not None else _DEFAULT_DROPPED_CLAIMS,
        persisted_claims=persisted_claims if persisted_claims is not None else [],
        claim_evolution_records=[],
        snapshot_deltas=[],
        evidence_sets=[],
    )


# ── Tests: _load_evolution_fact_bundle ────────────────────────────────────────

class TestLoadEvolutionFactBundle:

    def test_returns_fact_bundle(self):
        bundle = _load_evolution_fact_bundle(88)
        assert isinstance(bundle, EvolutionFactBundle)

    def test_full_tier_with_diff_signals(self):
        bundle = _load_evolution_fact_bundle(88)
        assert bundle.tier == "full"
        assert bundle.error is None

    def test_new_events_populated(self):
        bundle = _load_evolution_fact_bundle(88)
        assert len(bundle.new_events) >= 1, "Should have at least 1 new event (ev2)"

    def test_resolved_events_populated(self):
        bundle = _load_evolution_fact_bundle(88)
        assert len(bundle.resolved_events) >= 1, "Should have at least 1 resolved event (ev1)"

    def test_new_claims_populated(self):
        bundle = _load_evolution_fact_bundle(88)
        assert len(bundle.new_claims) >= 1

    def test_dropped_claims_populated(self):
        bundle = _load_evolution_fact_bundle(88)
        assert len(bundle.dropped_claims) >= 1

    def test_skip_tier_on_no_data(self):
        conn = sqlite3.connect(database.DB_PATH)
        conn.execute("INSERT OR IGNORE INTO topics (id, name) VALUES (888, 'Empty')")
        conn.commit()
        conn.close()
        bundle = _load_evolution_fact_bundle(888)
        assert bundle.tier == "skip"
        assert bundle.error is not None


# ── Tests: _build_extractor_user_message ─────────────────────────────────────

class TestBuildExtractorUserMessage:

    def test_contains_new_events_section(self):
        bundle = _make_minimal_bundle()
        citations = [{"id": "E1", "type": "event", "title": "Test Event", "url": "http://x.com"}]
        msg = _build_extractor_user_message(bundle, citations)
        assert "=== New Events [+] ===" in msg

    def test_contains_ne_markers(self):
        bundle = _make_minimal_bundle()
        citations = []
        msg = _build_extractor_user_message(bundle, citations)
        assert "[NE-0]" in msg

    def test_contains_nc_markers(self):
        bundle = _make_minimal_bundle()
        citations = []
        msg = _build_extractor_user_message(bundle, citations)
        assert "[NC-0]" in msg

    def test_contains_dc_markers(self):
        bundle = _make_minimal_bundle()
        citations = []
        msg = _build_extractor_user_message(bundle, citations)
        assert "[DC-0]" in msg

    def test_contains_re_markers(self):
        bundle = _make_minimal_bundle()
        citations = []
        msg = _build_extractor_user_message(bundle, citations)
        assert "[RE-0]" in msg

    def test_contains_citation_catalog(self):
        bundle = _make_minimal_bundle()
        citations = [{"id": "E1", "type": "event", "title": "Test Event", "url": "http://x.com"}]
        msg = _build_extractor_user_message(bundle, citations)
        assert "[Citation Catalog]" in msg

    def test_does_not_contain_snapshot_prose(self):
        """Extractor input should not contain full snapshot summary prose."""
        bundle = _make_minimal_bundle()
        msg = _build_extractor_user_message(bundle, [])
        assert "=== Baseline Snapshot [T1" not in msg
        assert "=== Current Snapshot [TN" not in msg

    def test_contains_tier_signal(self):
        bundle = _make_minimal_bundle()
        msg = _build_extractor_user_message(bundle, [])
        assert "Signal Tier: FULL" in msg

    def test_empty_bundle_minimal_output(self):
        bundle = _make_minimal_bundle(
            new_events=[], resolved_events=[], new_claims=[], dropped_claims=[]
        )
        msg = _build_extractor_user_message(bundle, [])
        assert "Signal Tier:" in msg
        assert "=== New Events [+] ===" not in msg


# ── Tests: _build_rule_based_diff_facts ───────────────────────────────────────

class TestBuildRuleBasedDiffFacts:

    def test_returns_diff_facts(self):
        bundle = _make_minimal_bundle()
        facts = _build_rule_based_diff_facts(bundle, set())
        assert isinstance(facts, DiffFacts)

    def test_new_events_become_emerged_transitions(self):
        bundle = _make_minimal_bundle()
        facts = _build_rule_based_diff_facts(bundle, set())
        emerged = [t for t in facts.event_transitions if t["kind"] == "emerged"]
        assert len(emerged) >= 1

    def test_resolved_events_become_resolved_transitions(self):
        bundle = _make_minimal_bundle()
        facts = _build_rule_based_diff_facts(bundle, set())
        resolved = [t for t in facts.event_transitions if t["kind"] == "resolved"]
        assert len(resolved) >= 1

    def test_new_claims_become_emerged_trajectories(self):
        bundle = _make_minimal_bundle()
        facts = _build_rule_based_diff_facts(bundle, set())
        emerged = [c for c in facts.claim_trajectories if c["kind"] == "emerged"]
        assert len(emerged) >= 1

    def test_dropped_claims_become_dropped_trajectories(self):
        bundle = _make_minimal_bundle()
        facts = _build_rule_based_diff_facts(bundle, set())
        dropped = [c for c in facts.claim_trajectories if c["kind"] == "dropped"]
        assert len(dropped) >= 1

    def test_no_validation_errors(self):
        bundle = _make_minimal_bundle()
        facts = _build_rule_based_diff_facts(bundle, set())
        assert len(facts.validation_errors) == 0

    def test_entity_ids_are_strings(self):
        bundle = _make_minimal_bundle()
        facts = _build_rule_based_diff_facts(bundle, set())
        for t in facts.event_transitions:
            assert isinstance(t["entity_id"], str)
        for c in facts.claim_trajectories:
            assert isinstance(c["entity_id"], str)

    def test_claim_evolution_strengthened_mapped(self):
        bundle = _make_minimal_bundle(new_events=[], resolved_events=[], new_claims=[], dropped_claims=[])
        bundle.claim_evolution_records = [
            {"relation_type": "strengthened", "claim_id": "cl-test", "reason": "More evidence appeared."}
        ]
        facts = _build_rule_based_diff_facts(bundle, set())
        strengthened = [c for c in facts.claim_trajectories if c["kind"] == "strengthened"]
        assert len(strengthened) >= 1


# ── Tests: _extract_diff_facts_llm ────────────────────────────────────────────

class TestExtractDiffFactsLlm:

    VALID_JSON = json.dumps({
        "top_changes": [
            {"change_id": "TC1", "priority": 1, "entity_type": "event",
             "novelty": "emerged_cluster", "narrative_role": "observed_change",
             "statement": "New Event emerged in this period.", "context": "Marks entry",
             "citation_ids": ["E1"], "source_entity_ids": ["NE-0"]},
        ],
        "event_transitions": [
            {"change_id": "EV1", "priority": 1, "narrative_role": "event_shift",
             "kind": "emerged", "entity_id": "ev2", "title": "New Event",
             "statement": "New Event emerged.", "citation_ids": ["E1"],
             "derived_from_change_ids": ["TC1"]},
        ],
        "claim_trajectories": [
            {"change_id": "CL1", "priority": 1, "narrative_role": "claim_shift",
             "kind": "emerged", "entity_id": "cl2",
             "statement": "New current claim appeared.", "context": "in TN",
             "citation_ids": [], "supported_by_event_ids": ["EV1"]},
        ],
        "strategic_implications": [
            {"change_id": "SI1", "narrative_role": "implication",
             "statement": "Domain shifted.", "derived_from_change_ids": ["TC1"],
             "citation_ids": []}
        ],
    })

    INVALID_JSON = "Not a JSON response at all."

    VALID_JSON_WITH_BAD_CITATIONS = json.dumps({
        "top_changes": [],
        "event_transitions": [
            {"change_id": "EV1", "priority": 1, "narrative_role": "event_shift",
             "kind": "emerged", "entity_id": "ev2", "title": "New Event",
             "statement": "New Event emerged.", "citation_ids": ["INVALID-99", "E1"],
             "derived_from_change_ids": []},
        ],
        "claim_trajectories": [],
        "strategic_implications": [],
    })

    def test_valid_json_parsed_correctly(self):
        bundle = _make_minimal_bundle()
        citations = [{"id": "E1", "type": "event", "title": "T", "url": "U"}]
        with patch("topic_summary.llm_chat", return_value=self.VALID_JSON):
            facts, diag = _extract_diff_facts_llm(bundle, citations)
        assert len(facts.top_changes) >= 1
        assert len(facts.event_transitions) == 1
        assert facts.event_transitions[0]["kind"] == "emerged"
        assert len(facts.claim_trajectories) == 1
        assert len(facts.strategic_implications) == 1
        assert not diag["is_fallback"]

    def test_invalid_json_triggers_fallback(self):
        bundle = _make_minimal_bundle()
        citations = []
        with patch("topic_summary.llm_chat", return_value=self.INVALID_JSON):
            facts, diag = _extract_diff_facts_llm(bundle, citations)
        assert diag["is_fallback"]
        assert len(diag["validation_errors"]) >= 1
        # Should still have facts from rule-based fallback
        assert len(facts.event_transitions) >= 1

    def test_invalid_citation_ids_filtered(self):
        """Citation IDs not in the catalog must be stripped from facts."""
        bundle = _make_minimal_bundle()
        citations = [{"id": "E1", "type": "event", "title": "T", "url": "U"}]
        with patch("topic_summary.llm_chat", return_value=self.VALID_JSON_WITH_BAD_CITATIONS):
            facts, diag = _extract_diff_facts_llm(bundle, citations)
        # INVALID-99 should be filtered; E1 should remain
        if not diag["is_fallback"]:
            cit_ids = facts.event_transitions[0]["citation_ids"]
            assert "INVALID-99" not in cit_ids
            assert "E1" in cit_ids

    def test_empty_facts_with_diff_signals_triggers_fallback(self):
        """If LLM returns empty facts but bundle has diff signals, apply fallback."""
        bundle = _make_minimal_bundle()
        citations = []
        empty_json = json.dumps({"event_transitions": [], "claim_trajectories": [],
                                  "strategic_implications": []})
        with patch("topic_summary.llm_chat", return_value=empty_json):
            facts, diag = _extract_diff_facts_llm(bundle, citations)
        # Should have applied rule-based fallback since bundle has diff signals
        assert len(facts.event_transitions) >= 1 or len(facts.claim_trajectories) >= 1

    def test_diagnostics_has_required_keys(self):
        bundle = _make_minimal_bundle()
        with patch("topic_summary.llm_chat", return_value=self.VALID_JSON):
            facts, diag = _extract_diff_facts_llm(bundle, [])
        required = {
            "raw_extractor_hash", "raw_extractor_length", "validation_errors",
            "top_changes_count", "event_transitions_count", "claim_trajectories_count",
            "strategic_implications_count", "is_fallback",
            "event_transitions_reframed", "claim_trajectories_priority1",
            "claim_trajectories_bound_to_events",
        }
        assert required.issubset(set(diag.keys()))

    def test_code_fence_stripped_from_json(self):
        bundle = _make_minimal_bundle()
        fenced = f"```json\n{self.VALID_JSON}\n```"
        with patch("topic_summary.llm_chat", return_value=fenced):
            facts, diag = _extract_diff_facts_llm(bundle, [])
        assert not diag["is_fallback"], "Code-fenced JSON should be parsed successfully"


# ── Tests: _collect_stage_context_diagnostics ────────────────────────────────

class TestStageContextDiagnostics:

    def test_returns_required_keys(self):
        bundle = _make_minimal_bundle()
        citations = [{"id": "E1", "type": "event", "title": "T", "url": "U"}]
        diag = _collect_stage_context_diagnostics(bundle, citations)
        required = {
            "tier", "snapshot_count", "new_events_count", "resolved_events_count",
            "new_claims_count", "dropped_claims_count", "persisted_claims_count",
            "claim_evolution_count", "evidence_sets_count", "citation_ids_available",
        }
        assert required.issubset(set(diag.keys()))

    def test_counts_match_bundle(self):
        bundle = _make_minimal_bundle()
        diag = _collect_stage_context_diagnostics(bundle, [])
        assert diag["new_events_count"] == len(bundle.new_events)
        assert diag["new_claims_count"] == len(bundle.new_claims)
        assert diag["dropped_claims_count"] == len(bundle.dropped_claims)

    def test_citation_ids_listed(self):
        bundle = _make_minimal_bundle()
        citations = [
            {"id": "E1", "type": "event", "title": "T1", "url": "U1"},
            {"id": "A2", "type": "article", "title": "T2", "url": "U2"},
        ]
        diag = _collect_stage_context_diagnostics(bundle, citations)
        assert "E1" in diag["citation_ids_available"]
        assert "A2" in diag["citation_ids_available"]


# ── Tests: _collect_stage_facts_diagnostics ───────────────────────────────────

class TestStageFactsDiagnostics:

    def test_returns_required_keys(self):
        bundle = _make_minimal_bundle()
        facts = _build_rule_based_diff_facts(bundle, set())
        diag = _collect_stage_facts_diagnostics(facts)
        required = {
            "raw_extractor_hash", "validation_errors", "is_fallback",
            "event_transitions_count", "claim_trajectories_count",
            "strategic_implications_count",
        }
        assert required.issubset(set(diag.keys()))

    def test_counts_match_facts(self):
        bundle = _make_minimal_bundle()
        facts = _build_rule_based_diff_facts(bundle, set())
        diag = _collect_stage_facts_diagnostics(facts)
        assert diag["event_transitions_count"] == len(facts.event_transitions)
        assert diag["claim_trajectories_count"] == len(facts.claim_trajectories)

    def test_no_fallback_for_clean_facts(self):
        bundle = _make_minimal_bundle()
        facts = _build_rule_based_diff_facts(bundle, set())
        diag = _collect_stage_facts_diagnostics(facts)
        assert not diag["is_fallback"]

    def test_top_changes_count_in_diagnostics(self):
        bundle = _make_minimal_bundle()
        facts = _build_rule_based_diff_facts(bundle, set())
        diag = _collect_stage_facts_diagnostics(facts)
        assert "top_changes_count" in diag
        assert diag["top_changes_count"] == len(facts.top_changes)

    def test_reframed_count_in_diagnostics(self):
        bundle = _make_minimal_bundle()
        facts = _build_rule_based_diff_facts(bundle, set())
        diag = _collect_stage_facts_diagnostics(facts)
        assert "event_transitions_reframed" in diag

    def test_priority1_count_in_diagnostics(self):
        bundle = _make_minimal_bundle()
        facts = _build_rule_based_diff_facts(bundle, set())
        diag = _collect_stage_facts_diagnostics(facts)
        assert "claim_trajectories_priority1" in diag


# ── Tests: new DiffFacts v2 schema fields ─────────────────────────────────────

class TestDiffFactsV2Schema:
    """Verify DiffFacts v2 schema has required fields in all list items."""

    def test_rule_based_top_changes_populated(self):
        """Rule-based facts should produce top_changes when diff signals exist."""
        bundle = _make_minimal_bundle()
        facts = _build_rule_based_diff_facts(bundle, set())
        assert len(facts.top_changes) >= 1, "Should have at least one top_change"

    def test_rule_based_top_changes_have_required_fields(self):
        bundle = _make_minimal_bundle()
        facts = _build_rule_based_diff_facts(bundle, set())
        for tc in facts.top_changes:
            assert "change_id" in tc
            assert "priority" in tc
            assert "narrative_role" in tc
            assert "statement" in tc

    def test_rule_based_event_transitions_have_change_id(self):
        bundle = _make_minimal_bundle()
        facts = _build_rule_based_diff_facts(bundle, set())
        for et in facts.event_transitions:
            assert "change_id" in et
            assert "narrative_role" in et
            assert et.get("narrative_role") == "event_shift"

    def test_rule_based_claim_trajectories_have_priority(self):
        bundle = _make_minimal_bundle()
        facts = _build_rule_based_diff_facts(bundle, set())
        for ct in facts.claim_trajectories:
            assert "priority" in ct
            assert ct["priority"] in (1, 2)

    def test_rule_based_claim_trajectories_have_supported_by_event_ids(self):
        bundle = _make_minimal_bundle()
        facts = _build_rule_based_diff_facts(bundle, set())
        for ct in facts.claim_trajectories:
            assert "supported_by_event_ids" in ct
            assert isinstance(ct["supported_by_event_ids"], list)

    def test_extractor_json_top_changes_parsed(self):
        """Valid extractor JSON with top_changes should be parsed into top_changes."""
        bundle = _make_minimal_bundle()
        valid_json_with_top_changes = json.dumps({
            "top_changes": [
                {"change_id": "TC1", "priority": 1, "entity_type": "claim_cluster",
                 "novelty": "emerged_cluster", "narrative_role": "observed_change",
                 "statement": "Iran policy claims surged.", "context": "Driven by diplomatic stance",
                 "citation_ids": [], "source_entity_ids": ["NC-0"]},
            ],
            "event_transitions": [],
            "claim_trajectories": [
                {"change_id": "CL1", "priority": 1, "narrative_role": "claim_shift",
                 "kind": "emerged", "entity_id": "NC-0",
                 "statement": "Iran policy hardened.", "context": "US stance",
                 "citation_ids": [], "supported_by_event_ids": []},
            ],
            "strategic_implications": [],
        })
        citations = []
        with patch("topic_summary.llm_chat", return_value=valid_json_with_top_changes):
            facts, _ = _extract_diff_facts_llm(bundle, citations)
        assert len(facts.top_changes) >= 1
        assert facts.top_changes[0]["change_id"] == "TC1"

    def test_extractor_json_event_derived_from_parsed(self):
        """event_transitions should have derived_from_change_ids parsed."""
        bundle = _make_minimal_bundle()
        valid_json = json.dumps({
            "top_changes": [
                {"change_id": "TC1", "priority": 1, "entity_type": "event",
                 "novelty": "emerged_cluster", "narrative_role": "observed_change",
                 "statement": "New Event emerged.", "context": "ctx",
                 "citation_ids": [], "source_entity_ids": []},
            ],
            "event_transitions": [
                {"change_id": "EV1", "priority": 1, "narrative_role": "event_shift",
                 "kind": "emerged", "entity_id": "ev2", "title": "New Event",
                 "statement": "New Event emerged.", "citation_ids": [],
                 "derived_from_change_ids": ["TC1"]},
            ],
            "claim_trajectories": [],
            "strategic_implications": [],
        })
        with patch("topic_summary.llm_chat", return_value=valid_json):
            facts, _ = _extract_diff_facts_llm(bundle, [])
        assert facts.event_transitions[0]["derived_from_change_ids"] == ["TC1"]

    def test_context_events_note_when_no_new_events(self):
        """When no new/resolved events, extractor message should have context events note."""
        bundle = _make_minimal_bundle(new_events=[], resolved_events=[])
        citations = [{"id": "E1", "type": "event", "title": "Context Event Title", "url": "http://x.com"}]
        msg = _build_extractor_user_message(bundle, citations)
        assert "Context Events" in msg
        assert "Context Event Title" in msg
        assert "synthesize" in msg.lower() or "reframed" in msg.lower()


# ── Tests: adequacy gate ─────────────────────────────────────────────────────

from topic_summary import _assess_evolution_adequacy


class TestAdequacyGate:
    """Verify _assess_evolution_adequacy correctly suppresses low-signal runs."""

    def _make_stage_facts_diag(
        self,
        top_changes: int = 2,
        event_transitions: int = 2,
        p1_claims: int = 1,
        is_fallback: bool = False,
        claim_trajectories: int = 1,
    ) -> dict:
        return {
            "top_changes_count": top_changes,
            "event_transitions_count": event_transitions,
            "claim_trajectories_priority1": p1_claims,
            "claim_trajectories_count": claim_trajectories,
            "is_fallback": is_fallback,
            "validation_errors": [],
            "raw_extractor_hash": "abc12345",
            "event_transitions_reframed": 0,
            "claim_trajectories_bound_to_events": 0,
            "strategic_implications_count": 0,
        }

    def test_normal_full_tier_passes(self):
        """Full tier with populated facts should pass the gate."""
        bundle = _make_minimal_bundle(tier="full")
        diag = self._make_stage_facts_diag()
        should_emit, reason = _assess_evolution_adequacy(bundle, diag)
        assert should_emit is True
        assert reason is None

    def test_provisional_with_diff_signals_passes(self):
        """Provisional tier that has new_claims should pass the gate."""
        bundle = _make_minimal_bundle(tier="provisional")
        diag = self._make_stage_facts_diag(top_changes=0, event_transitions=0, p1_claims=1)
        should_emit, reason = _assess_evolution_adequacy(bundle, diag)
        assert should_emit is True, f"Expected pass, got suppressed: {reason}"

    def test_provisional_no_diff_signals_suppressed(self):
        """Provisional tier with zero diff signals must be suppressed."""
        bundle = _make_minimal_bundle(
            tier="provisional",
            new_events=[],
            resolved_events=[],
            new_claims=[],
            dropped_claims=[],
        )
        bundle.claim_evolution_records = []
        diag = self._make_stage_facts_diag(top_changes=0, event_transitions=0, p1_claims=0)
        should_emit, reason = _assess_evolution_adequacy(bundle, diag)
        assert should_emit is False
        assert reason is not None
        assert "provisional" in reason

    def test_all_facts_zero_suppressed(self):
        """Any tier where top_changes==0 AND ev_transitions==0 AND p1_claims==0 must suppress."""
        bundle = _make_minimal_bundle(tier="full")
        diag = self._make_stage_facts_diag(top_changes=0, event_transitions=0, p1_claims=0)
        should_emit, reason = _assess_evolution_adequacy(bundle, diag)
        assert should_emit is False
        assert "insufficient structured facts" in reason

    def test_full_fallback_empty_facts_suppressed(self):
        """Full tier where extractor failed AND fallback also empty must suppress."""
        bundle = _make_minimal_bundle(tier="full")
        diag = self._make_stage_facts_diag(
            top_changes=0,
            event_transitions=0,
            p1_claims=0,
            is_fallback=True,
            claim_trajectories=0,
        )
        should_emit, reason = _assess_evolution_adequacy(bundle, diag)
        assert should_emit is False

    def test_gate_suppresses_returns_non_markdown(self):
        """Gate suppression reason must NOT start with '## ' (so background task detects it)."""
        bundle = _make_minimal_bundle(
            tier="provisional",
            new_events=[],
            resolved_events=[],
            new_claims=[],
            dropped_claims=[],
        )
        bundle.claim_evolution_records = []
        diag = self._make_stage_facts_diag(top_changes=0, event_transitions=0, p1_claims=0)
        should_emit, reason = _assess_evolution_adequacy(bundle, diag)
        assert should_emit is False
        assert reason is not None
        assert not reason.startswith("## "), (
            "Suppression reason must not start with '## ' — background task uses this to detect suppression"
        )

    def test_partial_facts_enough_passes(self):
        """Having only event_transitions (no top_changes) still passes when ev_trans > 0."""
        bundle = _make_minimal_bundle(tier="full")
        diag = self._make_stage_facts_diag(top_changes=0, event_transitions=1, p1_claims=0)
        should_emit, reason = _assess_evolution_adequacy(bundle, diag)
        assert should_emit is True, f"Expected pass with ev_transitions=1, got suppressed: {reason}"

    def test_only_p1_claims_enough_passes(self):
        """Having only p1 claim trajectories (no top_changes, no ev_trans) still passes."""
        bundle = _make_minimal_bundle(tier="full")
        diag = self._make_stage_facts_diag(top_changes=0, event_transitions=0, p1_claims=1)
        should_emit, reason = _assess_evolution_adequacy(bundle, diag)
        assert should_emit is True, f"Expected pass with p1_claims=1, got suppressed: {reason}"
