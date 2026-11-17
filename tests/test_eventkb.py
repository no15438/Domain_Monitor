import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from eventkb import Store
from eventkb.demo import seed
from eventkb.server import make_server

JAN = "2026-01-01T00:00:00Z"
FEB = "2026-02-01T00:00:00Z"
MAR = "2026-03-01T00:00:00Z"


class EventCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = JAN
        self.store = Store(Path(self.temp.name)/"test.sqlite3", clock=lambda:self.now)
        self.store.create_event(event_id="deal",topic="test",identity_key="deal-1",title="Synthetic deal",kind="acquisition")
        self.ev = self.evidence("filing","1")
        self.announced = self.fact("status","announced","announced")

    def evidence(self,key,revision,body="Synthetic evidence",published=JAN):
        return self.store.add_evidence(source_key=key,revision=revision,publisher="Synthetic",url="https://example.invalid/"+key,published_at=published,body=body)["id"]

    def fact(self,field,value,key,**kwargs):
        return self.store.assert_fact("deal",field=field,value=value,message_key=key,valid_from=kwargs.pop("valid_from",JAN),evidence_id=kwargs.pop("evidence_id",self.ev),**kwargs)

    def complete(self):
        self.now = "2026-02-02T00:00:00Z"
        return self.fact("status","completed","completed",valid_from=FEB,relation="transition",target_id=self.announced["id"],reviewed=True,reason="Reviewed completion filing")

    def test_replay_is_idempotent_and_cannot_overwrite(self):
        self.complete()
        self.now = MAR
        replay = self.fact("status","announced","announced")
        self.assertEqual(replay["id"],self.announced["id"])
        self.assertEqual(len(self.store.history("deal")["assertions"]),2)
        self.assertEqual(self.store.state("deal")["fields"]["status"]["value"],"completed")
        with self.assertRaises(ValueError):
            self.fact("status","cancelled","announced")

    def test_late_bounded_report_does_not_pollute_current(self):
        self.complete()
        self.now = MAR
        late = self.evidence("late","1",published=JAN)
        self.fact("status","announced","late",valid_to=FEB,evidence_id=late)
        self.assertEqual(self.store.state("deal")["fields"]["status"]["value"],"completed")
        self.assertEqual(self.store.state("deal",valid_at="2026-01-15T00:00:00Z")["fields"]["status"]["value"],"announced")
        self.assertEqual(self.store.search("announced"),[])
        self.assertEqual(len(self.store.search("completed")),1)

    def test_unbounded_late_conflict_is_explicit_and_newest_does_not_win(self):
        self.complete()
        self.now = MAR
        self.fact("status","cancelled","unverified",evidence_id=self.evidence("rumour","1"),confidence=.1)
        status = self.store.state("deal")["fields"]["status"]
        self.assertEqual(status["status"],"conflict")
        self.assertIsNone(status["value"])
        self.assertEqual({f["value"] for f in status["alternatives"]},{"completed","cancelled"})
        self.assertEqual(self.store.search("completed"),[])

    def test_field_correction_preserves_other_fields_and_as_known_history(self):
        original = self.fact("amount",100,"amount")
        self.fact("participants",[{"id":"north","role":"buyer"}],"parties")
        self.complete()
        self.now = "2026-02-03T00:00:00Z"
        revised = self.evidence("filing","2",body="Synthetic corrected amount 120")
        correction = self.fact("amount",120,"correction",evidence_id=revised,relation="correction",target_id=original["id"],reviewed=True,reason="Issuer corrected typo")
        current = self.store.state("deal")["fields"]
        self.assertEqual(current["amount"]["value"],120)
        self.assertEqual(current["status"]["value"],"completed")
        self.assertEqual(current["participants"]["value"][0]["id"],"north")
        past = self.store.state("deal",valid_at="2026-01-15T00:00:00Z",known_at="2026-01-20T00:00:00Z")
        self.assertEqual(past["fields"]["amount"]["value"],100)
        retrospective = self.store.state("deal",valid_at="2026-01-15T00:00:00Z")
        self.assertEqual(retrospective["fields"]["amount"]["value"],120)
        self.assertEqual(retrospective["fields"]["status"]["value"],"announced")
        history = self.store.history("deal")
        self.assertIn(original["id"],{f["id"] for f in history["assertions"]})
        self.assertEqual(correction["target_id"],original["id"])
        self.assertEqual({e["revision"] for e in history["evidence"]},{"1","2"})

    def test_valid_and_knowledge_time_are_independent_and_timezone_normalized(self):
        self.complete()
        old = self.store.state("deal",valid_at=FEB,known_at="2026-02-01T12:00:00Z")
        new = self.store.state("deal",valid_at="2026-02-01T08:00:00+08:00",known_at="2026-02-02T00:00:00Z")
        self.assertEqual(old["fields"]["status"]["value"],"announced")
        self.assertEqual(new["fields"]["status"]["value"],"completed")
        with self.assertRaises(KeyError):self.store.state("deal",known_at="2025-01-01T00:00:00Z")

    def test_stable_fact_does_not_expire_when_news_gets_old(self):
        self.fact("location","Shanghai","location")
        self.now = "2036-01-01T00:00:00Z"
        field = self.store.state("deal")["fields"]["location"]
        self.assertEqual(field["value"],"Shanghai")
        self.assertEqual(field["status"],"confirmed")
        self.assertLess(self.store.search()[0]["retrieval"]["weight"],.01)

    def test_transition_expiry_does_not_resurrect_predecessor(self):
        self.now = "2026-02-02T00:00:00Z"
        self.fact("status","completed","limited",valid_from=FEB,valid_to=MAR,relation="transition",target_id=self.announced["id"],reviewed=True,reason="Known interval")
        self.now = "2026-04-01T00:00:00Z"
        self.assertNotIn("status",self.store.state("deal")["fields"])

    def test_correction_of_closed_predecessor_never_resurrects_it(self):
        self.complete()
        self.now = MAR
        self.fact("status","proposed","fix-old",relation="correction",target_id=self.announced["id"],reviewed=True,reason="Historical wording corrected")
        self.assertEqual(self.store.state("deal")["fields"]["status"]["value"],"completed")
        self.assertEqual(self.store.state("deal",valid_at=JAN)["fields"]["status"]["value"],"proposed")

    def test_conflict_can_be_resolved_with_evidenced_correction_and_audit(self):
        self.complete()
        self.now = MAR
        rumour=self.fact("status","cancelled","rumour",valid_from=FEB)
        self.assertTrue(self.store.state("deal")["has_conflicts"])
        self.now="2026-03-02T00:00:00Z"
        self.fact("status","completed","rumour-corrected",valid_from=FEB,relation="correction",target_id=rumour["id"],evidence_id=self.evidence("retraction","1",body="Synthetic rumour correction"),reviewed=True,reason="Source corrected false cancellation claim")
        self.assertEqual(self.store.state("deal")["fields"]["status"]["value"],"completed")
        self.assertTrue(self.store.state("deal",known_at=MAR)["has_conflicts"])

    def test_evidence_versions_and_append_only_sql(self):
        self.assertEqual(self.evidence("filing","1"),self.ev)
        with self.assertRaises(ValueError):self.evidence("filing","1",body="changed")
        self.assertNotEqual(self.evidence("filing","2",body="changed"),self.ev)
        with self.store.connection() as db:
            for sql in ("DELETE FROM evidence","UPDATE assertions SET value_json='null'","DELETE FROM events","DELETE FROM memory_policy"):
                with self.assertRaises(sqlite3.IntegrityError):db.execute(sql)

    def test_importance_archive_and_restore_do_not_change_truth_or_evidence(self):
        self.complete()
        before=self.store.history("deal")
        self.now=MAR
        self.store.set_memory("deal",importance=.1,mode="archived",reason="Low priority")
        self.assertEqual(self.store.search(),[])
        self.assertEqual(len(self.store.search(include_archived=True)),1)
        self.assertEqual(self.store.state("deal")["fields"]["status"]["value"],"completed")
        self.now="2026-03-02T00:00:00Z"
        self.store.set_memory("deal",importance=1,pinned=True,reason="Important again")
        self.assertEqual(len(self.store.search()),1)
        self.assertEqual(self.store.search()[0]["retrieval"]["weight"],1)
        self.assertEqual(self.store.history("deal")["evidence"],before["evidence"])
        self.assertEqual(self.store.history("deal")["assertions"],before["assertions"])
        self.assertEqual(self.store.state("deal",known_at=MAR)["memory"]["mode"],"archived")

    def test_memory_index_is_regenerable_and_archives_retain_dossiers(self):
        self.complete()
        self.now=MAR
        self.store.set_memory("deal",importance=.1,mode="archived",reason="Recoverable")
        out=Path(self.temp.name)/"memory"
        self.store.export_memory(out)
        self.assertNotIn("[deal]",(out/"MEMORY.md").read_text())
        self.assertIn("[deal]",(out/"archive.md").read_text())
        self.assertIn(self.announced["id"],(out/"events/deal.md").read_text())
        (out/"MEMORY.md").write_text("fake current status")
        self.assertEqual(self.store.state("deal")["fields"]["status"]["value"],"completed")
        self.store.export_memory(out)
        self.assertNotIn("fake current status",(out/"MEMORY.md").read_text())

    def test_validation_prevents_unsafe_replacements_and_missing_evidence(self):
        for args in (dict(relation="transition",target_id=self.announced["id"]),dict(valid_to=JAN),dict(evidence_id="missing"),dict(valid_from="2026-01-01"),dict(confidence=2)):
            with self.assertRaises(ValueError):self.fact("status","bad","bad",**args)
        with self.assertRaises(ValueError):self.store.create_event(event_id="../escape",topic="test",identity_key="bad",title="bad")
        with self.assertRaises(ValueError):self.store.create_event(event_id="different",topic="test",identity_key="deal-1",title="different")

    def test_restart_and_topic_isolation(self):
        self.complete()
        restarted=Store(self.store.path,clock=lambda:self.now)
        self.assertEqual(restarted.state("deal")["fields"]["status"]["value"],"completed")
        self.assertEqual(restarted.search(topic="another-topic"),[])

    def test_clock_rollback_rejected(self):
        self.now="2025-01-01T00:00:00Z"
        with self.assertRaises(ValueError):self.fact("amount",1,"rollback")


class HTTPCase(unittest.TestCase):
    def test_local_api_create_evidence_assert_query_archive_restore_and_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/"http.sqlite3")
            server=make_server(store,0)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            base=f"http://127.0.0.1:{server.server_port}"
            def call(path,body=None,headers=None):
                request=Request(base+path,data=json.dumps(body).encode() if body is not None else None,headers={"Content-Type":"application/json",**(headers or {})})
                with urlopen(request,timeout=5) as r:return r.status,json.load(r)
            try:
                self.assertTrue(call('/health')[1]['ok'])
                with urlopen(base,timeout=5) as response:self.assertIn('Event Memory Lab',response.read().decode())
                call('/api/events',dict(event_id='http',topic='test',identity_key='http',title='HTTP synthetic'))
                ev=call('/api/evidence',dict(source_key='http',revision='1',publisher='Synthetic',url='https://example.invalid/http',published_at=JAN,body='Synthetic HTTP evidence'))[1]
                call('/api/events/http/assertions',dict(field='status',value='completed',valid_from=JAN,evidence_id=ev['id'],message_key='http'))
                self.assertEqual(call('/api/events/http/state')[1]['fields']['status']['value'],'completed')
                self.assertEqual(len(call('/api/events/http/history')[1]['evidence']),1)
                call('/api/events/http/memory',dict(importance=.1,mode='archived',reason='test'))
                self.assertEqual(call('/api/events')[1],[])
                self.assertEqual(len(call('/api/events?include_archived=true')[1]),1)
                call('/api/events/http/memory',dict(importance=1,mode='active',reason='restore'))
                self.assertEqual(len(call('/api/events')[1]),1)
                with self.assertRaises(HTTPError) as err:call('/api/events',dict(event_id='x'),headers={'Origin':'https://example.invalid'})
                self.assertEqual(err.exception.code,403)
                with self.assertRaises(HTTPError) as err:call('/api/events/http/assertions',dict(field='status',value='bad',valid_from=JAN,evidence_id='missing',message_key='bad'))
                self.assertEqual(err.exception.code,400)
            finally:
                server.shutdown();server.server_close();thread.join(timeout=5)
            restarted=Store(store.path)
            self.assertEqual(restarted.state('http')['fields']['status']['value'],'completed')

    def test_demo_is_synthetic_replayable_and_offline(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'demo.sqlite3')
            self.assertTrue(seed(store)['synthetic'])
            count=len(store.history('acquisition-demo-en')['assertions'])
            seed(store)
            self.assertEqual(len(store.history('acquisition-demo-en')['assertions']),count)
            self.assertEqual(store.state('acquisition-demo-en')['fields']['status']['value'],'completed')
            self.assertTrue(store.state('rumour-demo-en')['has_conflicts'])


if __name__ == '__main__':
    unittest.main()
