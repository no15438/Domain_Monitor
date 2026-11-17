"""Exercise the real unified app and persistent stores; external responses are synthetic."""
import json
import os
from pathlib import Path
import socket
import sqlite3
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
checks = []


def check(name, condition):
    if not condition:
        raise AssertionError(name)
    checks.append(name)


with tempfile.TemporaryDirectory(prefix="domain-monitor-system-") as directory:
    os.environ.update(DATABASE_PATH=f"{directory}/monitor.db", CHROMA_PERSIST_DIR=f"{directory}/chroma",
        EVENT_MEMORY_DATABASE_PATH=f"{directory}/eventkb.sqlite3", EXTERNAL_CALLS_ENABLED="false",
        SCHEDULER_ENABLED="false", DOMAIN_MONITOR_ENV_FILE=f"{directory}/no-secrets.env",
        ANONYMIZED_TELEMETRY="False")
    from fastapi.testclient import TestClient
    import app
    import main
    import database
    import vector_store
    from config import settings

    def no_network(*args, **kwargs):
        raise AssertionError("Unexpected network access in offline validation")

    # Block outbound sockets. TestClient uses in-process ASGI, Chroma uses local Rust storage.
    with patch.object(socket.socket, "connect", no_network), patch.object(main, "start_scheduler") as schedule:
        with TestClient(app.app) as client:
            check("unified-health-and-runtime", client.get("/health").status_code == 200 and
                  client.get("/api/runtime").json()["event_memory_enabled"])
            check("scheduler-does-not-start-in-local-mode", not schedule.called)
            topic = client.post("/api/topics", json={"name": "Synthetic system test"}).json()["id"]
            check("topic-create-and-duplicate", client.post("/api/topics", json={"name": "Synthetic system test"}).status_code == 409)
            check("topic-update", client.put(f"/api/topics/{topic}", json={"research_brief": "Synthetic scope"}).status_code == 200)
            client.post("/api/keywords", json={"keyword": "synthetic", "topic_id": topic})
            client.post(f"/api/topics/{topic}/feeds", json={"feed_url": "https://example.invalid/feed", "label": "Synthetic"})
            check("topic-keywords-and-feeds", len(client.get(f"/api/keywords?topic_id={topic}").json()["keywords"]) == 1
                  and len(client.get(f"/api/topics/{topic}/feeds").json()["feeds"]) == 1)
            with sqlite3.connect(settings.database_path) as db:
                db.execute("INSERT INTO articles(id,title,summary,source,url,topic_id) VALUES('a','Synthetic original','Summary','Synthetic','https://example.invalid/a',?)", (topic,))
            client.put("/api/articles/a", json={"title": "Synthetic edited", "tags": ["test"]})
            client.put("/api/articles/a/keep", json={"is_kept": True})
            check("article-edit-and-keep", client.get(f"/api/topics/{topic}/kept-articles").json()[0]["title"] == "Synthetic edited")
            check("article-archive-and-restore", client.put("/api/articles/a/archive").status_code == 200 and client.put("/api/articles/a/restore").status_code == 200)
            client.post(f"/api/topics/{topic}/archive")
            check("topic-archive", any(t["id"] == topic for t in client.get("/api/topics/archived/overview").json()["topics"]))
            client.post(f"/api/topics/{topic}/unarchive")
            for path in ("claims", "evidence", "snapshot-deltas", "claim-lifecycle-audit", "snapshots",
                         "events/active", "events/history", "ai-summary", "synthesis/global-overview", "synthesis/evolution-report"):
                check(f"workspace-{path}", client.get(f"/api/topics/{topic}/{path}").status_code == 200)
            for path in ("/api/chat", "/api/chat/tasks", "/api/fetch-now", "/api/admin/regen-event-titles",
                         f"/api/topics/{topic}/generate-research-plan", f"/api/topics/{topic}/ai-summary/generate",
                         f"/api/topics/{topic}/global-overview/generate", f"/api/topics/{topic}/synthesis/global-overview/generate",
                         f"/api/topics/{topic}/synthesis/evolution-report/generate"):
                check(f"local-mode-blocks-{path}", client.post(path, json={"message": "Synthetic", "prompt": "Synthetic"}).status_code == 503)
            with sqlite3.connect(settings.database_path) as db:
                check("blocked-actions-create-no-tasks", db.execute("SELECT count(*) FROM chat_tasks").fetchone()[0] == 0 and db.execute("SELECT count(*) FROM task_state").fetchone()[0] == 0)
            with patch.object(settings, "external_calls_enabled", True), patch.object(settings, "llm_provider", "openai"), patch.object(settings, "openai_api_key", None):
                check("unconfigured-model-fails-before-task-creation", client.post("/api/chat/tasks", json={"message": "Synthetic"}).status_code == 503)

            # Real conversation/task persistence and SSE framing, with only the response generator replaced.
            def response(*args, **kwargs):
                yield {"status": "Reading synthetic records"}
                yield "Synthetic answer"
            with patch.object(settings, "external_calls_enabled", True), patch("llm_client.configuration_issue", return_value=None), patch.object(main, "chat_stream_with_status", response):
                stream = client.post("/api/chat", json={"message": "Synthetic", "topic_id": topic})
                check("chat-sse-framing", '"content": "Synthetic answer"' in stream.text and '"done": true' in stream.text)
                task = client.post("/api/chat/tasks", json={"message": "Synthetic", "topic_id": topic}).json()
                deadline = time.monotonic() + 5
                while client.get(f"/api/chat/tasks/{task['task_id']}/status").json()["status"] == "running" and time.monotonic() < deadline:
                    time.sleep(.02)
                payload = client.get(f"/api/chat/conversations/{task['conversation_id']}").json()
                check("chat-task-completes-and-persists", payload["task"]["status"] == "done" and payload["messages"][-1]["content"] == "Synthetic answer")
                other = client.post("/api/topics", json={"name": "Other synthetic scope"}).json()["id"]
                check("chat-conversation-cannot-cross-topic", client.post("/api/chat/tasks", json={"message": "Synthetic", "topic_id": other, "conversation_id": task["conversation_id"]}).status_code == 400)

            event = {"event_id": "synthetic", "topic": str(topic), "identity_key": "synthetic", "title": "Synthetic event"}
            check("integrated-event-memory-create", client.post("/api/event-memory/events", json=event).status_code == 201)
            check("integrated-event-memory-query", client.get(f"/api/event-memory/query?topic={topic}").json()["total"] == 1)
            check("event-memory-reverse-proxy-host", client.get("/api/event-memory/health", headers={"host": "backend:8000"}).status_code == 200)

            # Real Chroma write/query/delete/persistence without downloading any embedding model.
            import chromadb
            class DeterministicEmbedding:
                def __call__(self, input):
                    return [[1., 0., 0.] if "synthetic" in text.lower() else [0., 1., 0.] for text in input]
                def name(self):
                    return "synthetic-offline-v1"
                def embed_query(self, input):
                    return self(input)
            embedding = DeterministicEmbedding()
            store = chromadb.PersistentClient(path=settings.chroma_persist_dir)
            name = vector_store.COLLECTIONS["claims"]
            vector_store._client = store
            vector_store._collections[name] = store.get_or_create_collection(name, embedding_function=embedding)
            vector_store.add_claim_document("v", "Synthetic record", {"topic_id": str(topic)})
            check("chroma-real-write-and-query", vector_store.search_collection("claims", "Synthetic", where_filter={"topic_id": str(topic)})[0]["id"] == "v")
            reopened = chromadb.PersistentClient(path=settings.chroma_persist_dir)
            check("chroma-reopen-persistence", reopened.get_collection(name, embedding_function=embedding).count() == 1)
            vector_store.delete_document("v", name)
            check("chroma-delete", store.get_collection(name).count() == 0)
            vector_store._collections.clear()
            vector_store._client = None
        with TestClient(app.app) as restarted:
            check("unified-restart-retains-topics-and-events", len(restarted.get("/api/topics").json()["topics"]) >= 2
                  and restarted.get(f"/api/event-memory/query?topic={topic}").json()["total"] == 1)

print(json.dumps({"status": "ok", "checks": checks, "count": len(checks), "external_network_calls": 0}, ensure_ascii=False, indent=2))
