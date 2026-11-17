"""Regression cases for semantic shortcuts discovered in the design audit."""
from datetime import datetime, timezone

import pytest

import relevance
import topic_summary
from eventkb.store import Store


def test_short_keywords_do_not_admit_unrelated_documents():
    keywords = ["AI chips", "Alibaba Qwen", "US"]
    noise = [{"title": title, "content": title} for title in (
        "New chair elected at university library", "Music festival schedule announced")]
    assert relevance.filter_by_relevance(noise, keywords) == []
    assert relevance.score_relevance({"title": "US approves AI chips", "content": ""}, keywords) > 0
    assert relevance._kw_matches("asx200", "asx 200 outlook")
    assert relevance._kw_matches("rba 利率", "rba raises rates")


def test_distinct_release_versions_survive_similarity_stages():
    items = [{"title": f"Alibaba releases Qwen {version} model for enterprise use",
              "content": "The model is available for enterprise developers worldwide.",
              "url": f"https://example.invalid/{version}",
              "published_date": "2026-01-01T10:00:00Z"} for version in ("3.5", "3.6")]
    assert len(relevance.dedup_by_similarity(items)) == 2
    assert len(relevance.cluster_by_event(items)) == 2


def test_comparison_keys_preserve_resource_parameters_and_ports():
    assert relevance.normalize_url("http://127.0.0.1:9005/report?id=2") == "http://127.0.0.1:9005/report?id=2"
    assert "cid=alpha" in relevance.normalize_url("https://example.invalid/report?cid=alpha&utm_source=test")
    assert "v=abc123" in relevance.normalize_url("https://youtube.com/watch?v=abc123&utm_source=test")
    assert relevance._parse_date("2026-01-01T12:00:00+0200") == datetime(2026, 1, 1, 10, tzinfo=timezone.utc)


def test_leaving_a_snapshot_does_not_end_an_event(monkeypatch):
    monkeypatch.setattr(topic_summary, "get_snapshot_events", lambda sid: [{"id": "A" if sid == 1 else "B", "status": "active"}])
    monkeypatch.setattr(topic_summary, "get_snapshot_claims", lambda sid: [])
    monkeypatch.setattr(topic_summary, "get_claim_evolution", lambda *a, **kw: [])
    delta = topic_summary._build_delta_summary(1, 2, 1)
    assert delta["left_report_event_ids"] == ["A"]
    assert delta["resolved_event_ids"] == []
    assert "left the report" in delta["change_summary"]
    assert "resolved events" not in delta["change_summary"]


def test_evolution_bundle_keeps_report_departure_separate(monkeypatch):
    monkeypatch.setattr(topic_summary, "get_temporal_snapshots", lambda *a, **kw: [{"id": 2}, {"id": 1}])
    monkeypatch.setattr(topic_summary, "get_snapshot_deltas", lambda *a, **kw: [])
    monkeypatch.setattr(topic_summary, "_get_topic_research_context", lambda *a: {})
    monkeypatch.setattr(topic_summary, "get_snapshot_events", lambda sid: [{"id": "A" if sid == 1 else "B", "title": "Active release"}])
    monkeypatch.setattr(topic_summary, "get_snapshot_claims", lambda sid: [])
    monkeypatch.setattr(topic_summary, "get_claim_evolution", lambda *a, **kw: [])
    monkeypatch.setattr(topic_summary, "list_evidence_sets", lambda *a, **kw: [])
    bundle = topic_summary._load_evolution_fact_bundle(1)
    facts = topic_summary._build_rule_based_diff_facts(bundle, set())
    assert [event["id"] for event in bundle.left_report_events] == ["A"]
    assert not bundle.resolved_events
    assert not any(change["kind"] == "resolved" for change in facts.event_transitions)


def test_unknown_publication_time_is_not_fabricated(tmp_path):
    store = Store(tmp_path / "memory.sqlite3")
    evidence = store.add_evidence(source_key="unknown-publication", revision="1", publisher="Test source",
                                  url="https://example.invalid/source", body="Available at 2026-01-01T10:00:00Z.",
                                  published_at="")
    assert evidence["published_at"] == ""
    with pytest.raises(ValueError):
        store.add_evidence(source_key="bad-publication", revision="1", publisher="Test source",
                           url="https://example.invalid/source", body="Source", published_at="yesterday")


def test_composed_store_writes_roll_back_together(tmp_path):
    store = Store(tmp_path / "memory.sqlite3")
    with pytest.raises(RuntimeError):
        with store.atomic():
            store.create_event(event_id="release", topic="topic:1", identity_key="release-1", title="Release")
            store.add_evidence(source_key="source", revision="1", publisher="Test", published_at="",
                               url="https://example.invalid", body="Original source")
            raise RuntimeError("simulated worker crash")
    with store.connection() as db:
        assert db.execute("SELECT count(*) FROM events").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM evidence").fetchone()[0] == 0
    store.create_event(event_id="release", topic="topic:1", identity_key="release-1", title="Release")
    assert store.state("release")["event"]["id"] == "release"


def test_saved_briefing_is_marked_stale_after_authoritative_change(monkeypatch):
    import main
    monkeypatch.setattr(main.settings, "event_memory_enabled", True)
    state = {"event": {"id": "release"}, "fields": {"status": {"value": "announced", "assertion_ids": ["a1"]}}}
    monkeypatch.setattr(topic_summary, "_memory_briefing", lambda topic_id: {"events": [state]})
    assert main._memory_report_status(1, {})["event_memory_stale"]
    captured = {"event_memory_inputs": [state]}
    assert not main._memory_report_status(1, captured)["event_memory_stale"]
    changed = {"event": {"id": "release"}, "fields": {"status": {"value": "available", "assertion_ids": ["a2"]}}}
    monkeypatch.setattr(topic_summary, "_memory_briefing", lambda topic_id: {"events": [changed]})
    assert main._memory_report_status(1, captured)["event_memory_stale"]
    assert captured["event_memory_inputs"][0]["fields"]["status"]["value"] == "announced"
