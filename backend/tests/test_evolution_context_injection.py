"""
Deterministic tests for evolution report context injection.

These tests verify that the correct context sections are assembled and
injected into the LLM calls — WITHOUT making any real LLM API calls.
The `llm_chat` function is mocked so results are fully reproducible.

Two-stage pipeline notes:
  - Stage B (extractor): first llm_chat call — call_args_list[0]
  - Stage C (narrator):  second llm_chat call — call_args_list[1] / call_args

Run with:
    cd backend && python -m pytest tests/test_evolution_context_injection.py -v
"""

import json
import os
import sqlite3
import sys
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database
import topic_summary


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def db_path(tmp_path_factory):
    """Temporary SQLite DB with minimal seed data for two snapshots."""
    path = str(tmp_path_factory.mktemp("db") / "test_monitor.db")
    database.init_db(path)

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row

    conn.execute("INSERT INTO topics (id, name, is_active) VALUES (99, 'Test Topic', 1)")

    now = datetime.now(timezone.utc)
    for i in range(1, 4):
        conn.execute(
            """INSERT INTO articles
               (id, title, summary, source, url, topic_id, importance, status, created_at)
               VALUES (?,?,?,?,?,99,9,'active',?)""",
            (
                f"art-{i}",
                f"Article {i} about test topic",
                f"Summary of article {i} with specific details.",
                "TestSource",
                f"https://example.com/art{i}",
                now.isoformat(),
            ),
        )

    for i in range(1, 3):
        conn.execute(
            """INSERT INTO events_v2
               (id, topic_id, event_key, title, summary, status, first_seen_at, last_seen_at, created_at)
               VALUES (?,99,?,?,?,'active',?,?,?)""",
            (
                f"evt-{i}",
                f"test-event-key-{i}",
                f"Event {i}: Specific Happening",
                f"Detailed description of event {i}.",
                (now - timedelta(days=2)).isoformat(),
                now.isoformat(),
                now.isoformat(),
            ),
        )

    claim_ids = [str(uuid.uuid4()) for _ in range(2)]
    for i, cid in enumerate(claim_ids, 1):
        conn.execute(
            """INSERT INTO claims
               (id, topic_id, statement, status, staleness_status, claim_type, created_at, updated_at)
               VALUES (?,99,?,'active','fresh','observation',?,?)""",
            (
                cid,
                f"Specific claim {i}: something measurable happened.",
                now.isoformat(),
                now.isoformat(),
            ),
        )

    snap1_id = conn.execute(
        """INSERT INTO temporal_snapshots
           (topic_id, summary_text, window_type, snapshot_status, window_end, created_at)
           VALUES (99, 'Baseline snapshot summary. Early developments.', 'daily', 'final', ?, ?)""",
        (
            (now - timedelta(hours=2)).isoformat(),
            (now - timedelta(hours=2)).isoformat(),
        ),
    ).lastrowid

    snap2_id = conn.execute(
        """INSERT INTO temporal_snapshots
           (topic_id, summary_text, window_type, snapshot_status, window_end, created_at)
           VALUES (99, 'Current snapshot summary. Later developments emerged.', 'daily', 'final', ?, ?)""",
        (now.isoformat(), now.isoformat()),
    ).lastrowid

    # evt-1 in T1 only → resolved; evt-2 in TN only → new
    conn.execute("INSERT INTO snapshot_events (snapshot_id, event_id) VALUES (?,?)", (snap1_id, "evt-1"))
    conn.execute("INSERT INTO snapshot_events (snapshot_id, event_id) VALUES (?,?)", (snap2_id, "evt-2"))

    # claim[0] in T1 only → dropped; claim[1] in TN only → new
    conn.execute("INSERT INTO snapshot_claims (snapshot_id, claim_id) VALUES (?,?)", (snap1_id, claim_ids[0]))
    conn.execute("INSERT INTO snapshot_claims (snapshot_id, claim_id) VALUES (?,?)", (snap2_id, claim_ids[1]))

    conn.execute(
        """INSERT INTO snapshot_deltas
           (topic_id, from_snapshot_id, to_snapshot_id, change_summary,
            new_event_ids, resolved_event_ids, strengthened_claim_ids,
            weakened_claim_ids, superseded_claim_ids, metadata_json)
           VALUES (99,?,?,'1 new event, 1 resolved event',?,?,?,?,?,?)""",
        (
            snap1_id, snap2_id,
            json.dumps(["evt-2"]), json.dumps(["evt-1"]),
            json.dumps([]), json.dumps([]), json.dumps([]), json.dumps({}),
        ),
    )

    conn.commit()
    conn.close()
    return path


@pytest.fixture(autouse=True)
def use_test_db(db_path):
    database.init_db(db_path)
    yield


# ── Fake responses ────────────────────────────────────────────────────────────

FAKE_EXTRACTOR_JSON = json.dumps({
    "top_changes": [
        {"change_id": "TC1", "priority": 1, "entity_type": "event",
         "novelty": "emerged_cluster", "narrative_role": "observed_change",
         "statement": "Event 2 emerged while Event 1 resolved, marking a structural shift.",
         "context": "Primary change this period.", "citation_ids": [],
         "source_entity_ids": ["EV1", "EV2"]},
    ],
    "event_transitions": [
        {"change_id": "EV1", "priority": 1, "narrative_role": "event_shift",
         "kind": "emerged", "entity_id": "evt-2", "title": "Event 2: Specific Happening",
         "statement": "Event 2 emerged with specific details.", "citation_ids": [],
         "derived_from_change_ids": ["TC1"]},
        {"change_id": "EV2", "priority": 2, "narrative_role": "event_shift",
         "kind": "resolved", "entity_id": "evt-1", "title": "Event 1: Specific Happening",
         "statement": "Event 1 resolved.", "citation_ids": [],
         "derived_from_change_ids": ["TC1"]},
    ],
    "claim_trajectories": [
        {"change_id": "CL1", "priority": 1, "narrative_role": "claim_shift",
         "kind": "emerged", "entity_id": "claim-x", "statement": "Specific claim 2 appeared.",
         "context": "Emerged in current snapshot.", "citation_ids": [],
         "supported_by_event_ids": ["EV1"]},
        {"change_id": "CL2", "priority": 2, "narrative_role": "claim_shift",
         "kind": "dropped", "entity_id": "claim-y", "statement": "Specific claim 1 dropped.",
         "context": "", "citation_ids": [], "supported_by_event_ids": []},
    ],
    "strategic_implications": [
        {"change_id": "SI1", "narrative_role": "implication",
         "statement": "The shift from event 1 to event 2 represents a structural change.",
         "derived_from_change_ids": ["TC1"], "citation_ids": []},
    ],
})

FAKE_NARRATOR_RESPONSE = """## 1. Observed Changes
Event 2 emerged while Event 1 resolved. Specific claim 2 appeared as Specific claim 1 dropped.

## 2. Event-Level Shifts
Event 2: Specific Happening emerged with specific details. Event 1: Specific Happening resolved.

## 3. Claim Trajectories
Specific claim 2 emerged with measurable evidence. Specific claim 1 was dropped.

## 4. Strategic Implications
The shift from event 1 to event 2 represents a structural change.
"""


def _get_call_messages(mock_llm, call_index: int):
    """Return the messages list from the Nth call to the mocked llm_chat."""
    assert mock_llm.called, "llm_chat was never called"
    assert len(mock_llm.call_args_list) > call_index, (
        f"Expected at least {call_index + 1} calls, got {len(mock_llm.call_args_list)}"
    )
    return mock_llm.call_args_list[call_index][0][0]


def _get_extractor_call(mock_llm):
    return _get_call_messages(mock_llm, 0)


def _get_narrator_call(mock_llm):
    """Last call is always the narrator."""
    return mock_llm.call_args[0][0]


# ── Tests: Stage B (extractor) injection ─────────────────────────────────────

class TestExtractorInjection:
    """Verify the extractor (Stage B) receives the right diff signals."""

    @patch("topic_summary.llm_chat", side_effect=[FAKE_EXTRACTOR_JSON, FAKE_NARRATOR_RESPONSE])
    @patch("topic_summary.add_artifact_document")
    @patch("topic_summary.replace_synthesis_artifact", return_value="fake-artifact-id")
    def test_extractor_gets_new_events_section(self, mock_repl, mock_add, mock_llm):
        topic_summary.generate_evolution_report_sync(99)
        user_msg = _get_extractor_call(mock_llm)[1]["content"]
        assert "=== New Events [+] ===" in user_msg, (
            "Extractor user message must contain '=== New Events [+] ===' section"
        )

    @patch("topic_summary.llm_chat", side_effect=[FAKE_EXTRACTOR_JSON, FAKE_NARRATOR_RESPONSE])
    @patch("topic_summary.add_artifact_document")
    @patch("topic_summary.replace_synthesis_artifact", return_value="fake-artifact-id")
    def test_extractor_gets_new_claims_section(self, mock_repl, mock_add, mock_llm):
        topic_summary.generate_evolution_report_sync(99)
        user_msg = _get_extractor_call(mock_llm)[1]["content"]
        assert "=== New Claims [+] ===" in user_msg, (
            "Extractor user message must contain '=== New Claims [+] ===' section"
        )

    @patch("topic_summary.llm_chat", side_effect=[FAKE_EXTRACTOR_JSON, FAKE_NARRATOR_RESPONSE])
    @patch("topic_summary.add_artifact_document")
    @patch("topic_summary.replace_synthesis_artifact", return_value="fake-artifact-id")
    def test_extractor_gets_new_event_marker(self, mock_repl, mock_add, mock_llm):
        topic_summary.generate_evolution_report_sync(99)
        user_msg = _get_extractor_call(mock_llm)[1]["content"]
        assert "[NE-" in user_msg, "Extractor user message must contain [NE-N] markers"

    @patch("topic_summary.llm_chat", side_effect=[FAKE_EXTRACTOR_JSON, FAKE_NARRATOR_RESPONSE])
    @patch("topic_summary.add_artifact_document")
    @patch("topic_summary.replace_synthesis_artifact", return_value="fake-artifact-id")
    def test_extractor_gets_new_claim_marker(self, mock_repl, mock_add, mock_llm):
        topic_summary.generate_evolution_report_sync(99)
        user_msg = _get_extractor_call(mock_llm)[1]["content"]
        assert "[NC-" in user_msg, "Extractor user message must contain [NC-N] markers"

    @patch("topic_summary.llm_chat", side_effect=[FAKE_EXTRACTOR_JSON, FAKE_NARRATOR_RESPONSE])
    @patch("topic_summary.add_artifact_document")
    @patch("topic_summary.replace_synthesis_artifact", return_value="fake-artifact-id")
    def test_extractor_gets_citation_catalog(self, mock_repl, mock_add, mock_llm):
        topic_summary.generate_evolution_report_sync(99)
        user_msg = _get_extractor_call(mock_llm)[1]["content"]
        assert "[Citation Catalog]" in user_msg, (
            "Extractor user message must contain a [Citation Catalog] block"
        )

    @patch("topic_summary.llm_chat", side_effect=[FAKE_EXTRACTOR_JSON, FAKE_NARRATOR_RESPONSE])
    @patch("topic_summary.add_artifact_document")
    @patch("topic_summary.replace_synthesis_artifact", return_value="fake-artifact-id")
    def test_extractor_system_prompt_is_extractor_system(self, mock_repl, mock_add, mock_llm):
        topic_summary.generate_evolution_report_sync(99)
        system_msg = _get_extractor_call(mock_llm)[0]["content"]
        assert "temporal-change analyst" in system_msg.lower(), (
            "Extractor system prompt must be EVOLUTION_EXTRACTOR_SYSTEM"
        )

    @patch("topic_summary.llm_chat", side_effect=[FAKE_EXTRACTOR_JSON, FAKE_NARRATOR_RESPONSE])
    @patch("topic_summary.add_artifact_document")
    @patch("topic_summary.replace_synthesis_artifact", return_value="fake-artifact-id")
    def test_extractor_does_not_get_snapshot_prose(self, mock_repl, mock_add, mock_llm):
        """Extractor should NOT receive full snapshot prose — only diff signals."""
        topic_summary.generate_evolution_report_sync(99)
        user_msg = _get_extractor_call(mock_llm)[1]["content"]
        # The extractor user message should NOT contain the full baseline snapshot header
        # (that's reserved for the debug context renderer, not the extractor)
        assert "=== Baseline Snapshot [T1" not in user_msg, (
            "Extractor user message must NOT contain full snapshot prose sections"
        )


# ── Tests: Stage C (narrator) injection ──────────────────────────────────────

class TestNarratorInjection:
    """Verify the narrator (Stage C) receives extracted facts, not raw snapshots."""

    @patch("topic_summary.llm_chat", side_effect=[FAKE_EXTRACTOR_JSON, FAKE_NARRATOR_RESPONSE])
    @patch("topic_summary.add_artifact_document")
    @patch("topic_summary.replace_synthesis_artifact", return_value="fake-artifact-id")
    def test_narrator_gets_extracted_facts(self, mock_repl, mock_add, mock_llm):
        topic_summary.generate_evolution_report_sync(99)
        user_msg = _get_narrator_call(mock_llm)[1]["content"]
        assert "=== Extracted Change Facts ===" in user_msg, (
            "Narrator user message must contain '=== Extracted Change Facts ==='"
        )

    @patch("topic_summary.llm_chat", side_effect=[FAKE_EXTRACTOR_JSON, FAKE_NARRATOR_RESPONSE])
    @patch("topic_summary.add_artifact_document")
    @patch("topic_summary.replace_synthesis_artifact", return_value="fake-artifact-id")
    def test_narrator_gets_citation_catalog(self, mock_repl, mock_add, mock_llm):
        topic_summary.generate_evolution_report_sync(99)
        user_msg = _get_narrator_call(mock_llm)[1]["content"]
        assert "[Citation Catalog]" in user_msg

    @patch("topic_summary.llm_chat", side_effect=[FAKE_EXTRACTOR_JSON, FAKE_NARRATOR_RESPONSE])
    @patch("topic_summary.add_artifact_document")
    @patch("topic_summary.replace_synthesis_artifact", return_value="fake-artifact-id")
    def test_narrator_gets_tier_note(self, mock_repl, mock_add, mock_llm):
        topic_summary.generate_evolution_report_sync(99)
        user_msg = _get_narrator_call(mock_llm)[1]["content"]
        assert "Signal Tier:" in user_msg, (
            "Narrator user message must contain 'Signal Tier:' annotation"
        )

    @patch("topic_summary.llm_chat", side_effect=[FAKE_EXTRACTOR_JSON, FAKE_NARRATOR_RESPONSE])
    @patch("topic_summary.add_artifact_document")
    @patch("topic_summary.replace_synthesis_artifact", return_value="fake-artifact-id")
    def test_narrator_system_prompt_is_narrator_system(self, mock_repl, mock_add, mock_llm):
        topic_summary.generate_evolution_report_sync(99)
        system_msg = _get_narrator_call(mock_llm)[0]["content"]
        assert "evolution report" in system_msg.lower(), (
            "Narrator system prompt must be EVOLUTION_NARRATOR_SYSTEM"
        )

    @patch("topic_summary.llm_chat", side_effect=[FAKE_EXTRACTOR_JSON, FAKE_NARRATOR_RESPONSE])
    @patch("topic_summary.add_artifact_document")
    @patch("topic_summary.replace_synthesis_artifact", return_value="fake-artifact-id")
    def test_narrator_does_not_get_raw_diff_markers(self, mock_repl, mock_add, mock_llm):
        """Narrator should not receive raw [NE]/[NC] diff markers from snapshot context."""
        topic_summary.generate_evolution_report_sync(99)
        user_msg = _get_narrator_call(mock_llm)[1]["content"]
        # Narrator gets structured JSON, not the raw diff markers
        assert "[NE-" not in user_msg and "[NC-" not in user_msg, (
            "Narrator user message must NOT contain raw extractor diff markers"
        )

    @patch("topic_summary.llm_chat", side_effect=[FAKE_EXTRACTOR_JSON, FAKE_NARRATOR_RESPONSE])
    @patch("topic_summary.add_artifact_document")
    @patch("topic_summary.replace_synthesis_artifact", return_value="fake-artifact-id")
    def test_narrator_gets_facts_as_json(self, mock_repl, mock_add, mock_llm):
        """Narrator should receive facts as valid JSON in the user message."""
        topic_summary.generate_evolution_report_sync(99)
        user_msg = _get_narrator_call(mock_llm)[1]["content"]
        # Find the JSON block between "=== Extracted Change Facts ===" and the next "==="
        import re
        # Match the JSON block up to the next section header (===) or citation block ([)
        m = re.search(
            r"=== Extracted Change Facts ===\n(\{.+?\})(?=\n\n|\n\[|\Z)",
            user_msg,
            re.DOTALL,
        )
        assert m, "Could not find Extracted Change Facts JSON block in narrator message"
        try:
            data = json.loads(m.group(1).strip())
        except json.JSONDecodeError as e:
            pytest.fail(f"Facts block is not valid JSON: {e}")
        assert "top_changes" in data
        assert "event_transitions" in data
        assert "claim_trajectories" in data


# ── Tests: two-stage pipeline structure ──────────────────────────────────────

class TestTwostageStructure:
    """Verify the pipeline makes the correct number of LLM calls."""

    @patch("topic_summary.llm_chat", side_effect=[FAKE_EXTRACTOR_JSON, FAKE_NARRATOR_RESPONSE])
    @patch("topic_summary.add_artifact_document")
    @patch("topic_summary.replace_synthesis_artifact", return_value="fake-artifact-id")
    def test_full_tier_makes_two_llm_calls(self, mock_repl, mock_add, mock_llm):
        """Full tier (diff signals present) should make 2 LLM calls."""
        topic_summary.generate_evolution_report_sync(99)
        assert mock_llm.call_count == 2, (
            f"Expected 2 llm_chat calls for full tier, got {mock_llm.call_count}"
        )

    @patch("topic_summary.llm_chat", return_value=FAKE_NARRATOR_RESPONSE)
    @patch("topic_summary.add_artifact_document")
    @patch("topic_summary.replace_synthesis_artifact", return_value="fake-artifact-id")
    def test_artifact_source_is_two_stage(self, mock_repl, mock_add, mock_llm):
        """Persisted artifact metadata should indicate two_stage_evolution source."""
        topic_summary.generate_evolution_report_sync(99)
        _, kwargs = mock_repl.call_args
        assert kwargs.get("metadata", {}).get("source") == "two_stage_evolution", (
            "Artifact metadata 'source' must be 'two_stage_evolution'"
        )

    @patch("topic_summary.llm_chat", side_effect=[FAKE_EXTRACTOR_JSON, FAKE_NARRATOR_RESPONSE])
    @patch("topic_summary.add_artifact_document")
    @patch("topic_summary.replace_synthesis_artifact", return_value="fake-artifact-id")
    def test_artifact_has_three_stage_diagnostics(self, mock_repl, mock_add, mock_llm):
        """Artifact metadata diagnostics must include all 3 stage keys."""
        topic_summary.generate_evolution_report_sync(99)
        _, kwargs = mock_repl.call_args
        diag = kwargs.get("metadata", {}).get("diagnostics", {})
        for key in ("stage_context", "stage_facts", "stage_narrative"):
            assert key in diag, f"Diagnostics missing key '{key}'"


# ── Tests: tier classification ─────────────────────────────────────────────────

class TestTierClassification:
    """Verify _build_evolution_context_v2 wrapper returns the correct tier."""

    def test_full_tier_when_diff_exists(self):
        ctx, err, tier = topic_summary._build_evolution_context_v2(99)
        assert err is None
        assert tier == "full", f"Expected 'full' tier, got '{tier}'"

    def test_context_contains_baseline_and_current(self):
        ctx, err, tier = topic_summary._build_evolution_context_v2(99)
        assert err is None
        assert "=== Baseline Snapshot" in ctx
        assert "=== Current Snapshot" in ctx

    def test_skip_tier_on_empty_topic(self):
        conn = sqlite3.connect(database.DB_PATH)
        conn.execute("INSERT OR IGNORE INTO topics (id, name) VALUES (999, 'Empty Topic')")
        conn.commit()
        conn.close()
        ctx, err, tier = topic_summary._build_evolution_context_v2(999)
        assert tier == "skip"
        assert err is not None
        assert ctx is None


# ── Tests: legacy diagnostics structure (backward compat) ─────────────────────

class TestDiagnosticsStructure:
    """Verify _collect_evolution_diagnostics returns expected keys (legacy compat)."""

    def test_diagnostics_keys_present(self):
        ctx, err, tier = topic_summary._build_evolution_context_v2(99)
        citations = topic_summary._build_evolution_citation_catalog(99, "", "")
        diag = topic_summary._collect_evolution_diagnostics(
            ctx=ctx or "",
            user_content="test user content",
            citations=citations,
            raw_llm_out="raw output",
            result="result [E1]",
            tier=tier,
        )
        required_keys = {
            "tier", "context_length", "user_content_length",
            "section_names", "section_lengths", "diff_signals",
            "citation_ids_available", "citation_ids_used",
            "citations_used_count", "raw_llm_out_length",
            "result_length", "result_hash", "generated_at",
        }
        assert required_keys.issubset(set(diag.keys())), (
            f"Missing keys: {required_keys - set(diag.keys())}"
        )

    def test_diagnostics_diff_signals_count(self):
        ctx, err, tier = topic_summary._build_evolution_context_v2(99)
        diag = topic_summary._collect_evolution_diagnostics(
            ctx=ctx or "", user_content="", citations=[],
            raw_llm_out="", result="", tier=tier,
        )
        signals = diag["diff_signals"]
        assert signals["new_events"] >= 1, f"Expected ≥1 new_events signal, got {signals}"
        assert signals["new_claims"] >= 1, f"Expected ≥1 new_claims signal, got {signals}"


# ── Tests: generic detector ───────────────────────────────────────────────────

class TestGenericDetector:
    """Verify _detect_generic_output flags low-signal results correctly."""

    def test_specific_result_not_flagged(self):
        ctx, _, _ = topic_summary._build_evolution_context_v2(99)
        citations = [
            {"id": "E1", "type": "event", "title": "t1", "url": "u1"},
            {"id": "A1", "type": "article", "title": "t2", "url": "u2"},
        ]
        specific_result = (
            "Event 2: Specific Happening emerged [E1] while Specific claim 2 strengthened [A1]. "
            "## 1. Observed Changes\nEvent 2 appeared with specific details.\n"
            "## 2. Event-Level Shifts\nEvent 2 emerged, Event 1 resolved [E1].\n"
            "## 3. Claim Trajectories\nSpecific claim 2 emerged [A1].\n"
            "## 4. Strategic Implications\nShifts occurred [E1] in the domain [A1]."
        )
        result = topic_summary._detect_generic_output(specific_result, ctx or "", citations)
        assert not result["is_generic"], (
            f"Specific result should NOT be flagged as generic. Flags: {result['flags']}"
        )

    def test_empty_result_flagged(self):
        ctx, _, _ = topic_summary._build_evolution_context_v2(99)
        citations = [{"id": "E1", "type": "event", "title": "t", "url": "u"}]
        generic_result = (
            "In the bigger picture, the macro narrative shifted. "
            "Broadly speaking, strategic balance and risk profile changed overall."
        )
        result = topic_summary._detect_generic_output(generic_result, ctx or "", citations)
        assert "few_citations" in result["flags"]

    def test_result_without_citations_flagged(self):
        ctx, _, _ = topic_summary._build_evolution_context_v2(99)
        citations = [{"id": "E1", "type": "event", "title": "t", "url": "u"}]
        result = topic_summary._detect_generic_output(
            "Something happened without any citations.", ctx or "", citations
        )
        assert "few_citations" in result["flags"]


# ── Tests: context builder standalone ─────────────────────────────────────────

class TestContextBuilderStandalone:
    """Test _build_evolution_context_v2 wrapper independently."""

    def test_returns_three_tuple(self):
        result = topic_summary._build_evolution_context_v2(99)
        assert len(result) == 3

    def test_context_is_string(self):
        ctx, err, tier = topic_summary._build_evolution_context_v2(99)
        assert isinstance(ctx, str)
        assert err is None
        assert isinstance(tier, str)

    def test_context_not_empty(self):
        ctx, _, _ = topic_summary._build_evolution_context_v2(99)
        assert len(ctx) > 100

    def test_event_2_in_new_events_section(self):
        ctx, _, _ = topic_summary._build_evolution_context_v2(99)
        import re
        ne_blocks = re.findall(r"\[NE\][^\n]*", ctx)
        assert any("Event 2" in b for b in ne_blocks), (
            f"Event 2 should appear in [NE] markers. Got: {ne_blocks}"
        )

    def test_claim_in_dropped_section(self):
        ctx, _, _ = topic_summary._build_evolution_context_v2(99)
        import re
        dc_blocks = re.findall(r"\[DC\][^\n]*", ctx)
        assert len(dc_blocks) >= 1

    def test_citation_catalog_time_span(self):
        now = datetime.now(timezone.utc)
        oldest = (now - timedelta(days=3)).isoformat()
        citations = topic_summary._build_evolution_citation_catalog(99, oldest, now.isoformat())
        assert isinstance(citations, list)
