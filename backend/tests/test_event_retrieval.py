"""Offline acceptance checks for scoped facts, original support and chat authority."""
from copy import deepcopy

import pytest

import chatbot
from event_retrieval import relevance_score, retrieve_event_memory
from eventkb.store import Store


class WorkflowFixture:
    def __init__(self, path):
        self.now = "2026-01-05T12:00:00Z"
        self.store = Store(path, clock=lambda: self.now)

    def event_detail(self, topic_id, event_id, **scope):
        state = self.store.state(event_id, **scope)
        if state["event"]["topic"] != f"topic:{topic_id}":
            raise KeyError(event_id)
        history = self.store.history(event_id, known_at=scope.get("known_at"))
        evidence = deepcopy(history["evidence"])
        for source in evidence:
            source["passages"] = []
            for assertion in history["assertions"]:
                if assertion["evidence_id"] != source["id"]:
                    continue
                pos = source["body"].casefold().find(str(assertion["value"]).casefold())
                if pos >= 0:
                    start, end = max(0, pos - 100), min(len(source["body"]), pos + 200)
                    source["passages"].append({"assertion_id": assertion["id"], "field": assertion["field"],
                                               "start": start, "end": end, "quote": source["body"][start:end]})
        return {"state": state, "history": history, "evidence": evidence}

    def release(self, version="3.5", *, developer="Alibaba", model="Qwen", topic=1, body=None):
        eid = f"release-{topic}-{model.casefold()}-{version.replace('.', '-')}"
        self.store.create_event(event_id=eid, topic=f"topic:{topic}", identity_key=f"{developer}/{model}/{version}",
                                title=f"{developer} {model} {version} release", kind="ModelRelease")
        body = body or f"Alibaba announced {model} {version} on January 5. The availability is announced."
        source = self.store.add_evidence(source_key=f"{eid}-source", revision="1", publisher="Release source",
                                         url=f"https://example.invalid/{eid}", published_at="2026-01-05T10:00:00Z", body=body)
        for field, value in (("developer", developer), ("model", model), ("version", version), ("availability", "announced")):
            self.store.assert_fact(eid, field=field, value=value, valid_from="2026-01-05T10:00:00Z",
                                   evidence_id=source["id"], message_key=f"{field}-initial")
        return eid

    def available(self, eid):
        previous = next(row for row in self.store.history(eid)["assertions"] if row["field"] == "availability")
        source = self.store.add_evidence(source_key=f"{eid}-available", revision="1", publisher="Availability source",
                                         url=f"https://example.invalid/{eid}/available", published_at="2026-01-10T10:00:00Z",
                                         body="Qwen is available from January 10 at 10:00 UTC.")
        return self.store.assert_fact(eid, field="availability", value="available", valid_from="2026-01-10T10:00:00Z",
                                      evidence_id=source["id"], message_key="availability-transition", relation="transition",
                                      target_id=previous["id"], reviewed=True, reason="Explicit availability announcement")


@pytest.fixture
def workflow(tmp_path):
    return WorkflowFixture(tmp_path / "eventkb.sqlite3")


def test_specific_version_retrieval_is_unchanged_by_unrelated_events(workflow):
    target = workflow.release()
    before = retrieve_event_memory(1, "What is the Qwen 3.5 availability?", workflow=workflow)
    workflow.release("3.6")
    for number in range(20):
        workflow.release(f"{number + 5}.0", developer="Other", model="OtherModel")
    after = retrieve_event_memory(1, "What is the Qwen 3.5 availability?", workflow=workflow)
    assert [row["event"]["id"] for row in before["events"]] == [target]
    assert after["events"] == before["events"]
    assert after["sources"] == before["sources"]
    assert "3.6" not in after["text"]


def test_joined_name_and_version_supports_exact_identifier_matching():
    assert relevance_score("Alibaba Qwen3.5 release", "Qwen 3.5 status") > 0
    assert relevance_score("Alibaba Qwen3.6 release", "Qwen 3.5 status") == 0
    assert relevance_score("OtherModel 3.5 release", "Qwen 3.5 status") == 0
    assert relevance_score("New chair elected", "AI chips") == 0


def test_cjk_user_input_retains_latin_entity_and_exact_version_scope(workflow):
    target = workflow.release()
    workflow.release("3.6")
    assert relevance_score("Alibaba Qwen 3.5 release", "Qwen现在可用吗") > 0
    result = retrieve_event_memory(1, "Qwen 3.5什么时候发布", workflow=workflow)
    assert [row["event"]["id"] for row in result["events"]] == [target]
    assert result["exclusive"]
    assert "3.6" not in result["text"]


def test_developer_match_does_not_take_over_other_company_research(workflow):
    workflow.release()
    result = retrieve_event_memory(1, "Tell me about Alibaba", workflow=workflow)
    assert result["events"] and not result["exclusive"]
    assert retrieve_event_memory(1, "Tell me about Qwen", workflow=workflow)["exclusive"]


def test_generic_announcement_keeps_acquisition_context_in_chat(workflow, monkeypatch):
    workflow.release()
    question = "What acquisition was announced by Alibaba?"
    assert not retrieve_event_memory(1, question, workflow=workflow)["exclusive"]
    assert retrieve_event_memory(1, "Is Qwen available?", workflow=workflow)["exclusive"]
    assert retrieve_event_memory(1, "What models were released?", workflow=workflow)["exclusive"]
    assert retrieve_event_memory(1, "Is Moonstone 3.5 available?", workflow=workflow)["exclusive"]
    monkeypatch.setattr(chatbot, "retrieve_event_memory", lambda topic_id, message, **scope:
                        retrieve_event_memory(topic_id, message, workflow=workflow, **scope))
    monkeypatch.setattr(chatbot, "_get_topic_name", lambda _: "Alibaba coverage")
    calls = []
    acquisition = {"id": "acquisition", "title": "Alibaba acquisition announced",
                   "summary": "Alibaba acquired Example Commerce.", "status": "active"}
    def current(topic_id, message):
        calls.append((topic_id, message))
        return {"active_events": [acquisition], "fresh_claims": [], "stale_claims": []}
    monkeypatch.setattr(chatbot, "retrieve_current_state", current)
    monkeypatch.setattr(chatbot, "retrieve_timeline_context", lambda *args: {})
    monkeypatch.setattr(chatbot, "retrieve_archive_context", lambda *args: {})
    monkeypatch.setattr(chatbot, "_run_vector_supplement", lambda *args: {})
    seen = []
    def answer(messages, **kwargs):
        seen.extend(messages)
        yield "Alibaba acquired Example Commerce."
    monkeypatch.setattr(chatbot, "llm_chat_stream", answer)
    list(chatbot.chat_stream_with_status(question, topic_id=1))
    assert calls == [(1, question)]
    assert "Alibaba acquired Example Commerce" in seen[-1]["content"]


def test_current_and_known_by_answers_use_different_assertion_versions(workflow):
    eid = workflow.release()
    workflow.now = "2026-01-15T12:00:00Z"
    workflow.available(eid)
    current = retrieve_event_memory(1, "Qwen 3.5 availability", workflow=workflow)
    historical = retrieve_event_memory(1, "Qwen 3.5 availability", workflow=workflow,
                                       valid_at="2026-01-12T12:00:00Z", known_at="2026-01-08T12:00:00Z")
    assert current["events"][0]["fields"]["availability"]["value"] == "available"
    assert historical["events"][0]["fields"]["availability"]["value"] == "announced"
    assert all(source["publisher"] != "Availability source" for source in historical["sources"])
    assert historical["exclusive"] and historical["temporal"]


def test_conflicting_values_are_explicit_and_both_original_passages_are_returned(workflow):
    eid = workflow.release()
    source = workflow.store.add_evidence(source_key="contradiction", revision="1", publisher="Conflicting source",
                                          url="https://example.invalid/conflict", published_at="2026-01-05T10:00:00Z",
                                          body="The availability is withdrawn.")
    workflow.store.assert_fact(eid, field="availability", value="withdrawn", evidence_id=source["id"],
                               valid_from="2026-01-05T10:00:00Z", message_key="opposing-observation")
    result = retrieve_event_memory(1, "Qwen 3.5 availability", workflow=workflow)
    assert result["events"][0]["fields"]["availability"]["value"] is None
    assert "UNRESOLVED CONFLICT" in result["text"]
    assert {"Release source", "Conflicting source"} <= {row["publisher"] for row in result["sources"]}


def test_unknown_event_does_not_borrow_another_models_version(workflow):
    workflow.release()
    result = retrieve_event_memory(1, "Is Moonstone 3.5 available?", workflow=workflow)
    assert result["events"] == [] and result["sources"] == []
    assert result["exclusive"]
    assert "unknown" in result["text"]


def test_selected_event_is_topic_isolated(workflow):
    foreign = workflow.release(topic=2)
    result = retrieve_event_memory(1, "Availability?", event_id=foreign, workflow=workflow)
    assert result["exclusive"] and result["events"] == [] and result["sources"] == []
    assert "Release source" not in result["text"]


def test_support_after_700_characters_is_localized_without_first_prefix_shortcut(workflow):
    body = "Irrelevant introductory material. " * 60 + "Alibaba announced Qwen 3.5. Its availability is announced."
    workflow.release(body=body)
    result = retrieve_event_memory(1, "Qwen 3.5 availability", workflow=workflow)
    assert any(source["quote_start"] > 700 for source in result["sources"])
    for source in result["sources"]:
        assert source["quote"] == body[source["quote_start"]:source["quote_end"]]
        assert source["revision"] == "1" and source["assertion_ids"]


def test_candidate_text_is_reread_from_authoritative_store(workflow, monkeypatch):
    eid = workflow.release()
    stale = workflow.store.search("", topic="topic:1")
    workflow.now = "2026-01-15T12:00:00Z"
    workflow.available(eid)
    monkeypatch.setattr(workflow.store, "search", lambda *args, **kwargs: stale)
    result = retrieve_event_memory(1, "Qwen 3.5 availability", workflow=workflow)
    assert result["events"][0]["fields"]["availability"]["value"] == "available"
    assert "Availability source" in result["text"]


def test_date_only_historical_question_requires_explicit_scope(workflow):
    workflow.release()
    result = retrieve_event_memory(1, "What did we know on 2026-01-08 about Qwen?", workflow=workflow)
    assert result["exclusive"] and result["temporal"] and not result["sources"]
    assert "timezone-aware cutoff" in result["text"]


def test_five_unrelated_records_do_not_disable_semantic_retrieval():
    assert chatbot._needs_vector_supplement({"active_events": [{"title": "Unrelated"}] * 5}, {}, 5)


def test_specific_legacy_question_is_filtered_before_context_composition(monkeypatch):
    noise = [{"id": f"n{number}", "title": "NVIDIA supply update", "summary": "Chip supply"} for number in range(20)]
    target = {"id": "old-qwen", "title": "Qwen 3.5 announcement", "summary": "The announcement"}
    monkeypatch.setattr(chatbot, "get_events_since", lambda *args, **kwargs: noise)
    monkeypatch.setattr(chatbot, "get_events_v2", lambda *args, **kwargs: [target, *noise])
    monkeypatch.setattr(chatbot, "get_fresh_claims", lambda *args, **kwargs: [])
    monkeypatch.setattr(chatbot, "get_claims_v2", lambda *args, **kwargs: [])
    result = chatbot.retrieve_current_state(1, "Qwen 3.5 status")
    assert result["active_events"] == [target]
    assert result["snapshot"] is None and result["artifact"] is None


def test_selected_event_chat_excludes_legacy_history_free_text_and_web(workflow, monkeypatch):
    eid = workflow.release()
    seen_messages = []
    monkeypatch.setattr(chatbot, "retrieve_event_memory", lambda topic_id, message, **scope:
                        retrieve_event_memory(topic_id, message, workflow=workflow, **scope))
    monkeypatch.setattr(chatbot, "_get_topic_name", lambda _: "AI monitoring")
    def forbidden(*args, **kwargs):
        pytest.fail("A scoped event answer cannot read current legacy data or live web")
    for name in ("retrieve_current_state", "retrieve_timeline_context", "retrieve_archive_context", "web_search", "_run_vector_supplement"):
        monkeypatch.setattr(chatbot, name, forbidden)
    def fake_answer(messages, **kwargs):
        seen_messages.extend(messages)
        yield "Qwen 3.5 was announced. [S1]"
    monkeypatch.setattr(chatbot, "llm_chat_stream", fake_answer)
    chunks = list(chatbot.chat_stream_with_status("What is its availability?", topic_id=1, event_id=eid,
                  article_context="Future unsupported price is 999", history=[{"role": "assistant", "content": "Future unsupported state"}]))
    assert any(isinstance(chunk, dict) and chunk.get("sources") for chunk in chunks)
    prompt = "\n".join(message["content"] for message in seen_messages)
    assert "Future unsupported" not in prompt
    assert "announced" in prompt and "Original quotation" in prompt
    assert "[S1]" in prompt


def test_followup_rereads_user_identified_event_without_reusing_prior_assistant_facts(workflow, monkeypatch):
    eid = workflow.release()
    workflow.now = "2026-01-15T12:00:00Z"
    workflow.available(eid)
    monkeypatch.setattr(chatbot, "retrieve_event_memory", lambda topic_id, message, **scope:
                        retrieve_event_memory(topic_id, message, workflow=workflow, **scope))
    monkeypatch.setattr(chatbot, "_get_topic_name", lambda _: "AI monitoring")
    def forbidden(*args, **kwargs):
        pytest.fail("An inherited event follow-up must use freshly projected event memory")
    for name in ("retrieve_current_state", "retrieve_timeline_context", "retrieve_archive_context", "web_search", "_run_vector_supplement"):
        monkeypatch.setattr(chatbot, name, forbidden)
    seen = []
    def answer(messages, **kwargs):
        seen.extend(messages)
        yield "The model is now available. [S1]"
    monkeypatch.setattr(chatbot, "llm_chat_stream", answer)
    chunks = list(chatbot.chat_stream_with_status("Why is that important?", topic_id=1,
                  history=[{"role": "user", "content": "What is Qwen 3.5 availability?"},
                           {"role": "assistant", "content": "Stale assistant claim: Qwen is only announced and costs 999."}]))
    assert "Stale assistant claim" not in str(seen)
    assert 'availability: "available"' in seen[-1]["content"]
    sources = next(chunk["sources"] for chunk in chunks if isinstance(chunk, dict) and "sources" in chunk)
    assert any(source["publisher"] == "Availability source" for source in sources)


def test_ambiguous_event_followup_asks_for_model_version(workflow, monkeypatch):
    workflow.release()
    workflow.release("3.6")
    monkeypatch.setattr(chatbot, "retrieve_event_memory", lambda topic_id, message, **scope:
                        retrieve_event_memory(topic_id, message, workflow=workflow, **scope))
    memory = retrieve_event_memory(1, "Why is that important?", workflow=workflow)
    result = chatbot._inherit_event_referent(1, "Why is that important?", [
        {"role": "user", "content": "What is Qwen availability?"},
        {"role": "assistant", "content": "Invented referent Qwen 3.5"}], memory)
    assert result["exclusive"] and not result["sources"] and not result["events"]
    assert "Ask which model and version" in result["text"]


def test_followup_preserves_explicit_known_by_scope_from_user_question(workflow, monkeypatch):
    eid = workflow.release()
    workflow.now = "2026-01-15T12:00:00Z"
    workflow.available(eid)
    monkeypatch.setattr(chatbot, "retrieve_event_memory", lambda topic_id, message, **scope:
                        retrieve_event_memory(topic_id, message, workflow=workflow, **scope))
    memory = retrieve_event_memory(1, "Why is that important?", workflow=workflow)
    result = chatbot._inherit_event_referent(1, "Why is that important?", [
        {"role": "user", "content": "What did we know about Qwen 3.5 as of 2026-01-08T12:00:00Z?"}], memory)
    assert result["exclusive"] and result["temporal"]
    assert result["scope"]["event_id"] == eid
    assert result["events"][0]["fields"]["availability"]["value"] == "announced"
    assert all(source["publisher"] != "Availability source" for source in result["sources"])
    assert not chatbot._is_referential_followup("What acquisition did Alibaba announce this week?")


def test_historical_chat_never_uses_future_summaries_or_live_search(workflow, monkeypatch):
    workflow.release()
    monkeypatch.setattr(chatbot, "retrieve_event_memory", lambda topic_id, message, **scope:
                        retrieve_event_memory(topic_id, message, workflow=workflow, **scope))
    monkeypatch.setattr(chatbot, "_get_topic_name", lambda _: "AI monitoring")
    monkeypatch.setattr(chatbot, "web_search", lambda *args, **kwargs: pytest.fail("No future web evidence"))
    monkeypatch.setattr(chatbot, "retrieve_current_state", lambda *args, **kwargs: pytest.fail("No current summaries"))
    seen = []
    def answer(messages, **kwargs):
        seen.extend(messages)
        yield "The release was not yet known in this scope."
    monkeypatch.setattr(chatbot, "llm_chat_stream", answer)
    list(chatbot.chat_stream_with_status("Qwen 3.5 availability", topic_id=1,
          valid_at="2026-01-01T00:00:00Z", known_at="2026-01-01T00:00:00Z"))
    assert "No accepted ModelRelease fields" in seen[-1]["content"]


def test_real_ingestion_workflow_projects_and_cites_the_same_original_revision(tmp_path):
    from event_workflow import Workflow
    workflow = Workflow(tmp_path / "workflow.sqlite3", clock=lambda: "2026-01-06T12:00:00Z")
    quote = "Alibaba announced Qwen 3.5 at 2026-01-05T10:00:00Z."
    item = {"title": "Qwen 3.5 announcement", "content": quote, "url": "https://example.invalid/official-release",
            "source": "Official release", "published_date": "2026-01-05T11:00:00Z"}
    workflow.capture_documents(1, [item])
    result = workflow.ingest_extraction(1, item, {"model_release": {
        "developer": "Alibaba", "model": "Qwen", "version": "3.5", "status": "announced",
        "valid_from": "2026-01-05T10:00:00Z", "quote": quote}})
    assert result["review_status"] == "accepted"
    memory = retrieve_event_memory(1, "Qwen 3.5 availability", workflow=workflow)
    update = workflow.list_updates(1)["updates"][0]
    assert memory["events"][0]["event"]["id"] == update["event_id"]
    assert memory["events"][0]["fields"]["status"]["value"] == update["value"] == "announced"
    assert memory["sources"][0]["quote"] == quote
    assert memory["sources"][0]["revision"] == item["_workflow_revision_id"]
    assert len(memory["sources"][0]["assertion_ids"]) >= 1


def test_broad_source_questions_find_unprocessed_passages_without_upgrading_them_to_facts(tmp_path):
    from event_workflow import Workflow
    workflow = Workflow(tmp_path / "sources.sqlite3", clock=lambda: "2026-01-06T12:00:00Z")
    body = "Infrastructure capacity is financed through long-term bank loans."
    workflow.capture_documents(1, [{"title": "Financing infrastructure", "content": body,
        "url": "https://example.invalid/financing", "source": "Infrastructure report"}])
    result = retrieve_event_memory(1, "How is infrastructure capacity financed?", workflow=workflow)
    assert not result["exclusive"] and result["events"] == []
    assert "UNSTRUCTURED SOURCE MATERIAL" in result["text"]
    assert body in result["sources"][0]["quote"]
    assert result["sources"][0]["assertion_ids"] == []
    assert retrieve_event_memory(2, "How is infrastructure capacity financed?", workflow=workflow)["sources"] == []
    historical = retrieve_event_memory(1, "How is infrastructure capacity financed?", workflow=workflow,
                                       known_at="2026-01-07T00:00:00Z")
    assert historical["sources"] == []


SOURCE_REPORT_QUESTION = (
    "What do the retained sources report about Qwen model releases? "
    "Distinguish accepted event-memory facts from unstructured source reports. "
    "Do not search the web. Answer in three short English sentences with citations."
)


@pytest.fixture
def retained_release_reports(tmp_path):
    from event_workflow import Workflow
    workflow = Workflow(tmp_path / "release-reports.sqlite3", clock=lambda: "2026-01-06T12:00:00Z")
    report = {"title": "Alibaba Qwen4-Max model release report",
              "content": "A retained news source reports that Alibaba announced Qwen4-Max. The report gives no precise effective timestamp.",
              "url": "https://example.invalid/qwen4-max-report", "source": "Public model news"}
    workflow.capture_documents(1, [report])
    # Generic reporting/instruction words must not push the named model out of
    # the bounded document candidate window.
    for number in range(12):
        workflow.capture_documents(1, [{"title": f"Unrelated news report {number}",
            "content": "Retained sources report English facts about unrelated infrastructure projects.",
            "url": f"https://example.invalid/unrelated-{number}", "source": "Other reports"}])
    return workflow, report


def test_release_source_reporting_retrieves_qwen4_max_without_accepted_facts(retained_release_reports):
    workflow, report = retained_release_reports
    assert workflow.search_documents(1, "Qwen")[0]["original_url"] == report["url"]
    assert relevance_score(report["content"], "Qwen") > 0
    assert relevance_score("Alibaba Qwen5-Max announcement", "Qwen4-Max") == 0
    result = retrieve_event_memory(1, SOURCE_REPORT_QUESTION, workflow=workflow)
    assert result["exclusive"] and result["events"] == []
    assert len(result["sources"]) == 1
    source = result["sources"][0]
    assert source["support_status"] == "unstructured_source" and source["assertion_ids"] == []
    assert source["url"] == report["url"] and "Qwen4-Max" in source["quote"]
    document = workflow.search_documents(1, "Qwen")[0]
    assert document["body"][source["quote_start"]:source["quote_end"]] == source["quote"]
    assert "UNSTRUCTURED SOURCE MATERIAL" in result["text"]
    assert "Accepted field values are unknown" in result["text"]
    assert "Missing accepted facts does not mean retained reports are missing" in result["text"]
    assert not retrieve_event_memory(2, SOURCE_REPORT_QUESTION, workflow=workflow)["sources"]


@pytest.mark.parametrize("question", [
    "What is the current availability of Qwen model releases? Cite the retained sources.",
    "Is Qwen4-Max available? Cite the retained sources.",
    "What is the Qwen4-Max release date according to the sources?",
])
def test_strict_release_fields_do_not_borrow_unaccepted_reports(retained_release_reports, question):
    workflow, _ = retained_release_reports
    result = retrieve_event_memory(1, question, workflow=workflow)
    assert result["exclusive"] and result["events"] == [] and result["sources"] == []
    assert "Accepted field values are unknown" in result["text"]
    assert "UNSTRUCTURED SOURCE MATERIAL" not in result["text"]


@pytest.mark.parametrize("scope", [
    {"known_at": "2026-01-07T00:00:00Z"},
    {"valid_at": "2026-01-07T00:00:00Z"},
    {"event_id": "absent-release"},
])
def test_historical_and_selected_event_reporting_stay_projection_only(retained_release_reports, scope):
    workflow, _ = retained_release_reports
    result = retrieve_event_memory(1, SOURCE_REPORT_QUESTION, workflow=workflow, **scope)
    assert result["exclusive"] and result["events"] == [] and result["sources"] == []
    assert "UNSTRUCTURED SOURCE MATERIAL" not in result["text"]


def test_release_report_chat_keeps_web_and_legacy_disabled(retained_release_reports, monkeypatch):
    workflow, _ = retained_release_reports
    monkeypatch.setattr(chatbot, "retrieve_event_memory", lambda topic_id, message, **scope:
                        retrieve_event_memory(topic_id, message, workflow=workflow, **scope))
    monkeypatch.setattr(chatbot, "_get_topic_name", lambda _: "AI monitoring")
    def forbidden(*args, **kwargs):
        pytest.fail("Release source reporting cannot fill accepted facts from legacy or web")
    for name in ("retrieve_current_state", "retrieve_timeline_context", "retrieve_archive_context", "web_search", "_run_vector_supplement"):
        monkeypatch.setattr(chatbot, name, forbidden)
    seen = []
    def answer(messages, **kwargs):
        seen.extend(messages)
        yield "There are no accepted release fields. A retained source reports a Qwen4-Max announcement. [S1]"
    monkeypatch.setattr(chatbot, "llm_chat_stream", answer)
    chunks = list(chatbot.chat_stream_with_status(SOURCE_REPORT_QUESTION, topic_id=1))
    assert "Qwen4-Max" in seen[-1]["content"] and "UNSTRUCTURED SOURCE MATERIAL" in seen[-1]["content"]
    sources = next(chunk["sources"] for chunk in chunks if isinstance(chunk, dict) and "sources" in chunk)
    assert len(sources) == 1 and sources[0]["support_status"] == "unstructured_source"
