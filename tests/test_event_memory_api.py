"""Real ASGI requests against synthetic data; no legacy clients are imported."""
import ast
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
except ImportError:
    raise unittest.SkipTest("Optional API tests require requirements-event-memory.txt")

from eventkb import Store
from eventkb.api import ROOT, create_app

JAN = "2026-01-01T00:00:00Z"
FEB = "2026-02-01T00:00:00Z"
MAR = "2026-03-01T00:00:00Z"


class APIBehavior(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = JAN
        self.store = Store(Path(self.temp.name) / "events.sqlite3", clock=lambda: self.now)
        self.store.create_event(event_id="deal", topic="one", identity_key="deal", title="Synthetic deal")
        first = self.evidence("filing", "1", "Old raw announcement: announced, amount 100")
        self.old = self.store.assert_fact("deal", field="status", value="announced", valid_from=JAN,
                                          evidence_id=first, message_key="announced")
        self.amount = self.store.assert_fact("deal", field="amount", value=100, valid_from=JAN,
                                            evidence_id=first, message_key="amount")
        self.now = "2026-02-02T00:00:00Z"
        done = self.evidence("completion", "1", "Completion filing")
        self.done = self.store.assert_fact("deal", field="status", value="completed", valid_from=FEB,
            evidence_id=done, message_key="completed", relation="transition", target_id=self.old["id"],
            reviewed=True, reason="Reviewed completion")
        self.now = MAR
        corrected = self.evidence("filing", "2", "Issuer corrected amount to 120")
        self.store.assert_fact("deal", field="amount", value=120, valid_from=JAN,
            evidence_id=corrected, message_key="corrected", relation="correction", target_id=self.amount["id"],
            reviewed=True, reason="Issuer correction")
        self.client = TestClient(create_app(self.store))
        self.addCleanup(self.client.close)

    def evidence(self, key, revision, body):
        return self.store.add_evidence(source_key=key, revision=revision, publisher="Synthetic",
            url="https://example.invalid/" + key, published_at=JAN, body=body)["id"]

    def query(self, **params):
        response = self.client.get("/api/event-memory/query", params={"topic": "one", **params})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers["cache-control"], "no-store")
        return response.json()

    def test_current_query_only_exposes_projected_values_and_active_citations(self):
        response = self.query()
        item = response["results"][0]
        self.assertEqual(item["fields"]["status"]["value"], "completed")
        self.assertEqual(item["fields"]["amount"]["value"], 120)
        self.assertNotIn("announced", json.dumps(response))
        self.assertNotIn("body", item["citations"][0])
        self.assertEqual({(e["source_key"], e["revision"]) for e in item["citations"]}, {("completion", "1"), ("filing", "2")})
        self.assertEqual(self.query(q="announced")["results"], [])
        self.assertFalse(response["model_used"])

    def test_effective_time_and_knowledge_cutoff_do_not_leak_future_knowledge(self):
        reconstructed = self.query(valid_at=JAN)["results"][0]
        self.assertEqual(reconstructed["fields"]["status"]["value"], "announced")
        self.assertEqual(reconstructed["fields"]["amount"]["value"], 120)
        then_known = self.query(valid_at=FEB, known_at="2026-01-20T00:00:00Z")
        item = then_known["results"][0]
        self.assertEqual(item["fields"]["amount"]["value"], 100)
        self.assertEqual(item["fields"]["status"]["value"], "announced")
        self.assertNotIn("completion", json.dumps(then_known))
        self.assertEqual(then_known["scope"]["mode"], "historical")
        history = self.client.get("/api/event-memory/events/deal/history", params={"topic": "one", "known_at": JAN}).json()
        self.assertEqual(len(history["assertions"]), 2)
        self.assertEqual(len(history["evidence"]), 1)

    def test_conflict_is_not_an_answer_and_keeps_both_sources(self):
        self.store.assert_fact("deal", field="status", value="cancelled", valid_from=FEB,
            evidence_id=self.evidence("rumour", "1", "Unverified rumour"), message_key="rumour")
        item = self.query()["results"][0]
        field = item["fields"]["status"]
        self.assertEqual(field["status"], "conflict")
        self.assertIsNone(field["value"])
        self.assertEqual({a["value"] for a in field["alternatives"]}, {"completed", "cancelled"})
        self.assertEqual(len(field["evidence_ids"]), 2)
        self.assertEqual(self.query(q="completed")["results"], [])

    def test_scope_is_required_and_checked_for_detail_history_and_writes(self):
        self.assertEqual(self.client.get("/api/event-memory/query").status_code, 422)
        self.assertEqual(self.query(topic="two")["results"], [])
        for action in ("state", "history"):
            self.assertEqual(self.client.get(f"/api/event-memory/events/deal/{action}", params={"topic": "two"}).status_code, 404)
        self.assertEqual(self.client.post("/api/event-memory/events/deal/memory", json={
            "topic": "two", "importance": .5, "reason": "wrong scope"}).status_code, 404)

    def test_archive_recall_restore_and_restart_preserve_evidence(self):
        before = self.store.history("deal")
        body = {"topic": "one", "importance": .2, "mode": "archived", "reason": "Low attention", "pinned": False}
        response = self.client.post("/api/event-memory/events/deal/memory", json=body)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.query()["results"], [])
        self.assertEqual(len(self.query(include_archived=True)["results"]), 1)
        reopened = Store(self.store.path, clock=lambda: self.now)
        self.assertEqual(reopened.state("deal")["memory"]["mode"], "archived")
        self.assertEqual(len(reopened.history("deal")["evidence"]), len(before["evidence"]))
        body.update(mode="summary", reason="Recall for review")
        self.assertEqual(self.client.post("/api/event-memory/events/deal/memory", json=body).status_code, 200)
        self.assertEqual(self.query()["results"][0]["memory"]["mode"], "summary")

    def test_api_validates_time_and_prevents_client_written_knowledge_time(self):
        self.assertEqual(self.client.get("/api/event-memory/query", params={"topic": "one", "valid_at": "bad"}).status_code, 400)
        body = {"topic": "one", "importance": .5, "reason": "Review", "recorded_at": JAN}
        self.assertEqual(self.client.post("/api/event-memory/events/deal/memory", json=body).status_code, 422)
        del body["recorded_at"]
        body["pinned"] = "false"
        self.assertEqual(self.client.post("/api/event-memory/events/deal/memory", json=body).status_code, 422)
        self.assertEqual(self.query(known_at="2025-01-01T00:00:00Z")["results"], [])

    def test_writes_reject_cross_origin_and_unreviewed_replacements(self):
        memory = {"topic": "one", "importance": .5, "reason": "Review"}
        path = "/api/event-memory/events/deal/memory"
        self.assertEqual(self.client.post(path, json=memory, headers={"origin": "https://untrusted.invalid"}).status_code, 403)
        self.assertEqual(self.client.post(path, json=memory, headers={"origin": "http://127.0.0.1:3870"}).status_code, 200)
        body = {"topic": "one", "field": "status", "value": "cancelled", "valid_from": FEB,
                "evidence_id": self.old["evidence_id"], "message_key": "unreviewed", "relation": "correction", "target_id": self.done["id"]}
        self.assertEqual(self.client.post("/api/event-memory/events/deal/assertions", json=body).status_code, 400)
        self.assertEqual(self.query()["results"][0]["fields"]["status"]["value"], "completed")
        self.assertEqual(self.client.get("/api/event-memory/query?topic=one", headers={"host": "untrusted.invalid"}).status_code, 403)

    def test_ingestion_api_keeps_replay_and_evidence_version_contract(self):
        evidence = {"source_key": "new", "revision": "1", "publisher": "Synthetic", "url": "https://example.invalid/new", "published_at": JAN, "body": "A new source"}
        response = self.client.post("/api/event-memory/evidence", json=evidence)
        self.assertEqual(response.status_code, 201)
        evidence_id = response.json()["id"]
        evidence["body"] = "Changed in place"
        self.assertEqual(self.client.post("/api/event-memory/evidence", json=evidence).status_code, 400)
        fact = {"topic": "one", "field": "location", "value": "Shanghai", "valid_from": JAN, "message_key": "location", "evidence_id": evidence_id}
        first = self.client.post("/api/event-memory/events/deal/assertions", json=fact).json()
        self.assertEqual(self.client.post("/api/event-memory/events/deal/assertions", json=fact).json()["id"], first["id"])
        fact["value"] = "Sydney"
        self.assertEqual(self.client.post("/api/event-memory/events/deal/assertions", json=fact).status_code, 400)

    def test_query_limit_reports_truncation(self):
        self.store.create_event(event_id="other", topic="one", identity_key="other", title="Other event")
        payload = self.query(limit=1)
        self.assertEqual(payload["total"], 2)
        self.assertTrue(payload["truncated"])
        self.assertEqual(len(payload["results"]), 1)

    def test_standalone_app_does_not_import_legacy_runtime_or_read_env_file(self):
        script = "from eventkb.api import create_app; import sys; assert not {'config','pipeline','scheduler','llm_client','vector_store','dotenv'} & set(sys.modules)"
        result = subprocess.run([sys.executable, "-c", script], cwd=ROOT, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_real_main_mount_block_is_opt_in(self):
        # Execute the actual app construction / opt-in block, omitting legacy imports and lifespan.
        tree = ast.parse((ROOT / "backend/main.py").read_text())
        block = next(node for node in tree.body if isinstance(node, ast.If) and isinstance(node.test, ast.Attribute) and node.test.attr == "event_memory_enabled")
        for enabled in (False, True):
            app = FastAPI()
            namespace = {"app": app, "settings": SimpleNamespace(event_memory_enabled=enabled,
                event_memory_database_path=str(self.store.path), cors_origins="http://localhost:3000",
                event_memory_hosts="localhost,127.0.0.1,testserver")}
            exec(compile(ast.Module(body=[block], type_ignores=[]), "backend/main.py", "exec"), namespace)
            response = TestClient(app).get("/api/event-memory/health")
            self.assertEqual(response.status_code, 200 if enabled else 404)


if __name__ == "__main__":
    unittest.main()
