"""Isolated RSS -> pipeline -> event memory -> review -> briefing/chat acceptance.

All documents and model responses are synthetic. Real parsers, orchestration,
SQLite, Chroma, Store projections, API handlers and chat retrieval run offline.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import re
import socket
import sqlite3
import sys
import tempfile
import time
from unittest.mock import patch
from xml.sax.saxutils import escape


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
checks = []
network_attempts = []


def check(name, condition):
    if not condition:
        raise AssertionError(name)
    checks.append(name)


def no_network(*args, **kwargs):
    network_attempts.append(True)
    raise AssertionError("Unexpected outbound connection during offline acceptance")


def rss_document(title, body, url):
    return ("<?xml version='1.0'?><rss version='2.0'><channel><title>Synthetic official feed</title>"
            f"<item><title>{escape(title)}</title><link>{escape(url)}</link>"
            "<pubDate>Mon, 05 Jan 2026 11:00:00 GMT</pubDate>"
            f"<description><![CDATA[<p>{body}</p>]]></description></item></channel></rss>").encode()


def run():
    with tempfile.TemporaryDirectory(prefix="domain-monitor-workflow-") as directory:
        os.environ.update(DATABASE_PATH=f"{directory}/monitor.db", CHROMA_PERSIST_DIR=f"{directory}/chroma",
            EVENT_MEMORY_DATABASE_PATH=f"{directory}/eventkb.sqlite3", EVENT_MEMORY_ENABLED="true",
            EXTERNAL_CALLS_ENABLED="false", SCHEDULER_ENABLED="false", ANONYMIZED_TELEMETRY="False",
            DOMAIN_MONITOR_ENV_FILE=f"{directory}/no-secrets.env", OPENAI_API_KEY="", DASHSCOPE_API_KEY="",
            TAVILY_API_KEY="", NEWSAPI_KEY="", EVENT_REGISTRY_API_KEY="", GLOBAL_RSS_FEEDS="")
        from fastapi.testclient import TestClient
        import app
        import main
        import chatbot
        import database
        import event_workflow
        import feedparser
        import llm_client
        import pipeline
        import topic_summary
        import vector_store
        import chromadb
        from collectors import rss_collector
        from config import settings

        clock = {"now": "2026-01-06T12:00:00Z"}
        current = {"workflow": event_workflow.Workflow(settings.event_memory_database_path, clock=lambda: clock["now"])}
        feed = {"xml": b"", "quote": "", "version": "3.5", "status": "announced", "effective": "2026-01-05T10:00:00Z"}
        enrich_prompts, chat_prompts, briefing_prompts = [], [], []

        def fake_enrichment(messages, **kwargs):
            prompt = messages[-1]["content"]
            enrich_prompts.append(prompt)
            if "[Article 1]" not in prompt:
                count = max(1, len(re.findall(r"\[Cluster \d+\]", prompt)))
                return json.dumps([{"event_title": "Synthetic coverage", "event_summary": "Synthetic event coverage."}] * count)
            blocks = re.split(r"\[Article \d+\]", prompt)[1:]
            return json.dumps([{"summary": "Synthetic release evidence captured.", "tags": ["Model release"],
                "sentiment": "neutral", "importance": 8, "topic_relevance": 0.95,
                "signal_type": "release announcement", "key_entities": ["Alibaba", "Qwen"],
                "topic_analysis": "A synthetic release updates the monitored availability.",
                "claims": [{"kind": "observation", "statement": "Synthetic release reported.", "summary": "Synthetic release evidence."}],
                "model_release": {"developer": "Alibaba", "model": "Qwen", "version": feed["version"],
                                  "status": feed["status"], "valid_from": feed["effective"], "quote": feed["quote"]}}
                for block in blocks if feed["quote"] in block])

        def fake_chat(messages, **kwargs):
            chat_prompts.append(messages)
            context = messages[-1]["content"]
            match = re.search(r'^status: "([^"]+)"\s+(\[S\d+\])', context, re.M)
            yield (f"The recorded availability is {match[1]}. {match[2]}" if match
                   else "The requested fact is not known in this scope.")

        def fake_briefing(messages, **kwargs):
            briefing_prompts.append(messages)
            return "## Key Developments\nSynthetic briefing generated from the supplied authoritative evidence."

        class DeterministicEmbedding:
            def __call__(self, input): return [[1.0, 0.0, 0.0] for _ in input]
            def name(self): return "workflow-offline-v1"
            def embed_query(self, input): return self(input)

        with ExitStack() as stack:
            stack.enter_context(patch.object(socket.socket, "connect", no_network))
            stack.enter_context(patch.object(socket.socket, "connect_ex", no_network))
            stack.enter_context(patch.object(socket, "create_connection", no_network))
            stack.enter_context(patch.object(main, "start_scheduler"))
            stack.enter_context(patch.object(event_workflow, "get_workflow", lambda: current["workflow"]))
            stack.enter_context(patch.object(pipeline, "get_workflow", lambda: current["workflow"]))
            stack.enter_context(patch.object(pipeline, "_collect_for_keywords", lambda *args, **kwargs: []))
            stack.enter_context(patch.object(rss_collector, "read_feed", lambda _: feedparser.parse(feed["xml"])))
            stack.enter_context(patch.object(pipeline, "llm_chat", fake_enrichment))
            stack.enter_context(patch.object(chatbot, "llm_chat_stream", fake_chat))
            stack.enter_context(patch.object(llm_client, "configuration_issue", lambda: None))
            stack.enter_context(patch.object(settings, "external_calls_enabled", True))
            chroma = chromadb.PersistentClient(path=settings.chroma_persist_dir)
            vector_store._client = chroma
            embedding = DeterministicEmbedding()
            for name in vector_store.COLLECTIONS.values():
                vector_store._collections[name] = chroma.get_or_create_collection(name, embedding_function=embedding)

            with TestClient(app.app) as client:
                check("unified-runtime-with-event-memory", client.get("/health").status_code == 200 and
                      client.get("/api/runtime").json()["event_memory_enabled"])
                topic = client.post("/api/topics", json={"name": "Synthetic AI workflow"}).json()["id"]
                other = client.post("/api/topics", json={"name": "Synthetic related research"}).json()["id"]
                for tid in (topic, other):
                    client.post("/api/keywords", json={"keyword": "Qwen", "topic_id": tid})
                    client.post(f"/api/topics/{tid}/feeds", json={"feed_url": "https://example.invalid/rss", "label": "Synthetic feed"})

                def collect(title, quote, *, version="3.5", status="announced", effective="2026-01-05T10:00:00Z", url=None, tid=topic, padding=""):
                    feed.update(quote=quote, version=version, status=status, effective=effective,
                                xml=rss_document(title, padding + quote, url or f"https://example.invalid/{version}/{status}"))
                    return pipeline.run_pipeline_once(tid)

                original_quote = "Alibaba announced Qwen 3.5 at 2026-01-05T10:00:00Z."
                initial = collect("Qwen 3.5 announcement", original_quote, padding="Introductory context. " * 60)
                check("real-rss-parser-and-pipeline-store-news", bool(initial) and
                      bool(client.get(f"/api/articles?topic_id={topic}").json()["articles"]))
                check("batch-extraction-can-see-beyond-700-characters", bool(enrich_prompts) and
                      enrich_prompts[-1].find(original_quote) > enrich_prompts[-1].find("Source text:") + 700)
                update_payload = client.get(f"/api/topics/{topic}/memory/updates").json()
                check("pipeline-produces-accepted-update", len(update_payload["events"]) == 1 and
                      update_payload["updates"][0]["kind"] == "new_event")
                event_id = update_payload["events"][0]["event"]["id"]
                detail = client.get(f"/api/topics/{topic}/memory/events/{event_id}").json()
                check("update-and-detail-share-authoritative-state", detail["state"]["fields"]["status"]["value"] == "announced")
                check("source-revision-and-exact-passage-retained", detail["evidence"][0]["passages"][0]["quote"] == original_quote and
                      original_quote in detail["evidence"][0]["body"] and detail["evidence"][0]["revision"].startswith("rev_"))
                first_assertions = len(detail["history"]["assertions"])
                collect("Qwen 3.5 announcement", original_quote, padding="Introductory context. " * 60)
                replay = client.get(f"/api/topics/{topic}/memory/events/{event_id}").json()
                check("repeated-collection-is-idempotent", len(replay["history"]["assertions"]) == first_assertions and
                      len(client.get(f"/api/topics/{topic}/memory/updates").json()["updates"]) == 1)
                collect("Qwen 3.5 announcement", original_quote, tid=other, padding="Introductory context. " * 60)
                check("one-source-can-serve-two-topics", len(client.get(f"/api/topics/{other}/memory/updates").json()["events"]) == 1)
                with current["workflow"].store.connection() as db:
                    check("source-revision-storage-shared-across-topics", db.execute("SELECT COUNT(*) FROM workflow_documents").fetchone()[0] == 1 and
                          db.execute("SELECT COUNT(*) FROM workflow_topic_documents").fetchone()[0] == 2)
                check("event-detail-is-topic-isolated", client.get(f"/api/topics/{other}/memory/events/{event_id}").status_code == 404)

                clock["now"] = "2026-01-07T12:00:00Z"
                collect("Qwen 3.6 announcement", "Alibaba announced Qwen 3.6 at 2026-01-06T10:00:00Z.", version="3.6", effective="2026-01-06T10:00:00Z")
                check("similar-version-headlines-retain-distinct-event-identities", len(client.get(f"/api/topics/{topic}/memory/updates").json()["events"]) == 2)

                clock["now"] = "2026-01-11T12:00:00Z"
                availability = "Alibaba Qwen 3.5 became available at 2026-01-10T10:00:00Z."
                collect("Qwen 3.5 availability", availability, status="available", effective="2026-01-10T10:00:00Z")
                candidates = client.get(f"/api/topics/{topic}/memory/candidates").json()["candidates"]
                candidate = next(row for row in candidates if row.get("status") == "available")
                check("transition-requires-visible-review", detail["state"]["fields"]["status"]["value"] == "announced" and
                      client.get(f"/api/topics/{topic}/memory/events/{event_id}").json()["state"]["fields"]["status"]["value"] == "announced")
                review_url = f"/api/topics/{topic}/memory/candidates/{candidate['id']}/review"
                review = {"action": "accept", "reason": "Synthetic source explicitly states general availability",
                          "expected_version": candidate["expected_version"], "relation": "transition", "target_id": candidate["target_id"]}
                check("cross-origin-review-rejected", client.post(review_url, json=review, headers={"origin": "https://untrusted.invalid"}).status_code == 403)
                check("unknown-review-fields-rejected", client.post(review_url, json={**review, "untrusted": True}).status_code == 422)
                check("stale-review-rejected", client.post(review_url, json={**review, "expected_version": "obsolete"}).status_code == 409)
                check("candidate-review-is-topic-isolated", client.post(review_url.replace(f"/{topic}/memory", f"/{other}/memory"), json=review).status_code == 404)
                accepted = client.post(review_url, json=review)
                check("reviewed-transition-commits", accepted.status_code == 200)
                transitioned = client.get(f"/api/topics/{topic}/memory/events/{event_id}").json()
                check("transition-updates-only-status-semantics", transitioned["state"]["fields"]["status"]["value"] == "available" and
                      transitioned["state"]["fields"]["version"]["value"] == "3.5")
                check("transition-preserves-original-evidence", len(transitioned["evidence"]) == 2 and
                      any(original_quote in row["body"] for row in transitioned["evidence"]))
                check("updates-show-before-and-after", any(row["kind"] == "field_changed" and row["previous_value"] == "announced" and row["value"] == "available"
                      for row in client.get(f"/api/topics/{topic}/memory/updates").json()["updates"]))

                available_assertion = next(row for row in transitioned["history"]["assertions"] if row["field"] == "status" and row["value"] == "available")
                clock["now"] = "2026-01-20T12:00:00Z"
                correction_quote = "Correction: Alibaba Qwen 3.5 was withdrawn at 2026-01-10T10:00:00Z."
                collect("Correction to Qwen 3.5 availability", correction_quote, status="withdrawn", effective="2026-01-10T10:00:00Z")
                correction = next(row for row in client.get(f"/api/topics/{topic}/memory/candidates").json()["candidates"] if row.get("status") == "withdrawn")
                corrected = client.post(f"/api/topics/{topic}/memory/candidates/{correction['id']}/review", json={
                    "action": "accept", "reason": "Synthetic targeted correction preserves the interval",
                    "expected_version": correction["expected_version"], "relation": "correction", "target_id": available_assertion["id"]})
                check("targeted-correction-commits", corrected.status_code == 200)
                current_detail = client.get(f"/api/topics/{topic}/memory/events/{event_id}").json()
                check("correction-does-not-erase-history", current_detail["state"]["fields"]["status"]["value"] == "withdrawn" and
                      len(current_detail["evidence"]) == 3 and len(current_detail["history"]["assertions"]) >= 3)
                historical_params = {"valid_at": "2026-01-12T12:00:00Z", "known_at": "2026-01-12T12:00:00Z"}
                past_detail = client.get(f"/api/topics/{topic}/memory/events/{event_id}", params=historical_params).json()
                check("known-by-projection-excludes-later-correction", past_detail["state"]["fields"]["status"]["value"] == "available" and
                      all(correction_quote not in source["body"] for source in past_detail["evidence"]))

                # Exercise preserved legacy SQLite/API surfaces and the real
                # summary writer, using a synthetic model completion only.
                database.upsert_event(topic, "legacy-capacity", "legacy-capacity", "Capacity financing research", summary="Unmigrated infrastructure coverage")
                check("legacy-events-api-remains-available", client.get(f"/api/topics/{topic}/events/active").status_code == 200)
                with patch.object(llm_client, "llm_chat", fake_briefing):
                    summary = topic_summary.generate_summary_sync(topic)
                check("real-briefing-path-persists-snapshot", bool(summary) and bool(database.get_latest_temporal_snapshot(topic)))
                check("briefing-uses-authoritative-event-evidence", bool(briefing_prompts) and
                      "eventkb" in briefing_prompts[-1][-1]["content"] and "withdrawn" in briefing_prompts[-1][-1]["content"])
                check("legacy-briefing-api-remains-available", client.get(f"/api/topics/{topic}/ai-summary").status_code == 200)

                def stream_chat(scope=None):
                    request = {"message": "What is the Qwen 3.5 availability?", "topic_id": topic, "event_id": event_id,
                               "article_context": "UNSUPPORTED_FUTURE_FREE_TEXT", "history": [{"role": "assistant", "content": "UNSUPPORTED_FUTURE_HISTORY"}]}
                    request.update(scope or {})
                    response = client.post("/api/chat", json=request)
                    packets = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
                    return response, packets

                response, packets = stream_chat()
                current_sources = next(packet["sources"] for packet in packets if packet.get("sources"))
                check("current-chat-stream-uses-authoritative-status", response.status_code == 200 and any("withdrawn" in packet.get("content", "") for packet in packets))
                check("chat-citations-open-exact-original-passages", all(source.get("quote") and source.get("revision") and source.get("assertion_ids") for source in current_sources))
                check("selected-event-ignores-free-text-and-assistant-history", "UNSUPPORTED_FUTURE" not in json.dumps(chat_prompts[-1]))
                _, past_packets = stream_chat(historical_params)
                past_sources = next(packet["sources"] for packet in past_packets if packet.get("sources"))
                check("historical-chat-uses-then-known-status", any("available" in packet.get("content", "") for packet in past_packets) and
                      all(correction_quote not in source["quote"] for source in past_sources))
                check("historical-chat-prompt-excludes-future-source", correction_quote not in chat_prompts[-1][-1]["content"])
                check("chat-rejects-foreign-event-scope", client.post("/api/chat", json={"message": "Availability?", "topic_id": other, "event_id": event_id}).status_code == 404)
                check("chat-rejects-invalid-temporal-scope", client.post("/api/chat", json={"message": "Availability?", "topic_id": topic, "valid_at": "2026-02-30"}).status_code == 400)
                task = client.post("/api/chat/tasks", json={"message": "Qwen 3.5 availability", "topic_id": topic, "event_id": event_id}).json()
                deadline = time.monotonic() + 5
                task_state = client.get(f"/api/chat/tasks/{task['task_id']}/status").json()
                while task_state["status"] == "running" and time.monotonic() < deadline:
                    time.sleep(.02)
                    task_state = client.get(f"/api/chat/tasks/{task['task_id']}/status").json()
                conversation = client.get(f"/api/chat/conversations/{task['conversation_id']}").json()
                check("scoped-background-chat-completes-and-persists", task_state["status"] == "done" and
                      "withdrawn" in conversation["messages"][-1]["content"] and bool(conversation["messages"][-1]["sources"]))
                before_restart = client.get(f"/api/topics/{topic}/memory/events/{event_id}").json()

            current["workflow"] = event_workflow.Workflow(settings.event_memory_database_path, clock=lambda: clock["now"])
            with TestClient(app.app) as reopened:
                after_restart = reopened.get(f"/api/topics/{topic}/memory/events/{event_id}").json()
                check("restart-retains-identical-projection-and-provenance", after_restart == before_restart)
                check("restart-retains-chat-and-briefing", bool(reopened.get(f"/api/chat/conversations/{task['conversation_id']}").json()["messages"]) and
                      bool(reopened.get(f"/api/topics/{topic}/ai-summary").json().get("content")))
            for name in ("monitor.db", "eventkb.sqlite3"):
                with sqlite3.connect(Path(directory) / name) as db:
                    check(f"integrity-{name}", db.execute("PRAGMA integrity_check").fetchone()[0] == "ok")
            check("no-external-network-attempts", not network_attempts)
            vector_store._collections.clear()
            vector_store._client = None
        return {"status": "ok", "count": len(checks), "checks": checks, "external_network_attempts": len(network_attempts),
                "source_data": "Synthetic RSS fixtures only", "model_responses": "Synthetic bounded responses only",
                "stores": "Real temporary SQLite, eventkb and Chroma", "production_data_touched": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    captured = io.StringIO()
    try:
        with redirect_stdout(captured), redirect_stderr(captured):
            report = run()
    except Exception as error:
        report = {"status": "failed", "count": len(checks), "checks": checks,
                  "error": f"{type(error).__name__}: {error}", "external_network_attempts": len(network_attempts),
                  "source_data": "Synthetic RSS fixtures only", "production_data_touched": False}
    output = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output)
    print(output, end="")
    raise SystemExit(0 if report["status"] == "ok" else 1)
