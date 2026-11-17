"""Offline regression checks for current-state retrieval and immutable snapshots."""
import ast
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import sqlite3
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent


class LegacySafetyCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        spec = importlib.util.spec_from_file_location("isolated_database", ROOT / "backend/database.py")
        self.db = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.db)
        self.path = str(Path(self.temp.name) / "monitor.db")
        self.db.init_db(self.path)
        self.topic = self.db.create_topic("Synthetic safety check")

    def function(self, file, name, scope):
        tree = ast.parse((ROOT / "backend" / file).read_text())
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
        exec(compile(ast.Module(body=[fn], type_ignores=[]), file, "exec"), scope)
        return scope[name]

    def test_vector_candidates_are_revalidated_and_rebuilt_from_sqlite(self):
        for ident, status, fresh in (("live", "active", "fresh"), ("replaced", "superseded", "fresh"),
                                     ("stale", "active", "stale")):
            self.db.upsert_claim(self.topic, f"Authoritative {ident}", claim_id=ident,
                                 status=status, staleness_status=fresh)
        other = self.db.create_topic("Other topic")
        self.db.upsert_claim(other, "Other topic secret", claim_id="foreign")
        hits = [{"id": ident, "collection": "kb_claims", "document": "stale vector text",
                 "metadata": {"status": "active", "topic_id": str(self.topic)}}
                for ident in ("live", "replaced", "stale", "foreign", "deleted")]
        query = self.function("chatbot.py", "_run_vector_supplement", {
            "MAX_VEC_PER_COLLECTION": 4, "search_multi_collection": lambda *a, **k: hits,
            "resolve_vector_candidate": self.db.resolve_vector_candidate})
        result = query("now", self.topic, {})["claims"]
        self.assertEqual([r["id"] for r in result], ["live"])
        self.assertEqual(result[0]["document"], "Authoritative live")
        self.assertNotIn("stale vector text", str(result))
        historical = query("past", self.topic, {"needs_archive": True})["claims"]
        self.assertEqual({r["id"] for r in historical}, {"live", "replaced", "stale"})

    def lifecycle(self, claim):
        evaluate = self.function("claim_lifecycle.py", "evaluate_claim_lifecycle", {
            "datetime": datetime, "timezone": timezone,
            "get_claims_v2": lambda *a, **k: [claim], "get_claim_evolution": lambda *a, **k: [],
            "get_evidence_sets_for_claim": lambda *a: [],
            "_pick_latest_signal": lambda *a: datetime(2020, 1, 1, tzinfo=timezone.utc),
            "ACTIVE_WINDOW_DAYS": {"medium": 7}, "INACTIVE_WINDOW_DAYS": {"medium": 21}})
        return evaluate(self.topic, now=datetime(2026, 1, 1, tzinfo=timezone.utc), persist=False)["audit"][0]

    def test_stable_facts_survive_age_but_transient_observations_expire(self):
        claim = {"id": "fact", "claim_type": "fact", "status": "active", "staleness_status": "fresh"}
        self.assertEqual(self.lifecycle(claim)["current_status"], "active")
        claim["claim_type"] = "observation"
        self.assertEqual(self.lifecycle(claim)["current_status"], "inactive")

    def test_terminal_states_are_not_revived_by_limited_recent_scan(self):
        for status in ("superseded", "archived", "inactive"):
            claim = {"id": "old", "claim_type": "fact", "status": status, "staleness_status": "replaced"}
            self.assertEqual(self.lifecycle(claim)["current_status"], status)

    def test_snapshot_captures_survive_source_updates_deletion_and_restart(self):
        claim = self.db.upsert_claim(self.topic, "Announced", claim_id="c")
        self.db.upsert_event(self.topic, "e", "key", "Original title")
        snap = self.db.save_temporal_snapshot(self.topic, "Historical record", claim_ids=[claim], event_ids=["e"])
        with sqlite3.connect(self.path) as conn:
            conn.execute("UPDATE claims SET statement='Completed' WHERE id='c'")
            conn.execute("UPDATE events_v2 SET title='Changed title' WHERE id='e'")
        self.db.init_db(self.path)
        self.assertEqual(self.db.get_snapshot_claims(snap)[0]["statement"], "Announced")
        self.assertEqual(self.db.get_snapshot_events(snap)[0]["title"], "Original title")
        with sqlite3.connect(self.path) as conn:
            conn.execute("DELETE FROM claims WHERE id='c'")
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("UPDATE snapshot_claims SET record_json='{}' WHERE snapshot_id=?", (snap,))
        self.assertEqual(self.db.get_snapshot_claims(snap)[0]["statement"], "Announced")

    def test_pre_migration_snapshot_does_not_fabricate_past_from_current_row(self):
        claim = self.db.upsert_claim(self.topic, "Current mutable content", claim_id="legacy")
        with sqlite3.connect(self.path) as conn:
            conn.execute("DROP TRIGGER capture_snapshot_claims")
        snap = self.db.save_temporal_snapshot(self.topic, "Old snapshot", claim_ids=[claim])
        self.db.init_db(self.path)
        restored = self.db.get_snapshot_claims(snap)[0]
        self.assertEqual(restored["snapshot_capture"], "unavailable")
        self.assertEqual(restored["statement"], "")


if __name__ == "__main__":
    unittest.main()
