"""Reproduce legacy risks without importing models, Chroma or schedulers.

These tests assert the old behavior for review. New safety is covered by
test_eventkb; the legacy runtime is deliberately unchanged in this phase.
"""
import ast
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parent.parent


class LegacyRiskCase(unittest.TestCase):
    def test_old_vector_supplement_allows_superseded_claim(self):
        tree=ast.parse((ROOT/'backend/chatbot.py').read_text())
        function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_run_vector_supplement')
        hits=[{'id':'replaced','collection':'kb_claims','metadata':{'status':'superseded'},'document':'old status'},
              {'id':'stale','collection':'kb_claims','metadata':{'status':'stale'},'document':'old stable fact'},
              {'id':'inactive','collection':'kb_claims','metadata':{'status':'inactive'},'document':'inactive'}]
        scope={'MAX_VEC_PER_COLLECTION':4,'search_multi_collection':lambda *a,**kw:hits}
        exec(compile(ast.Module(body=[function],type_ignores=[]),'legacy-vector-isolation','exec'),scope)
        result=scope['_run_vector_supplement']('now',1,{})
        self.assertEqual({h['id'] for h in result['claims']},{'replaced','stale'})

    def test_old_lifecycle_expires_stable_fact_due_only_to_age(self):
        tree=ast.parse((ROOT/'backend/claim_lifecycle.py').read_text())
        function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='evaluate_claim_lifecycle')
        from datetime import datetime,timezone
        claim={'id':'fact','statement':'Company was founded in 2000','claim_type':'fact','status':'active','staleness_status':'fresh','decay_policy':'medium'}
        scope={'datetime':datetime,'timezone':timezone,'get_claims_v2':lambda *a,**kw:[claim],
               'get_claim_evolution':lambda *a,**kw:[],'get_evidence_sets_for_claim':lambda *a:[],
               '_pick_latest_signal':lambda *a:datetime(2020,1,1,tzinfo=timezone.utc),
               'ACTIVE_WINDOW_DAYS':{'medium':7},'INACTIVE_WINDOW_DAYS':{'medium':21}}
        exec(compile(ast.Module(body=[function],type_ignores=[]),'legacy-lifecycle-isolation','exec'),scope)
        audit=scope['evaluate_claim_lifecycle'](1,now=datetime(2026,1,1,tzinfo=timezone.utc),persist=False)['audit'][0]
        self.assertEqual(audit['current_status'],'inactive')
        self.assertIn('expired',audit['reason'])

    def test_old_snapshot_joins_mutable_claim_content(self):
        import sqlite3
        with sqlite3.connect(':memory:') as db:
            db.executescript("CREATE TABLE claims(id TEXT PRIMARY KEY,statement TEXT,last_validated_at TEXT); CREATE TABLE snapshot_claims(snapshot_id INTEGER,claim_id TEXT); INSERT INTO claims VALUES('c','announced','2026-01-01'); INSERT INTO snapshot_claims VALUES(1,'c');")
            tree=ast.parse((ROOT/'backend/database.py').read_text())
            function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='get_snapshot_claims')
            sql=next(n.value for n in ast.walk(function) if isinstance(n,ast.Constant) and isinstance(n.value,str) and 'SELECT c.*' in n.value)
            self.assertEqual(db.execute(sql,(1,)).fetchone()[1],'announced')
            db.execute("UPDATE claims SET statement='completed' WHERE id='c'")
            self.assertEqual(db.execute(sql,(1,)).fetchone()[1],'completed')


if __name__=='__main__':unittest.main()
