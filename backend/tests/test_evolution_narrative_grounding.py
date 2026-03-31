"""
Tests for the narrator stage (Stage C) — narrative grounding and diagnostics.

Covers:
- _build_narrator_user_message: correct inputs, no raw snapshot prose
- _collect_stage_narrative_diagnostics: grounding and citation metrics
- Groundedness: final output traces back to extracted facts
- Full pipeline: provisional tier skips extractor

Run with:
    cd backend && python -m pytest tests/test_evolution_narrative_grounding.py -v
"""

import hashlib
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
    _build_narrator_user_message,
    _collect_stage_narrative_diagnostics,
    _build_rule_based_diff_facts,
    _detect_generic_output,
    _normalize_citations,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_minimal_bundle(tier: str = "full") -> EvolutionFactBundle:
    return EvolutionFactBundle(
        topic_id=1,
        tier=tier,
        error=None,
        research_context={
            "brief": "Track AI regulatory developments",
            "angles": ["policy", "industry"],
            "entities": ["OpenAI", "EU"],
            "geographic_scope": ["EU"],
        },
        baseline_snapshot={
            "id": 1,
            "summary_text": "Initial EU AI Act debate underway with broad stakeholder engagement.",
            "window_end": "2024-01-01T00:00:00",
        },
        current_snapshot={
            "id": 2,
            "summary_text": "EU AI Act passed first reading; major providers announced compliance plans.",
            "window_end": "2024-01-02T00:00:00",
        },
        intermediate_snapshots=[],
        baseline_events=[
            {"id": "ev1", "title": "EU AI Act debate", "summary": "Debate ongoing",
             "event_status": "active", "first_seen_at": "", "last_seen_at": ""},
        ],
        current_events=[
            {"id": "ev2", "title": "EU AI Act passed first reading", "summary": "Passed first reading",
             "event_status": "active", "first_seen_at": "", "last_seen_at": ""},
        ],
        baseline_claims=[
            {"id": "cl1", "statement": "EU AI Act will face strong industry opposition.",
             "staleness_status": "stale", "claim_type": "prediction", "summary": ""},
        ],
        current_claims=[
            {"id": "cl2", "statement": "Major AI providers announced EU AI Act compliance plans.",
             "staleness_status": "fresh", "claim_type": "observation", "summary": ""},
        ],
        new_events=[
            {"id": "ev2", "title": "EU AI Act passed first reading", "summary": "Passed first reading",
             "event_status": "active", "first_seen_at": "", "last_seen_at": ""},
        ],
        resolved_events=[
            {"id": "ev1", "title": "EU AI Act debate", "summary": "Debate concluded",
             "event_status": "resolved", "first_seen_at": "", "last_seen_at": ""},
        ],
        new_claims=[
            {"id": "cl2", "statement": "Major AI providers announced EU AI Act compliance plans.",
             "staleness_status": "fresh", "claim_type": "observation", "summary": ""},
        ],
        dropped_claims=[
            {"id": "cl1", "statement": "EU AI Act will face strong industry opposition.",
             "staleness_status": "stale", "claim_type": "prediction"},
        ],
        persisted_claims=[],
        claim_evolution_records=[],
        snapshot_deltas=[],
        evidence_sets=[],
    )


def _make_diff_facts(citations: list | None = None) -> DiffFacts:
    cit_ids = [c["id"] for c in (citations or [])][:1]
    return DiffFacts(
        top_changes=[
            {"change_id": "TC1", "priority": 1, "entity_type": "event",
             "novelty": "emerged_cluster", "narrative_role": "observed_change",
             "statement": "EU AI Act advanced to first reading, reshaping provider compliance landscape.",
             "context": "Major regulatory milestone passed.",
             "citation_ids": cit_ids, "source_entity_ids": ["EV1", "CL1"]},
            {"change_id": "TC2", "priority": 2, "entity_type": "claim_cluster",
             "novelty": "resolved_cluster", "narrative_role": "observed_change",
             "statement": "Industry opposition claims dropped as providers announced compliance.",
             "context": "Prediction proved inaccurate.",
             "citation_ids": [], "source_entity_ids": ["CL2"]},
        ],
        event_transitions=[
            {"change_id": "EV1", "priority": 1, "narrative_role": "event_shift",
             "kind": "emerged", "entity_id": "ev2",
             "title": "EU AI Act passed first reading",
             "statement": "EU AI Act passed its first reading in the European Parliament.",
             "citation_ids": cit_ids, "derived_from_change_ids": ["TC1"]},
            {"change_id": "EV2", "priority": 2, "narrative_role": "event_shift",
             "kind": "resolved", "entity_id": "ev1",
             "title": "EU AI Act debate",
             "statement": "The initial EU AI Act debate concluded.",
             "citation_ids": [], "derived_from_change_ids": ["TC1"]},
        ],
        claim_trajectories=[
            {"change_id": "CL1", "priority": 1, "narrative_role": "claim_shift",
             "kind": "emerged", "entity_id": "cl2",
             "statement": "Major AI providers announced EU AI Act compliance plans.",
             "context": "Appeared after first reading", "citation_ids": [],
             "supported_by_event_ids": ["EV1"]},
            {"change_id": "CL2", "priority": 2, "narrative_role": "claim_shift",
             "kind": "dropped", "entity_id": "cl1",
             "statement": "EU AI Act will face strong industry opposition.",
             "context": "Proved inaccurate once providers announced compliance.",
             "citation_ids": [], "supported_by_event_ids": []},
        ],
        strategic_implications=[
            {"change_id": "SI1", "narrative_role": "implication",
             "statement": "Regulatory compliance is now a competitive differentiator for AI providers.",
             "derived_from_change_ids": ["TC1", "TC2"], "citation_ids": []},
        ],
        validation_errors=[],
        raw_extractor_hash="abc12345",
    )


# ── Tests: _build_narrator_user_message ──────────────────────────────────────

class TestBuildNarratorUserMessage:

    def test_contains_extracted_facts(self):
        bundle = _make_minimal_bundle()
        facts = _make_diff_facts()
        msg = _build_narrator_user_message(facts, [], bundle, "full")
        assert "=== Extracted Change Facts ===" in msg

    def test_facts_are_valid_json(self):
        bundle = _make_minimal_bundle()
        facts = _make_diff_facts()
        msg = _build_narrator_user_message(facts, [], bundle, "full")
        import re
        m = re.search(r"=== Extracted Change Facts ===\n(\{.+?\})(?=\n\n|\n\[|\Z)", msg, re.DOTALL)
        assert m, "Could not find facts JSON block"
        data = json.loads(m.group(1).strip())
        assert "top_changes" in data
        assert "event_transitions" in data
        assert "claim_trajectories" in data

    def test_contains_citation_catalog(self):
        bundle = _make_minimal_bundle()
        facts = _make_diff_facts()
        citations = [{"id": "E1", "type": "event", "title": "Test", "url": "http://x.com"}]
        msg = _build_narrator_user_message(facts, citations, bundle, "full")
        assert "[Citation Catalog]" in msg

    def test_contains_tier_note(self):
        bundle = _make_minimal_bundle()
        facts = _make_diff_facts()
        msg = _build_narrator_user_message(facts, [], bundle, "full")
        assert "Signal Tier:" in msg
        assert "FULL" in msg

    def test_provisional_tier_note(self):
        bundle = _make_minimal_bundle(tier="provisional")
        facts = DiffFacts(
            top_changes=[], event_transitions=[], claim_trajectories=[], strategic_implications=[]
        )
        msg = _build_narrator_user_message(facts, [], bundle, "provisional")
        assert "PROVISIONAL" in msg

    def test_reference_context_present(self):
        bundle = _make_minimal_bundle()
        facts = _make_diff_facts()
        msg = _build_narrator_user_message(facts, [], bundle, "full")
        assert "=== Reference Context" in msg

    def test_no_raw_diff_markers(self):
        """Narrator must NOT receive raw [NE]/[NC]/[DC] diff markers."""
        bundle = _make_minimal_bundle()
        facts = _make_diff_facts()
        msg = _build_narrator_user_message(facts, [], bundle, "full")
        assert "[NE-" not in msg
        assert "[NC-" not in msg
        assert "[DC-" not in msg
        assert "[RE-" not in msg

    def test_no_explicit_diff_section(self):
        """Narrator must NOT receive the raw '=== Explicit Diff' section."""
        bundle = _make_minimal_bundle()
        facts = _make_diff_facts()
        msg = _build_narrator_user_message(facts, [], bundle, "full")
        assert "=== Explicit Diff" not in msg

    def test_no_baseline_snapshot_header(self):
        """Narrator should not receive full baseline snapshot prose as primary input."""
        bundle = _make_minimal_bundle()
        facts = _make_diff_facts()
        msg = _build_narrator_user_message(facts, [], bundle, "full")
        # The full "=== Baseline Snapshot [T1 ..." header should NOT appear
        assert "=== Baseline Snapshot [T1" not in msg

    def test_event_titles_in_facts_json(self):
        """Extracted event titles should appear in the JSON facts payload."""
        bundle = _make_minimal_bundle()
        facts = _make_diff_facts()
        msg = _build_narrator_user_message(facts, [], bundle, "full")
        assert "EU AI Act passed first reading" in msg

    def test_claim_statements_in_facts_json(self):
        bundle = _make_minimal_bundle()
        facts = _make_diff_facts()
        msg = _build_narrator_user_message(facts, [], bundle, "full")
        assert "Major AI providers announced" in msg


# ── Tests: _collect_stage_narrative_diagnostics ───────────────────────────────

class TestStageNarrativeDiagnostics:

    GROUNDED_NARRATIVE = """## 1. Observed Changes
EU AI Act passed first reading. Major AI providers announced compliance plans.

## 2. Event-Level Shifts
EU AI Act passed first reading emerged as a major milestone [E1].
The EU AI Act debate resolved as the legislative process advanced.

## 3. Claim Trajectories
Major AI providers announced EU AI Act compliance plans (emerged).
EU AI Act will face strong industry opposition was dropped after providers announced plans.

## 4. Strategic Implications
Regulatory compliance is now a competitive differentiator [E1].
"""

    GENERIC_NARRATIVE = (
        "In the bigger picture, the macro narrative shifted broadly. "
        "Strategic balance changed in a general sense."
    )

    def test_required_keys_present(self):
        facts = _make_diff_facts()
        citations = [{"id": "E1", "type": "event", "title": "T", "url": "U"}]
        diag = _collect_stage_narrative_diagnostics(self.GROUNDED_NARRATIVE, facts, citations)
        required = {
            "result_length", "result_hash", "citations_used", "citations_used_count",
            "facts_grounded_count", "facts_total_count", "generic_check", "generated_at",
        }
        assert required.issubset(set(diag.keys()))

    def test_grounded_narrative_scores_higher(self):
        facts = _make_diff_facts()
        citations = [{"id": "E1", "type": "event", "title": "T", "url": "U"}]
        diag_grounded = _collect_stage_narrative_diagnostics(self.GROUNDED_NARRATIVE, facts, citations)
        diag_generic = _collect_stage_narrative_diagnostics(self.GENERIC_NARRATIVE, facts, citations)
        assert diag_grounded["facts_grounded_count"] >= diag_generic["facts_grounded_count"], (
            "Grounded narrative should have higher grounding score than generic one"
        )

    def test_citations_counted(self):
        facts = _make_diff_facts()
        citations = [{"id": "E1", "type": "event", "title": "T", "url": "U"}]
        diag = _collect_stage_narrative_diagnostics(self.GROUNDED_NARRATIVE, facts, citations)
        assert "E1" in diag["citations_used"]
        assert diag["citations_used_count"] >= 1

    def test_result_hash_changes_with_content(self):
        facts = _make_diff_facts()
        citations = []
        diag1 = _collect_stage_narrative_diagnostics("Output A", facts, citations)
        diag2 = _collect_stage_narrative_diagnostics("Output B", facts, citations)
        assert diag1["result_hash"] != diag2["result_hash"]

    def test_generic_check_not_flagged_for_grounded(self):
        facts = _make_diff_facts()
        citations = [
            {"id": "E1", "type": "event", "title": "T1", "url": "U1"},
            {"id": "A1", "type": "article", "title": "T2", "url": "U2"},
        ]
        narrative = (
            "EU AI Act passed first reading [E1]. "
            "Major AI providers announced compliance plans [A1]. "
            "## 1. Observed Changes\nEU AI Act passed first reading [E1].\n"
            "## 2. Event-Level Shifts\nEU AI Act debate resolved [E1].\n"
            "## 3. Claim Trajectories\nMajor AI providers announced plans [A1].\n"
            "## 4. Strategic Implications\nCompliance is now a differentiator [E1]."
        )
        diag = _collect_stage_narrative_diagnostics(narrative, facts, citations)
        assert not diag["generic_check"]["is_generic"], (
            f"Grounded narrative should not be flagged as generic. "
            f"Flags: {diag['generic_check']['flags']}"
        )


# ── Tests: provisional tier pipeline ─────────────────────────────────────────

class TestProvisionalTierPipeline:
    """Verify provisional tier skips the extractor and uses rule-based facts."""

    @pytest.fixture(scope="class")
    def provisional_db(self, tmp_path_factory):
        path = str(tmp_path_factory.mktemp("prov") / "provisional.db")
        database.init_db(path)
        conn = sqlite3.connect(path)
        now = datetime.now(timezone.utc)

        conn.execute("INSERT INTO topics (id, name, is_active) VALUES (77, 'Provisional Topic', 1)")
        for i in range(1, 3):
            conn.execute(
                """INSERT INTO articles
                   (id, title, summary, source, url, topic_id, importance, status, created_at)
                   VALUES (?,?,?,?,?,77,9,'active',?)""",
                (f"pa{i}", f"Article {i}", f"Summary {i}", "S",
                 f"https://prov.com/{i}", now.isoformat()),
            )

        snap1 = conn.execute(
            """INSERT INTO temporal_snapshots
               (topic_id, summary_text, window_type, snapshot_status, window_end, created_at)
               VALUES (77,'Only snapshot.','daily','final',?,?)""",
            (now.isoformat(), now.isoformat()),
        ).lastrowid

        conn.commit()
        conn.close()
        return path

    def test_provisional_bundle_tier(self, provisional_db):
        database.init_db(provisional_db)
        bundle = topic_summary._load_evolution_fact_bundle(77)
        # One snapshot only → no diff possible → provisional
        assert bundle.tier in ("provisional", "skip")

    @patch("topic_summary.llm_chat", return_value="## 1. Observed Changes\nNo significant changes yet.")
    @patch("topic_summary.add_artifact_document")
    @patch("topic_summary.replace_synthesis_artifact", return_value="fake-id")
    def test_provisional_tier_makes_one_llm_call(self, mock_repl, mock_add, mock_llm, provisional_db):
        """Provisional tier should make only 1 LLM call (narrator only, no extractor)."""
        database.init_db(provisional_db)
        # If topic has no snapshots this returns early with error string
        result = topic_summary.generate_evolution_report_sync(77)
        # Either skip (no calls) or provisional (1 call)
        assert mock_llm.call_count <= 1, (
            f"Provisional/skip tier should make at most 1 LLM call, got {mock_llm.call_count}"
        )


# ── Tests: full pipeline integration ─────────────────────────────────────────

class TestFullPipelineIntegration:

    @pytest.fixture(scope="class")
    def full_db(self, tmp_path_factory):
        path = str(tmp_path_factory.mktemp("full") / "full.db")
        database.init_db(path)
        conn = sqlite3.connect(path)
        now = datetime.now(timezone.utc)

        conn.execute("INSERT INTO topics (id, name, is_active) VALUES (66, 'Full Test Topic', 1)")
        for i in range(1, 3):
            conn.execute(
                """INSERT INTO articles
                   (id, title, summary, source, url, topic_id, importance, status, created_at)
                   VALUES (?,?,?,?,?,66,9,'active',?)""",
                (f"fa{i}", f"Article {i}", f"Summary {i}", "S",
                 f"https://full.com/{i}", now.isoformat()),
            )
        for i in range(1, 3):
            conn.execute(
                """INSERT INTO events_v2
                   (id, topic_id, event_key, title, summary, status, first_seen_at, last_seen_at, created_at)
                   VALUES (?,66,?,?,?,'active',?,?,?)""",
                (f"fev{i}", f"fkey{i}", f"Full Event {i}", f"Summary {i}",
                 now.isoformat(), now.isoformat(), now.isoformat()),
            )
        cid = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO claims (id, topic_id, statement, status, staleness_status, claim_type, created_at, updated_at)
               VALUES (?,66,'Full claim assertion.','active','fresh','observation',?,?)""",
            (cid, now.isoformat(), now.isoformat()),
        )

        s1 = conn.execute(
            """INSERT INTO temporal_snapshots
               (topic_id, summary_text, window_type, snapshot_status, window_end, created_at)
               VALUES (66,'Baseline.','daily','final',?,?)""",
            ((now - timedelta(hours=3)).isoformat(), (now - timedelta(hours=3)).isoformat()),
        ).lastrowid
        s2 = conn.execute(
            """INSERT INTO temporal_snapshots
               (topic_id, summary_text, window_type, snapshot_status, window_end, created_at)
               VALUES (66,'Current.','daily','final',?,?)""",
            (now.isoformat(), now.isoformat()),
        ).lastrowid

        conn.execute("INSERT INTO snapshot_events (snapshot_id, event_id) VALUES (?,?)", (s1, "fev1"))
        conn.execute("INSERT INTO snapshot_events (snapshot_id, event_id) VALUES (?,?)", (s2, "fev2"))
        conn.execute("INSERT INTO snapshot_claims (snapshot_id, claim_id) VALUES (?,?)", (s2, cid))

        conn.commit()
        conn.close()
        return path

    FAKE_EXTRACTOR = json.dumps({
        "top_changes": [
            {"change_id": "TC1", "priority": 1, "entity_type": "event",
             "novelty": "emerged_cluster", "narrative_role": "observed_change",
             "statement": "Full Event 2 emerged this period.", "context": "Key shift",
             "citation_ids": [], "source_entity_ids": ["EV1"]},
        ],
        "event_transitions": [
            {"change_id": "EV1", "priority": 1, "narrative_role": "event_shift",
             "kind": "emerged", "entity_id": "fev2", "title": "Full Event 2",
             "statement": "Full Event 2 emerged.", "citation_ids": [],
             "derived_from_change_ids": ["TC1"]},
        ],
        "claim_trajectories": [],
        "strategic_implications": [],
    })

    FAKE_NARRATOR = (
        "## 1. Observed Changes\nFull Event 2 emerged.\n"
        "## 2. Event-Level Shifts\nFull Event 2 is significant.\n"
        "## 3. Claim Trajectories\nInsufficient evidence.\n"
        "## 4. Strategic Implications\nDomain shifted structurally."
    )

    @patch("topic_summary.llm_chat")
    @patch("topic_summary.add_artifact_document")
    @patch("topic_summary.replace_synthesis_artifact", return_value="fake-id")
    def test_full_pipeline_returns_narrative(self, mock_repl, mock_add, mock_llm, full_db):
        database.init_db(full_db)
        mock_llm.side_effect = [self.FAKE_EXTRACTOR, self.FAKE_NARRATOR]
        result = topic_summary.generate_evolution_report_sync(66)
        assert isinstance(result, str) and len(result) > 10

    @patch("topic_summary.llm_chat")
    @patch("topic_summary.add_artifact_document")
    @patch("topic_summary.replace_synthesis_artifact", return_value="fake-id")
    def test_full_pipeline_diagnostics_stored(self, mock_repl, mock_add, mock_llm, full_db):
        database.init_db(full_db)
        mock_llm.side_effect = [self.FAKE_EXTRACTOR, self.FAKE_NARRATOR]
        topic_summary.generate_evolution_report_sync(66)
        _, kwargs = mock_repl.call_args
        diag = kwargs["metadata"]["diagnostics"]
        assert "stage_context" in diag
        assert "stage_facts" in diag
        assert "stage_narrative" in diag
        assert diag["stage_context"]["new_events_count"] >= 1

    @patch("topic_summary.llm_chat")
    @patch("topic_summary.add_artifact_document")
    @patch("topic_summary.replace_synthesis_artifact", return_value="fake-id")
    def test_full_pipeline_stage_facts_has_top_changes(self, mock_repl, mock_add, mock_llm, full_db):
        database.init_db(full_db)
        mock_llm.side_effect = [self.FAKE_EXTRACTOR, self.FAKE_NARRATOR]
        topic_summary.generate_evolution_report_sync(66)
        _, kwargs = mock_repl.call_args
        diag = kwargs["metadata"]["diagnostics"]["stage_facts"]
        assert "top_changes_count" in diag
        assert diag["top_changes_count"] >= 1


# ── Tests: section contract validation ───────────────────────────────────────

class TestSectionContracts:
    """Verify the narrator user message and diagnostics enforce section contracts."""

    def test_narrator_message_passes_top_changes(self):
        """Narrator user message must include top_changes in the JSON payload."""
        bundle = _make_minimal_bundle()
        facts = _make_diff_facts()
        msg = _build_narrator_user_message(facts, [], bundle, "full")
        assert "top_changes" in msg

    def test_narrator_message_section_instruction_present(self):
        """Narrator user message must have explicit section routing instruction."""
        bundle = _make_minimal_bundle()
        facts = _make_diff_facts()
        msg = _build_narrator_user_message(facts, [], bundle, "full")
        assert "Section 1" in msg
        assert "top_changes" in msg

    def test_section_overlap_measured_in_diagnostics(self):
        """Diagnostics must measure overlap between Section 1 and Section 3."""
        facts = _make_diff_facts()
        citations = []
        narrative_with_repetition = (
            "## 1. Observed Changes\n"
            "Major providers announced compliance plans for EU regulations.\n\n"
            "## 2. Event-Level Shifts\nEU AI Act passed first reading.\n\n"
            "## 3. Claim Trajectories\n"
            "Major providers announced compliance plans — this is the same as Section 1.\n\n"
            "## 4. Strategic Implications\nCompliance became a differentiator."
        )
        narrative_without_repetition = (
            "## 1. Observed Changes\n"
            "The EU regulatory landscape shifted dramatically.\n\n"
            "## 2. Event-Level Shifts\nEU AI Act passed first reading.\n\n"
            "## 3. Claim Trajectories\n"
            "Specifically, compliance plans were announced by major providers.\n\n"
            "## 4. Strategic Implications\nCompliance became a differentiator."
        )
        diag_rep = _collect_stage_narrative_diagnostics(narrative_with_repetition, facts, citations)
        diag_no_rep = _collect_stage_narrative_diagnostics(narrative_without_repetition, facts, citations)
        assert "section1_section3_overlap" in diag_rep
        assert diag_rep["section1_section3_overlap"] >= diag_no_rep["section1_section3_overlap"], (
            "Repeated narrative should have higher section overlap score"
        )

    def test_insufficient_sections_counted(self):
        """Diagnostics must count sections that say 'Insufficient evidence'."""
        facts = _make_diff_facts()
        narrative_with_insufficient = (
            "## 1. Observed Changes\nSome changes occurred.\n\n"
            "## 2. Event-Level Shifts\nNo discrete event-level transitions this period.\n\n"
            "## 3. Claim Trajectories\nInsufficient evidence for this period.\n\n"
            "## 4. Strategic Implications\nCompliance matters."
        )
        diag = _collect_stage_narrative_diagnostics(narrative_with_insufficient, facts, [])
        assert "insufficient_sections" in diag

    def test_section_lengths_measured(self):
        """Diagnostics must record per-section lengths."""
        facts = _make_diff_facts()
        narrative = (
            "## 1. Observed Changes\nA.\n\n"
            "## 2. Event-Level Shifts\nB is longer content here.\n\n"
            "## 3. Claim Trajectories\nC.\n\n"
            "## 4. Strategic Implications\nD."
        )
        diag = _collect_stage_narrative_diagnostics(narrative, facts, [])
        assert "section_lengths" in diag
        assert isinstance(diag["section_lengths"], list)

    def test_narrator_message_contains_top_changes_in_payload(self):
        """The JSON payload in the narrator message must include top_changes array."""
        bundle = _make_minimal_bundle()
        facts = _make_diff_facts()
        msg = _build_narrator_user_message(facts, [], bundle, "full")
        import re
        m = re.search(r"=== Extracted Change Facts ===\n(\{.+?\})(?=\n\n|\n\[|\Z)", msg, re.DOTALL)
        assert m, "Could not find facts JSON block"
        data = json.loads(m.group(1).strip())
        assert "top_changes" in data
        assert len(data["top_changes"]) >= 1


# ── Tests: adequacy gate end-to-end ──────────────────────────────────────────

class TestAdequacyGateEndToEnd:
    """Verify that generate_evolution_report_sync respects the adequacy gate:
    - Narrator must NOT be called when gate suppresses.
    - replace_synthesis_artifact must NOT be called when gate suppresses.
    - Return value must NOT start with '## ' when suppressed.
    """

    @pytest.fixture(scope="class")
    def no_diff_db(self, tmp_path_factory):
        """DB with two snapshots that share identical events/claims → no diff signals."""
        path = str(tmp_path_factory.mktemp("nodiff") / "nodiff.db")
        database.init_db(path)
        conn = sqlite3.connect(path)
        now = datetime.now(timezone.utc)

        conn.execute("INSERT INTO topics (id, name, is_active) VALUES (55, 'No Diff Topic', 1)")

        for i in range(1, 3):
            conn.execute(
                """INSERT INTO articles
                   (id, title, summary, source, url, topic_id, importance, status, created_at)
                   VALUES (?,?,?,?,?,55,9,'active',?)""",
                (f"nd-art-{i}", f"Article {i}", f"Summary {i}", "S",
                 f"https://nodiff.com/{i}", now.isoformat()),
            )

        # Two snapshots with NO events or claims attached → zero diff signals
        s1 = conn.execute(
            """INSERT INTO temporal_snapshots
               (topic_id, summary_text, window_type, snapshot_status, window_end, created_at)
               VALUES (55,'Baseline no diff.','daily','final',?,?)""",
            ((now - timedelta(hours=2)).isoformat(), (now - timedelta(hours=2)).isoformat()),
        ).lastrowid
        s2 = conn.execute(
            """INSERT INTO temporal_snapshots
               (topic_id, summary_text, window_type, snapshot_status, window_end, created_at)
               VALUES (55,'Current no diff.','daily','final',?,?)""",
            (now.isoformat(), now.isoformat()),
        ).lastrowid

        conn.commit()
        conn.close()
        return path

    @patch("topic_summary.llm_chat")
    @patch("topic_summary.add_artifact_document")
    @patch("topic_summary.replace_synthesis_artifact", return_value="fake-id")
    def test_gate_suppresses_narrator_when_no_diff(self, mock_repl, mock_add, mock_llm, no_diff_db):
        """When two snapshots have zero diff signals, narrator must NOT be called."""
        database.init_db(no_diff_db)
        mock_llm.return_value = "should not reach narrator"
        result = topic_summary.generate_evolution_report_sync(55)
        assert mock_llm.call_count == 0, (
            f"Narrator (llm_chat) must NOT be called when gate suppresses. "
            f"Call count: {mock_llm.call_count}"
        )

    @patch("topic_summary.llm_chat")
    @patch("topic_summary.add_artifact_document")
    @patch("topic_summary.replace_synthesis_artifact", return_value="fake-id")
    def test_gate_suppresses_artifact_persist_when_no_diff(self, mock_repl, mock_add, mock_llm, no_diff_db):
        """When suppressed, replace_synthesis_artifact must NOT be called."""
        database.init_db(no_diff_db)
        mock_llm.return_value = "should not reach narrator"
        topic_summary.generate_evolution_report_sync(55)
        assert mock_repl.call_count == 0, (
            "replace_synthesis_artifact must NOT be called when gate suppresses"
        )

    @patch("topic_summary.llm_chat")
    @patch("topic_summary.add_artifact_document")
    @patch("topic_summary.replace_synthesis_artifact", return_value="fake-id")
    def test_gate_returns_non_markdown_when_suppressed(self, mock_repl, mock_add, mock_llm, no_diff_db):
        """Suppressed result must not start with '## ' so the background task detects suppression."""
        database.init_db(no_diff_db)
        mock_llm.return_value = "should not reach narrator"
        result = topic_summary.generate_evolution_report_sync(55)
        assert result is not None
        assert not result.startswith("## "), (
            f"Suppressed result must not start with '## '. Got: {result[:80]!r}"
        )

    @patch("topic_summary.llm_chat", side_effect=[
        json.dumps({"top_changes": [], "event_transitions": [], "claim_trajectories": [], "strategic_implications": []}),
        "should not be called",
    ])
    @patch("topic_summary.add_artifact_document")
    @patch("topic_summary.replace_synthesis_artifact", return_value="fake-id")
    def test_gate_suppresses_when_extractor_returns_empty_facts(self, mock_repl, mock_add, mock_llm):
        """Full tier where extractor returns empty JSON (no facts) must suppress narrator."""
        # Use the existing full-tier db fixture via direct bundle manipulation
        bundle = _make_minimal_bundle(tier="full")
        # Empty diff facts (extractor returned nothing)
        empty_facts = DiffFacts(
            top_changes=[], event_transitions=[], claim_trajectories=[], strategic_implications=[]
        )
        from topic_summary import _assess_evolution_adequacy, _collect_stage_facts_diagnostics
        stage_facts_diag = _collect_stage_facts_diagnostics(empty_facts)
        should_emit, reason = _assess_evolution_adequacy(bundle, stage_facts_diag)
        assert should_emit is False, (
            "Gate must suppress when extractor returns empty top_changes, event_transitions, and p1_claims"
        )
        assert reason is not None


# ── Tests: _normalize_citations ───────────────────────────────────────────────

class TestNormalizeCitations:
    """Unit tests for _normalize_citations: bracket normalization, internal ID
    cleanup, and bare catalog ID detection."""

    CATALOG = [
        {"id": "E1", "type": "event", "title": "Event One", "url": "https://ex.com/1"},
        {"id": "E5", "type": "event", "title": "Event Five", "url": "https://ex.com/5"},
        {"id": "A1", "type": "article", "title": "Article One", "url": "https://ex.com/a1"},
        {"id": "A3", "type": "article", "title": "Article Three", "url": "https://ex.com/a3"},
    ]

    # ── bracket normalization ─────────────────────────────────────────────────

    def test_round_bracket_e_id_converted(self):
        result = _normalize_citations("事件发生了 (E1)。", self.CATALOG)
        assert "[E1]" in result
        assert "(E1)" not in result

    def test_round_bracket_a_id_converted(self):
        result = _normalize_citations("报道显示 (A1)。", self.CATALOG)
        assert "[A1]" in result
        assert "(A1)" not in result

    def test_lowercase_bracket_uppercased(self):
        result = _normalize_citations("分析显示 [e1] 和 [a3]。", self.CATALOG)
        assert "[E1]" in result
        assert "[A3]" in result
        assert "[e1]" not in result
        assert "[a3]" not in result

    def test_see_reference_converted(self):
        result = _normalize_citations("参见 (see E1)。", self.CATALOG)
        assert "[E1]" in result
        assert "(see E1)" not in result

    # ── invalid catalog ID removal ─────────────────────────────────────────────

    def test_invalid_bracketed_id_removed(self):
        """[E99] is not in catalog → must be stripped entirely."""
        result = _normalize_citations("信号 [E99] 出现。", self.CATALOG)
        assert "[E99]" not in result
        assert "E99" not in result

    def test_valid_bracketed_id_kept(self):
        result = _normalize_citations("信号 [E5] 出现。", self.CATALOG)
        assert "[E5]" in result

    # ── internal DiffFacts ID stripping ──────────────────────────────────────

    def test_bracketed_tc_id_stripped(self):
        result = _normalize_citations("鉴于 [TC1] 的政策收紧。", self.CATALOG)
        assert "TC1" not in result

    def test_bare_tc_id_stripped(self):
        result = _normalize_citations("鉴于 TC1 和 TC2 的影响。", self.CATALOG)
        assert "TC1" not in result
        assert "TC2" not in result

    def test_bare_ev_id_stripped(self):
        result = _normalize_citations("由事件 EV1 支持。", self.CATALOG)
        assert "EV1" not in result

    def test_bare_cl_id_stripped(self):
        result = _normalize_citations("参考 CL3 中的主张。", self.CATALOG)
        assert "CL3" not in result

    def test_bare_si_id_stripped(self):
        result = _normalize_citations("依据 SI2 的战略含义。", self.CATALOG)
        assert "SI2" not in result

    def test_multiple_internal_ids_all_stripped(self):
        text = "鉴于 TC1 和 TC3 中提到的政策收紧，结合 EV2 和 CL1 的影响。"
        result = _normalize_citations(text, self.CATALOG)
        for token in ("TC1", "TC3", "EV2", "CL1"):
            assert token not in result, f"Expected {token!r} to be stripped"

    # ── bare external catalog ID normalization ────────────────────────────────

    def test_bare_e5_in_chinese_text_bracketed(self):
        """LLM outputs 'E5' without brackets → must become '[E5]'."""
        result = _normalize_citations("禁止经由加拿大转运 E5。", self.CATALOG)
        assert "[E5]" in result
        # Verify it's not still bare (not already-bracketed regex may leave bare)
        import re
        assert not re.search(r"(?<!\[)E5(?!\])", result), (
            f"Bare 'E5' must not appear in result: {result!r}"
        )

    def test_bare_a1_in_chinese_text_bracketed(self):
        result = _normalize_citations("销售目标 A1 上升。", self.CATALOG)
        assert "[A1]" in result
        import re
        assert not re.search(r"(?<!\[)A1(?!\])", result)

    def test_bare_id_not_in_catalog_removed(self):
        """Bare 'E9' is not in catalog → must be removed, not bracketed."""
        result = _normalize_citations("信号 E9 出现。", self.CATALOG)
        assert "E9" not in result

    def test_already_bracketed_not_double_bracketed(self):
        """[E1] already has brackets → must not become [[E1]]."""
        result = _normalize_citations("报告 [E1] 显示。", self.CATALOG)
        assert "[[E1]]" not in result
        assert "[E1]" in result

    def test_combined_bad_narrator_output_fully_sanitized(self):
        """Simulates a realistic 'bad' LLM output with all three problem types."""
        bad_text = (
            "## 1. Observed Changes\n"
            "政策范围扩大至第三方转运路径 E5，明确关闭了漏洞。\n\n"
            "## 2. Event-Level Shifts\n"
            "事件重构，从潜在漏洞转为强硬壁垒 (E1)。\n\n"
            "## 3. Claim Trajectories\n"
            "由事件 EV1 支持 E5。比亚迪海外市场将持续高增，由事件 EV2 支持 A1。\n\n"
            "## 4. Strategic Implications\n"
            "鉴于 TC1 和 TC2 中提到的政策收紧 E5。结合 TC3 的影响 A1。\n"
            "引用不存在 [E99]。\n"
        )
        result = _normalize_citations(bad_text, self.CATALOG)

        # Internal IDs all gone
        for token in ("TC1", "TC2", "TC3", "EV1", "EV2"):
            assert token not in result, f"{token!r} must be stripped"

        # Invalid catalog ID gone
        assert "E99" not in result

        # Valid catalog IDs are bracketed
        assert "[E5]" in result
        assert "[E1]" in result
        assert "[A1]" in result

        # No bare valid IDs remaining
        import re
        for cid in ("E5", "A1", "E1"):
            assert not re.search(rf"(?<!\[){re.escape(cid)}(?!\])", result), (
                f"Bare {cid!r} must not remain in: {result!r}"
            )


# ── Tests: generic vs grounded narrative regression ───────────────────────────

class TestGenericVsGroundedRegression:
    """Regression tests verifying _detect_generic_output correctly distinguishes
    grounded narratives from templated generic output."""

    CATALOG = [
        {"id": "E1", "type": "event", "title": "New EV Policy Emerged", "url": "https://ex.com/1"},
        {"id": "A1", "type": "article", "title": "BYD Sales Report", "url": "https://ex.com/a1"},
    ]

    # A narrative that references specific names, specific changes, and uses citations
    GROUNDED = (
        "## 1. Observed Changes\n"
        "US trade enforcement has explicitly closed third-country transit routes for Chinese EVs [E1], "
        "marking a significant escalation from border controls to systematic channel blocking. "
        "BYD continues to raise international sales targets despite rising trade barriers [A1].\n\n"
        "## 2. Event-Level Shifts\n"
        "The announcement that 'Chinese EVs cannot enter the US from Canada' [E1] reframed prior "
        "ambiguity as a hard policy wall, eliminating the Canada transit loophole entirely.\n\n"
        "## 3. Claim Trajectories\n"
        "The claim that US trade enforcement covers third-party transit routes strengthened [E1]. "
        "BYD's international growth target increase emerged as a new strategic signal [A1].\n\n"
        "## 4. Strategic Implications\n"
        "Closure of the Canada route will accelerate supply chain decoupling [E1], forcing "
        "manufacturers to localise production outside North America to preserve market access."
    )

    # Vague, no entity names, no citations, no direction verbs
    GENERIC = (
        "## 1. Observed Changes\n"
        "The macro narrative shifted broadly across the monitored domain. "
        "Strategic balance changed in a general sense.\n\n"
        "## 2. Event-Level Shifts\n"
        "In the bigger picture, events evolved as expected.\n\n"
        "## 3. Claim Trajectories\n"
        "Claims continued to develop along the observed trajectory.\n\n"
        "## 4. Strategic Implications\n"
        "Ongoing monitoring is warranted as the situation continues to unfold."
    )

    def _make_rich_diff_facts(self) -> DiffFacts:
        return DiffFacts(
            top_changes=[
                {"change_id": "TC1", "priority": 1, "entity_type": "event",
                 "novelty": "emerged_cluster", "narrative_role": "observed_change",
                 "statement": "US trade enforcement closed Canada transit route for Chinese EVs.",
                 "context": "New hard policy barrier.",
                 "citation_ids": ["E1"], "source_entity_ids": ["EV1"]},
            ],
            event_transitions=[
                {"change_id": "EV1", "priority": 1, "narrative_role": "event_shift",
                 "kind": "emerged", "entity_id": "ev1",
                 "title": "Chinese EVs cannot enter the US from Canada",
                 "statement": "New hard barrier confirmed.",
                 "citation_ids": ["E1"], "derived_from_change_ids": ["TC1"]},
            ],
            claim_trajectories=[
                {"change_id": "CL1", "priority": 1, "narrative_role": "claim_shift",
                 "kind": "strengthened", "entity_id": "cl1",
                 "statement": "US trade enforcement covers third-party transit routes.",
                 "context": "Confirmed by diplomatic statement.",
                 "citation_ids": ["E1"], "supported_by_event_ids": ["EV1"]},
            ],
            strategic_implications=[
                {"change_id": "SI1", "narrative_role": "implication",
                 "statement": "Supply chain decoupling will accelerate.",
                 "derived_from_change_ids": ["TC1"], "citation_ids": ["E1"]},
            ],
        )

    def test_generic_narrative_flagged_as_generic(self):
        """Vague template-style output must be detected as generic."""
        facts = self._make_rich_diff_facts()
        diag = _collect_stage_narrative_diagnostics(self.GENERIC, facts, self.CATALOG)
        assert diag["generic_check"]["is_generic"] is True, (
            f"Generic narrative must be flagged. Flags: {diag['generic_check']['flags']}"
        )

    def test_grounded_narrative_not_flagged_as_generic(self):
        """Specific, cited narrative must NOT be flagged as generic."""
        facts = self._make_rich_diff_facts()
        diag = _collect_stage_narrative_diagnostics(self.GROUNDED, facts, self.CATALOG)
        assert diag["generic_check"]["is_generic"] is False, (
            f"Grounded narrative must not be flagged as generic. "
            f"Flags: {diag['generic_check']['flags']}"
        )

    def test_grounded_scores_more_facts_than_generic(self):
        """Grounded narrative must ground more facts than the generic one."""
        facts = self._make_rich_diff_facts()
        diag_g = _collect_stage_narrative_diagnostics(self.GROUNDED, facts, self.CATALOG)
        diag_n = _collect_stage_narrative_diagnostics(self.GENERIC, facts, self.CATALOG)
        assert diag_g["facts_grounded_count"] > diag_n["facts_grounded_count"], (
            f"Grounded: {diag_g['facts_grounded_count']}, "
            f"Generic: {diag_n['facts_grounded_count']} — grounded must be higher"
        )

    def test_grounded_uses_citations(self):
        """Grounded narrative must use at least 2 distinct citation IDs."""
        facts = self._make_rich_diff_facts()
        diag = _collect_stage_narrative_diagnostics(self.GROUNDED, facts, self.CATALOG)
        assert diag["citations_used_count"] >= 2, (
            f"Grounded narrative must use ≥2 citations. Got: {diag['citations_used_count']}"
        )

    def test_generic_uses_no_citations(self):
        """Generic narrative contains no citation markers → zero citations used."""
        facts = self._make_rich_diff_facts()
        diag = _collect_stage_narrative_diagnostics(self.GENERIC, facts, self.CATALOG)
        assert diag["citations_used_count"] == 0, (
            f"Generic narrative has no [E1]/[A1] markers. Got: {diag['citations_used_count']}"
        )
