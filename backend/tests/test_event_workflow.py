"""Outcome checks for source capture, review, time and retry boundaries."""
import copy
import json
from pathlib import Path

import pytest

from event_workflow import Workflow


class Clock:
    value = "2026-02-01T10:00:00Z"

    def __call__(self):
        return self.value


@pytest.fixture
def workflow(tmp_path):
    clock = Clock()
    return Workflow(tmp_path / "events.sqlite3", clock=clock), clock


def source(version="3.5", status="announced", effective="2026-01-01T09:00:00Z", url=None, developer="Alibaba"):
    verb = {"announced": "announced", "available": "released", "withdrawn": "withdrew"}[status]
    quote = f"{developer} {verb} Qwen {version} at {effective}."
    item = {"title": f"Qwen {version} model release", "content": quote,
            "url": url or f"https://example.invalid/qwen-{version}-{status}", "source": "Official model bulletin",
            "published_date": "2026-01-03T11:00:00Z", "_source_type": "rss"}
    extraction = {"model_release": {"developer": developer, "model": "Qwen", "version": version,
                                   "status": status, "valid_from": effective, "quote": quote}}
    return item, extraction


def ingest(workflow, **kwargs):
    item, extraction = source(**kwargs)
    workflow.capture_documents(1, [item])
    return workflow.ingest_extraction(1, item, extraction)


def test_sources_are_immutable_shared_and_keep_original_url(workflow):
    w, clock = workflow
    item, _ = source(url="http://example.invalid:9005/report?cid=release&v=3.5")
    w.capture_documents(1, [item])
    w.capture_documents(2, [copy.deepcopy(item)])
    assert len(w.search_documents(1)) == len(w.search_documents(2)) == 1
    assert w.search_documents(1)[0]["url"] == item["url"]
    with w.store.connection() as db:
        assert db.execute("SELECT count(*) FROM workflow_documents").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM workflow_topic_documents").fetchone()[0] == 2
    changed = {**item, "content": item["content"] + " New captured text."}
    clock.value = "2026-02-02T10:00:00Z"
    w.capture_documents(1, [changed])
    assert len(w.search_documents(1)) == 2
    with pytest.raises(Exception, match="append-only"):
        with w.store.connection(write=True) as db:
            db.execute("UPDATE workflow_documents SET body='replacement'")


def test_single_source_becomes_event_and_source_passages_are_exact(workflow):
    w, _ = workflow
    candidate = ingest(w)
    assert candidate["review_status"] == "accepted"
    updates = w.list_updates(1)
    assert updates["coverage"]["migrated_kinds"] == ["ModelRelease"]
    assert len(updates["updates"]) == 1
    assert updates["updates"][0]["kind"] == "new_event"
    assert updates["updates"][0]["review_status"] == "machine_only"
    detail = w.event_detail(1, candidate["event_id"])
    assert detail["state"]["fields"]["status"]["value"] == "announced"
    for passage in detail["evidence"][0]["passages"]:
        assert detail["evidence"][0]["body"][passage["start"]:passage["end"]] == passage["quote"]
    assert detail["entities"][0]["canonical_name"] == "Alibaba"
    assert detail["entities"][0]["role"] == "developer"


def test_different_versions_are_distinct_and_aliases_share_developer(workflow):
    w, _ = workflow
    first = ingest(w)
    second = ingest(w, version="3.6")
    alias = ingest(w, developer="Alibaba Group", url="https://example.invalid/alias")
    assert first["event_id"] != second["event_id"]
    assert alias["event_id"] == first["event_id"]
    with w.store.connection() as db:
        assert db.execute("SELECT count(*) FROM workflow_entities").fetchone()[0] == 1


def test_updates_search_requires_the_exact_requested_version(workflow):
    w, _ = workflow
    ingest(w)
    wanted = ingest(w, version="3.6")
    for query in ("Qwen 3.6", "Qwen3.6", "Qwen v3.6", "Qwen3.6发布"):
        result = w.list_updates(1, q=query)
        assert [event["event"]["id"] for event in result["events"]] == [wanted["event_id"]]
        assert all(update["event_id"] == wanted["event_id"] for update in result["updates"])
    assert not w.list_updates(1, q="Qwen 9.9")["events"]
    assert not w.list_updates(1, q="Alibaba 9.9")["updates"]
    assert not w.list_updates(1, q="AI")["events"]


def test_reprints_and_replay_do_not_create_repeated_change_cards(workflow):
    w, _ = workflow
    first = ingest(w)
    original_update = w.list_updates(1)["updates"][0]["id"]
    ingest(w, url="https://example.invalid/syndicated-copy")
    item, extraction = source()
    w.capture_documents(1, [item])
    assert item["_workflow_should_process"] is False
    w.ingest_extraction(1, item, extraction)
    assert len(w.list_updates(1)["updates"]) == 1
    assert w.list_updates(1)["updates"][0]["id"] == original_update
    assert len(w.event_detail(1, first["event_id"])["evidence"]) == 2


@pytest.mark.parametrize("effective", [None, "2026-01-01", "2026-01-01T00:00:00Z"])
def test_unknown_or_invented_effective_time_stays_pending(workflow, effective):
    w, _ = workflow
    item, extraction = source()
    extraction["model_release"]["valid_from"] = effective
    w.capture_documents(1, [item])
    result = w.ingest_extraction(1, item, extraction)
    assert result["review_status"] == "pending"
    assert any("timezone timestamp" in issue for issue in result["issues"])
    assert w.list_updates(1)["events"] == []
    assert w.search_documents(1)[0]["body"]


@pytest.mark.parametrize("text", [
    "Alibaba Qwen 3.5 is not available at 2026-01-01T09:00:00Z.",
    "Alibaba Qwen 3.5 will be available at 2026-01-01T09:00:00Z.",
    "Alibaba Qwen 3.5 is rumoured to be released at 2026-01-01T09:00:00Z.",
])
def test_negated_future_or_rumour_is_not_an_accepted_available_fact(workflow, text):
    w, _ = workflow
    item, extraction = source(status="available")
    item["content"] = text
    extraction["model_release"]["quote"] = text
    w.capture_documents(1, [item])
    result = w.ingest_extraction(1, item, extraction)
    assert result["review_status"] == "pending"
    assert any("uncertainty" in issue for issue in result["issues"])
    assert not w.list_updates(1)["events"]


def test_release_support_cannot_cross_bind_other_version_state_or_time(workflow):
    w, _ = workflow
    item, extraction = source(version="3.6", status="available")
    quote = ("Alibaba released Qwen 3.5 at 2026-01-01T09:00:00Z. "
             "Alibaba announced Qwen 3.6 at 2026-01-02T09:00:00Z.")
    item["content"] = quote
    extraction["model_release"]["quote"] = quote
    w.capture_documents(1, [item])
    result = w.ingest_extraction(1, item, extraction)
    assert result["review_status"] == "pending"
    assert any("same unambiguous" in issue for issue in result["issues"])
    assert not w.list_updates(1)["events"]
    # Correct binding to the second source sentence is supported.
    item2 = {**item, "url": "https://example.invalid/correct-version-binding"}
    correct = copy.deepcopy(extraction)
    correct["model_release"].update(version="v3.6", status="announced", valid_from="2026-01-02T09:00:00Z")
    w.capture_documents(1, [item2])
    assert w.ingest_extraction(1, item2, correct)["review_status"] == "accepted"


def test_version_match_is_exact_not_a_substring(workflow):
    w, _ = workflow
    item, extraction = source(version="13.5")
    extraction["model_release"]["version"] = "3.5"
    w.capture_documents(1, [item])
    assert w.ingest_extraction(1, item, extraction)["review_status"] == "pending"
    assert not w.list_updates(1)["events"]


def test_transition_requires_review_and_preserves_temporal_state(workflow):
    w, clock = workflow
    first = ingest(w)
    before = w.store.state(first["event_id"])["known_at"]
    clock.value = "2026-02-02T10:00:00Z"
    candidate = ingest(w, status="available", effective="2026-01-02T09:00:00Z")
    assert candidate["review_status"] == "pending"
    assert w.store.state(first["event_id"])["fields"]["status"]["value"] == "announced"
    reviewed = w.review_candidate(1, candidate["id"], "accept", "The source explicitly states availability",
                                  expected_version=candidate["expected_version"])
    assert reviewed["review_status"] == "accepted"
    state = w.store.state(first["event_id"])
    assert state["fields"]["status"]["value"] == "available"
    assert state["fields"]["version"]["value"] == "3.5"
    assert w.store.state(first["event_id"], valid_at="2026-01-01T20:00:00Z")["fields"]["status"]["value"] == "announced"
    assert w.store.state(first["event_id"], known_at=before)["fields"]["status"]["value"] == "announced"
    assert w.list_updates(1)["updates"][0]["previous_value"] == "announced"
    assert w.list_updates(1)["updates"][0]["value"] == "available"


def test_late_old_report_cannot_regress_current_availability(workflow):
    w, _ = workflow
    current = ingest(w, status="available", effective="2026-01-02T09:00:00Z")
    older = ingest(w)
    assert older["review_status"] == "pending"
    with pytest.raises(ValueError, match="advance"):
        w.review_candidate(1, older["id"], "accept", "Old report", expected_version=older["expected_version"])
    assert w.store.state(current["event_id"])["fields"]["status"]["value"] == "available"


def test_correction_preserves_known_time_and_does_not_leak_later_passages(workflow):
    w, clock = workflow
    first = ingest(w)
    before = w.store.state(first["event_id"])["known_at"]
    clock.value = "2026-02-02T10:00:00Z"
    candidate = ingest(w, status="available")
    w.review_candidate(1, candidate["id"], "accept", "Correcting the previously reported availability",
                       expected_version=candidate["expected_version"], relation="correction")
    assert w.store.state(first["event_id"])["fields"]["status"]["value"] == "available"
    historical = w.event_detail(1, first["event_id"], known_at=before)
    assert historical["state"]["fields"]["status"]["value"] == "announced"
    known = {a["id"] for a in historical["history"]["assertions"]}
    assert all(p["assertion_id"] in known for e in historical["evidence"] for p in e["passages"])


def test_stale_review_and_wrong_topic_are_rejected(workflow):
    w, _ = workflow
    first = ingest(w)
    pending = ingest(w, status="available", effective="2026-01-02T09:00:00Z")
    ingest(w, url="https://example.invalid/new-support")
    with pytest.raises(ValueError, match="Stale review"):
        w.review_candidate(1, pending["id"], "accept", "Review", expected_version=pending["expected_version"])
    with pytest.raises(KeyError):
        w.review_candidate(2, pending["id"], "defer", "Wrong topic")
    with pytest.raises(KeyError):
        w.event_detail(2, first["event_id"])


def test_failure_keeps_source_and_durable_retry_without_facts(workflow):
    w, _ = workflow
    item, extraction = source()
    w.capture_documents(1, [item])
    failed = w.ingest_extraction(1, item, {"_extraction_failed": True})
    assert failed["review_status"] == "pending"
    assert not w.list_updates(1)["events"]
    assert len(w.pending_documents(1)) == 1
    assert w.ingest_extraction(1, item, extraction)["review_status"] == "accepted"
    assert not w.pending_documents(1)


def test_atomic_failure_rolls_back_all_facts_and_resumes_idempotently(workflow, monkeypatch):
    w, _ = workflow
    item, extraction = source()
    w.capture_documents(1, [item])
    original = w.store.assert_fact
    attempts = 0

    def crash(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 3:
            raise RuntimeError("simulated worker interruption")
        return original(*args, **kwargs)

    monkeypatch.setattr(w.store, "assert_fact", crash)
    with pytest.raises(RuntimeError, match="worker interruption"):
        w.ingest_extraction(1, item, extraction)
    with w.store.connection() as db:
        assert db.execute("SELECT count(*) FROM events").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM assertions").fetchone()[0] == 0
        assert db.execute("SELECT state FROM workflow_jobs").fetchone()[0] == "committing"
    monkeypatch.setattr(w.store, "assert_fact", original)
    assert w.resume_commits(1)[0]["review_status"] == "accepted"
    assert w.resume_commits(1) == []
    assert len(w.list_updates(1)["updates"]) == 1


def test_resume_rechecks_availability_and_keeps_changed_state_for_review(workflow, monkeypatch):
    w, _ = workflow
    item, extraction = source(status="available", effective="2026-01-02T09:00:00Z")
    w.capture_documents(1, [item])
    original = w.store.assert_fact

    def crash(*args, **kwargs):
        raise RuntimeError("simulated interrupted commit")

    monkeypatch.setattr(w.store, "assert_fact", crash)
    with pytest.raises(RuntimeError, match="interrupted commit"):
        w.ingest_extraction(1, item, extraction)
    monkeypatch.setattr(w.store, "assert_fact", original)
    announced = ingest(w, status="announced", effective="2026-01-01T09:00:00Z")
    assert announced["review_status"] == "accepted"
    before = w.store.state(announced["event_id"])["fields"]["status"]

    resumed = w.resume_commits(1)
    assert len(resumed) == 1
    pending = resumed[0]
    assert pending["review_status"] == "pending"
    assert pending["relation"] == "transition"
    assert pending["target_id"] == before["assertion_ids"][0]
    assert pending["event_id"] == announced["event_id"]
    assert pending["expected_version"] == w.event_detail(1, announced["event_id"])["expected_version"]
    assert pending["issues"]
    assert w.store.state(announced["event_id"])["fields"]["status"] == before
    assert len(w.list_candidates(1)) == 1
    assert w.resume_commits(1) == []
    with w.store.connection() as db:
        assert db.execute("SELECT state FROM workflow_jobs WHERE revision_id=?", (pending["revision_id"],)).fetchone()[0] == "processed"


def test_source_and_assertion_known_times_remain_distinct(workflow):
    w, clock = workflow
    item, extraction = source()
    w.capture_documents(1, [item])
    clock.value = "2026-02-02T10:00:00Z"
    result = w.ingest_extraction(1, item, extraction)
    assert w.search_documents(1, known_at="2026-02-01T12:00:00Z")
    assert not w.list_updates(1, known_at="2026-02-01T12:00:00Z")["events"]
    assert w.store.state(result["event_id"])["fields"]


def test_missing_publication_stays_unknown_without_blocking_explicit_effective_time(workflow):
    w, _ = workflow
    item, extraction = source()
    item["published_date"] = ""
    w.capture_documents(1, [item])
    result = w.ingest_extraction(1, item, extraction)
    assert result["review_status"] == "accepted"
    assert w.event_detail(1, result["event_id"])["evidence"][0]["published_at"] == ""


def test_batch_extractor_sees_supported_content_beyond_old_700_character_limit(monkeypatch):
    import pipeline
    item, extraction = source()
    item["content"] = "Background. " * 100 + item["content"]
    observed = []

    def llm(messages):
        observed.append(messages[0]["content"])
        return json.dumps([extraction])

    monkeypatch.setattr(pipeline, "llm_chat", llm)
    context = {k: "test" for k in ("topic_name", "research_brief", "topic_keywords", "entities", "geographic_scope", "sector_scope", "angles")}
    parsed = pipeline._call_batch_llm([item], context)
    assert parsed[0]["model_release"]["quote"] in observed[0]


def test_collector_pipeline_drains_distinct_release_queue_with_existing_budget(tmp_path, monkeypatch):
    import database
    import pipeline
    from config import settings

    monitor = tmp_path / "monitor.db"
    events = tmp_path / "events.sqlite3"
    database.init_db(str(monitor))
    monkeypatch.setattr(settings, "database_path", str(monitor))
    monkeypatch.setattr(settings, "event_memory_database_path", str(events))
    monkeypatch.setattr(settings, "event_memory_enabled", True)
    monkeypatch.setattr(settings, "global_rss_feeds", "")
    monkeypatch.setattr(settings, "max_enrich_per_run", 1)
    monkeypatch.setattr(pipeline, "get_topics", lambda: [{"id": 1, "name": "Model monitoring"}])
    monkeypatch.setattr(pipeline, "get_keywords", lambda _: [{"keyword": "Qwen"}])
    monkeypatch.setattr(pipeline, "get_topic_feeds", lambda _: [])
    one, e1 = source()
    two, e2 = source(version="3.6")
    monkeypatch.setattr(pipeline, "_collect_for_keywords", lambda *args, **kwargs: [copy.deepcopy(one), copy.deepcopy(two)])
    for name in ("add_claim_document", "add_evidence_document", "add_event_document"):
        monkeypatch.setattr(pipeline, name, lambda *args, **kwargs: None)
    requests = []

    def batch(items, context):
        requests.append(len(items))
        return [{**(e1 if "3.5" in item["title"] else e2), "summary": "A model announcement.",
                 "importance": 5, "topic_relevance": 1.0} for item in items]

    monkeypatch.setattr(pipeline, "_call_batch_llm", batch)
    pipeline.run_pipeline_once(1)
    workflow = Workflow(events)
    assert len(workflow.list_updates(1)["events"]) == 1
    assert len(workflow.pending_documents(1)) == 1
    pipeline.run_pipeline_once(1)
    assert len(workflow.list_updates(1)["events"]) == 2
    assert requests == [1, 1]
