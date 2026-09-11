"""Private-memory regression and adversarial contract tests; no neural inference."""
from __future__ import annotations
import copy
from contextlib import closing
import json
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from headroom_recursion.memory import (MemoryStore, MemoryPolicy, MemoryModels,
    MemorySession, MemoryContractError as E, Principal, ObservationLedger)
from headroom_recursion.memory.contracts import digest, timestamp
from headroom_recursion.clients import CallResult
from headroom_recursion.compression import ContextLimitError
from headroom_recursion.runtime import BudgetExhausted


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'private.sqlite'
        self.s=MemoryStore(self.path)
        self.addCleanup(self.s.close)
        self.p=Principal('alice','repo')
        self.other=Principal('bob','repo')
        self.src=self.s.add_source(self.p,'Do not delete unverified evidence. Keep the exception.')
    def write(self,key='decision',summary='Do not delete unverified evidence.',**kw):
        return self.s.write(self.p,key=key,summary=summary,kind='decision',sources=[self.src],**kw)
    def item(self,key,summary,**kw):
        d=dict(key=key,summary=summary,kind='decision',sources=[self.src],tags=[],expected=None,
               created=None,pinned=False,dependencies=[])
        d.update(kw);return d
    def session(self,**models):
        return MemorySession(self.s,self.p,models=MemoryModels(**models))
    def sender(self,value):
        return lambda **request:CallResult(json.dumps(value))


class StoreTests(Fixture):
    def test_scope_isolation(self):
        ref=self.write()
        for operation in (lambda:self.s.get(self.other,ref),lambda:self.s.source(self.other,self.src)):
            with self.assertRaises(E):operation()
        self.assertEqual(self.s.candidates(self.other),[])
    def test_project_isolation(self):
        with self.assertRaises(E):self.s.source(Principal('alice','elsewhere'),self.src)
    def test_exact_source_and_negation_survive_reopen(self):
        ref=self.write()
        with MemoryStore(self.path) as reopened:
            self.assertEqual(reopened.source(self.p,self.src),'Do not delete unverified evidence. Keep the exception.')
            self.assertEqual(reopened.get(self.p,ref)['summary'],'Do not delete unverified evidence.')
            self.assertEqual(reopened.identity,self.s.identity)
    def test_database_identity_differs(self):
        with MemoryStore(Path(self.tmp.name)/'other.sqlite') as other:
            self.assertNotEqual(other.identity,self.s.identity)
    def test_no_vector_or_shared_graph(self):
        self.assertFalse(hasattr(self.s,'embedding'))
        self.assertFalse(hasattr(self.s,'publish'))
        tables={r[0] for r in self.s.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertFalse({'node','edge','graph_head'}&tables)
    def test_rejects_existing_unknown_database_without_mutation(self):
        path=Path(self.tmp.name)/'unrelated.sqlite'
        with closing(sqlite3.connect(path)) as db:
            db.execute('CREATE TABLE unrelated(x)');db.commit()
        original=path.read_bytes()
        with self.assertRaises(E):MemoryStore(path)
        self.assertEqual(path.read_bytes(),original)
    def test_versioned_sources_are_not_overwritten(self):
        old=self.write(created='2026-01-01T00:00:00Z')
        new=self.write(summary='Do not delete except after exact host review.',expected=old,created='2026-02-01T00:00:00Z')
        self.assertEqual(self.s.get(self.p,new)['supersedes'],old)
        self.assertEqual(self.s.get(self.p,new)['version'],2)
        self.assertIn('unverified',self.s.get(self.p,old)['summary'])
        self.assertFalse(self.s.get(self.p,old)['active'])
    def test_stale_compare_and_swap_fails(self):
        old=self.write()
        with self.assertRaises(E):self.write(summary='different')
        self.assertEqual(self.s.head(self.p,'decision')['id'],old)
    def test_batch_rolls_back_first_write_on_second_conflict(self):
        self.write('existing')
        with self.assertRaises(E):self.s.write_batch(self.p,[self.item('new','new'),self.item('existing','wrong')])
        self.assertIsNone(self.s.head(self.p,'new'))
    def test_dependencies_invalidated_transitively(self):
        a=self.write('a','assumption a')
        b=self.write('b','decision b',dependencies=[a])
        c=self.write('c','procedure c',dependencies=[b])
        self.write('a','assumption changed',expected=a)
        self.assertTrue(self.s.get(self.p,b)['invalidated'])
        self.assertTrue(self.s.get(self.p,c)['invalidated'])
        self.assertEqual([r['key'] for r in self.s.candidates(self.p)],['a'])
        self.assertTrue(self.s.audit())
    def test_stale_dependency_cannot_be_reintroduced(self):
        old=self.write('a','original')
        self.write('a','changed',expected=old)
        with self.assertRaises(E):self.write('b',dependencies=[old])
    def test_cross_principal_dependency_rejected(self):
        src=self.s.add_source(self.other,'private')
        ref=self.s.write(self.other,key='private',summary='private',kind='fact',sources=[src])
        with self.assertRaises(E):self.write('b',dependencies=[ref])
    def test_pins_require_explicit_retirement(self):
        ref=self.write(pinned=True)
        with self.assertRaises(E):self.write(summary='weakened',expected=ref)
        resolution=self.s.add_source(self.p,'Host explicitly retires this exact constraint.')
        self.s.retire(self.p,'decision',expected=ref,resolution_source=resolution)
        new=self.write(summary='new constraint',expected=ref)
        self.assertNotEqual(new,ref)
        self.assertEqual(self.s.db.execute('SELECT resolution FROM retirement').fetchone()[0],resolution)
    def test_pinned_capacity_rolls_back(self):
        self.s.policy=replace(self.s.policy,capacity=1)
        self.write('a',pinned=True)
        with self.assertRaises(E):self.write('b',pinned=True)
        self.assertIsNone(self.s.head(self.p,'b'))
    def test_pruning_retains_originals(self):
        self.s.policy=replace(self.s.policy,capacity=1)
        old=self.write('a');self.write('b')
        self.assertFalse(self.s.get(self.p,old)['active'])
        self.assertIn('exception',self.s.source(self.p,self.src))
    def test_history_cap_rejects_not_deletes(self):
        self.s.policy=replace(self.s.policy,max_records=1)
        old=self.write()
        with self.assertRaises(E):self.write(summary='new',expected=old)
        self.assertEqual(self.s.head(self.p,'decision')['id'],old)
    def test_source_capacity_rejects_without_evidence_eviction(self):
        self.s.policy=replace(self.s.policy,max_archive_bytes=1024)
        with self.assertRaises(E):self.s.add_source(self.p,'x'*1100)
        self.assertTrue(self.s.source(self.p,self.src))
    def test_historical_window_uses_correct_version(self):
        old=self.write(created='2026-01-01T00:00:00Z')
        self.write(summary='new',expected=old,created='2026-03-01T00:00:00Z')
        rows=self.s.candidates(self.p,before='2026-02-01T00:00:00Z')
        self.assertEqual(rows[0]['id'],old)
    def test_uses_are_not_authority(self):
        ref=self.write();self.s.touch(self.p,[ref]);self.s.touch(self.p,[ref])
        row=self.s.get(self.p,ref)
        self.assertEqual(row['uses'],2);self.assertEqual(row['authority'],'advisory')
    def test_record_tampering_detected(self):
        ref=self.write();self.s.db.execute("UPDATE entry SET body='{}' WHERE id=?",(ref,))
        with self.assertRaises(E):self.s.get(self.p,ref)
    def test_source_tampering_detected(self):
        self.s.db.execute("UPDATE source SET text='changed'")
        with self.assertRaises(E):self.s.source(self.p,self.src)
    def test_restricted_evidence_tags_rejected(self):
        for tag in ('holdout','Confirmation','restricted','validation'):
            with self.subTest(tag=tag),self.assertRaises(E):self.write(item_tags=[tag])
    def test_strict_policy_values(self):
        for kw in ({'k':True},{'capacity':0},{'summary_chars':1},{'max_records':False}):
            with self.subTest(kw=kw),self.assertRaises(E):MemoryPolicy(**kw)
    def test_timezone_required(self):
        with self.assertRaises(E):timestamp('2026-01-01')


class RoleTests(Fixture):
    def test_fallback_lexical_scope_and_budget(self):
        for i in range(8):self.write(str(i),'alpha evidence '+str(i))
        session=self.session();r=session.retrieve('alpha',k=2)
        self.assertEqual(len(r.records),2)
        self.assertIn(self.src,r.source_refs)
        self.assertIn('advisory',r.text)
    def test_irrelevant_query_returns_no_random_memory(self):
        self.write();self.assertEqual(self.session().retrieve('unrelated-zebra').records,())
    def test_selector_cannot_invent_ids_or_authority(self):
        self.write();session=self.session(selector='operator-model')
        for value in ({'keep':['forged']},{'keep':[],'verified':True},{'keep':[True]}):
            r=session.retrieve('evidence',send=self.sender(value))
            self.assertEqual(len(r.records),1)
            self.assertTrue(any(e.get('error') for e in session.events))
    def test_selector_only_selects_not_rewrites(self):
        ref=self.write();session=self.session(selector='operator-model')
        r=session.retrieve('evidence',send=self.sender({'keep':[ref]}))
        self.assertEqual(r.records[0]['summary'],'Do not delete unverified evidence.')
    def test_selector_cannot_drop_pins(self):
        ref=self.write(pinned=True);session=self.session(selector='operator-model')
        r=session.retrieve('anything',send=self.sender({'keep':[]}))
        self.assertEqual(r.records[0]['id'],ref)
        self.assertIn('Do not delete',r.required_pins[0])
    def test_too_many_pins_fail_closed(self):
        self.write('a',pinned=True);self.write('b',pinned=True)
        with self.assertRaises(ContextLimitError):self.session().retrieve('query',k=1)
    def test_invalid_controller_scope_falls_back(self):
        self.write();r=self.session(controller='model').retrieve('evidence',send=self.sender({'queries':[],'user':'bob'}))
        self.assertEqual(len(r.records),1)
    def test_budget_exhaustion_not_swallowed_as_fallback(self):
        def exhausted(**kw):raise BudgetExhausted('bounded')
        with self.assertRaises(BudgetExhausted):self.session(controller='model').retrieve('query',send=exhausted)
    def test_writer_does_not_receive_database_or_other_user(self):
        session=self.session(writer='model');captured=[]
        def sender(**kw):
            captured.append(json.loads(kw['user']))
            return CallResult('{"items":[]}')
        session.write_turn('task','accepted',send=sender)
        self.assertNotIn('database',captured[0]);self.assertNotIn('owner',captured[0])
    def test_exact_delta_fallback_does_not_cut_negation(self):
        session=self.session()
        result=session.write_turn('task','Accept only if verified; otherwise do not accept.')
        self.assertIn('otherwise do not accept.',self.s.get(self.p,result[0])['summary'])
    def test_oversized_delta_archived_not_truncated(self):
        session=self.session();delta='a'*900+' DO NOT ACCEPT'
        self.assertEqual(session.write_turn('task',delta),())
        texts=[r[0] for r in self.s.db.execute('SELECT text FROM source')]
        self.assertTrue(any('DO NOT ACCEPT' in t for t in texts))
        self.assertEqual(self.s.candidates(self.p),[])
    def test_writer_authority_forgery_rejected(self):
        result=self.session(writer='model').write_turn('task','accepted',send=self.sender({'items':[], 'verified':True}))
        self.assertEqual(result,())
    def test_writer_cannot_overwrite_unoffered_head(self):
        old=self.write();session=self.session(writer='model')
        proposal={'items':[dict(key='decision',summary='changed',kind='decision',tags=[])]}
        self.assertEqual(session.write_turn('task','accepted',send=self.sender(proposal)),())
        self.assertEqual(self.s.head(self.p,'decision')['id'],old)
    def test_writer_snapshot_rejects_concurrent_update(self):
        old=self.write();session=self.session(writer='model');session.retrieve('evidence')
        def sender(**kw):
            self.write(summary='concurrent authoritative host edit',expected=old)
            return CallResult(json.dumps({'items':[dict(key='decision',summary='stale model overwrite',kind='decision',tags=[])]}))
        self.assertEqual(session.write_turn('task','accepted',send=sender),())
        self.assertEqual(self.s.head(self.p,'decision')['summary'],'concurrent authoritative host edit')
    def test_writer_can_update_offered_unpinned_advice(self):
        old=self.write();session=self.session(writer='model');session.retrieve('evidence')
        proposal={'items':[dict(key='decision',summary='Do not delete except after host review.',kind='decision',tags=[])]}
        refs=session.write_turn('task','accepted',send=self.sender(proposal))
        self.assertEqual(self.s.get(self.p,refs[0])['supersedes'],old)
    def test_model_cannot_weaken_pin(self):
        old=self.write(pinned=True);session=self.session(writer='model');session.retrieve('evidence')
        proposal={'items':[dict(key='decision',summary='delete freely',kind='decision',tags=[])]}
        self.assertEqual(session.write_turn('task','accepted',send=self.sender(proposal)),())
        self.assertEqual(self.s.head(self.p,'decision')['id'],old)
    def test_session_identity_binds_database_and_principal(self):
        a=self.session();b=MemorySession(self.s,self.other)
        self.assertNotEqual(a.identity,b.identity)
        with MemoryStore(Path(self.tmp.name)/'different.sqlite') as store:
            self.assertNotEqual(a.identity,MemorySession(store,self.p).identity)
    def test_truncated_role_response_rejected(self):
        refs=self.session(writer='model').write_turn('task','accepted',send=lambda **kw:CallResult('{"items":[]}',stop_reason='length'))
        self.assertEqual(refs,())
    def test_event_retention_is_bounded(self):
        session=self.session()
        for i in range(2100):session._emit({'stage':'fixture'})
        self.assertEqual(len(session.events),2048)
        self.assertEqual(session.event_sequence,2100)


class ConsolidationTests(Fixture):
    def proposal(self):
        ref=self.write('a','alpha procedure')
        session=self.session(consolidator='operator-model')
        draft={'items':[dict(key='procedure',summary='alpha procedure; preserve uncertainty.',kind='procedure',tags=[],entries=[ref])]}
        proposal=session.consolidate(send=self.sender(draft))
        return ref,session,proposal
    def test_offline_is_explicit_and_staged_not_applied(self):
        ref,session,p=self.proposal()
        self.assertFalse(p['shared']);self.assertFalse(p['applied'])
        self.assertIsNone(self.s.head(self.p,'procedure'))
    def test_approval_required(self):
        ref,session,p=self.proposal()
        with self.assertRaises(E):self.s.apply_consolidation(self.p,p['job'],p['draft_hash'],approve=lambda d:False,approval_id='review')
        self.assertIsNone(self.s.head(self.p,'procedure'))
    def test_apply_is_private_advisory_and_dependency_bound(self):
        ref,session,p=self.proposal()
        refs=self.s.apply_consolidation(self.p,p['job'],p['draft_hash'],approve=lambda d:True,approval_id='trusted-review-v1')
        row=self.s.get(self.p,refs[0]);self.assertEqual(row['dependencies'],[ref]);self.assertEqual(row['authority'],'advisory')
        self.write('a','updated premise',expected=ref)
        self.assertTrue(self.s.get(self.p,refs[0])['invalidated'])
    def test_changed_head_invalidates_approval(self):
        ref,session,p=self.proposal();self.write('a','changed',expected=ref)
        with self.assertRaises(E):self.s.apply_consolidation(self.p,p['job'],p['draft_hash'],approve=lambda d:True,approval_id='review')
    def test_second_application_rejected(self):
        ref,session,p=self.proposal()
        self.s.apply_consolidation(self.p,p['job'],p['draft_hash'],approve=lambda d:True,approval_id='review')
        with self.assertRaises(E):self.s.apply_consolidation(self.p,p['job'],p['draft_hash'],approve=lambda d:True,approval_id='review')
    def test_unoffered_source_rejected(self):
        self.write()
        draft={'items':[dict(key='fake',summary='fake',kind='fact',tags=[],entries=['forged'])]}
        with self.assertRaises(E):self.session(consolidator='model').consolidate(send=self.sender(draft))
        self.assertIsNone(self.s.head(self.p,'fake'))
    def test_scope_cannot_consume_another_job(self):
        ref,session,p=self.proposal()
        with self.assertRaises(E):self.s.apply_consolidation(self.other,p['job'],p['draft_hash'],approve=lambda d:True,approval_id='review')
    def test_no_hidden_consolidator(self):
        with self.assertRaises(E):self.session().consolidate()
    def test_no_private_consolidation_when_disabled(self):
        self.s.policy=replace(self.s.policy,allow_private_consolidation=False)
        self.write()
        self.assertIsNone(self.s.reserve_batch(self.p))


class ObservationTests(Fixture):
    def ledger(self):return ObservationLedger(self.s,self.p)
    def test_failure_never_masked_and_exit_code_preserved(self):
        ledger=self.ledger();ledger.record('tests','FAILED exact details',status='failure',revision='abc',exit_code=1,failed_tests=2)
        view=ledger.view(revision='def')
        row=json.loads(view['text'])['observations'][0]
        self.assertFalse(row['masked']);self.assertTrue(row['stale'])
        self.assertEqual(row['failed_tests'],2);self.assertEqual(row['exit_code'],1)
        self.assertIn('FAILED exact details',view['required_pins'][0])
    def test_failure_budget_overflow_does_not_hide(self):
        ledger=self.ledger();ledger.record('tests','x'*2000,status='failure',revision='abc')
        with self.assertRaises(ContextLimitError):ledger.view(max_chars=1000)
    def test_success_bulk_masked_but_recoverable(self):
        ledger=self.ledger();raw='successful line\n'*1000
        ledger.record('tests',raw,status='success',revision='abc',exit_code=0,failed_tests=0)
        view=ledger.view();row=json.loads(view['text'])['observations'][0]
        self.assertTrue(row['masked']);self.assertEqual(view['sources'][row['source']],raw)
        self.assertLess(len(view['text']),len(raw))
    def test_empty_success_not_failed_call(self):
        ledger=self.ledger();ledger.record('find','',status='success',revision='abc',exit_code=0)
        row=json.loads(ledger.view()['text'])['observations'][0]
        self.assertEqual(row['exact_output'],'');self.assertEqual(row['status'],'success')
    def test_contradictory_success_rejected(self):
        for kw in ({'exit_code':1},{'failed_tests':1}):
            with self.subTest(kw=kw),self.assertRaises(E):self.ledger().record('test','',status='success',revision='abc',**kw)
    def test_host_resolution_required_and_recoverable(self):
        ledger=self.ledger();oid=ledger.record('test','old failure',status='failure',revision='a')
        resolution=self.s.add_source(self.p,'new successful exact test')
        ledger.resolve(oid,resolution_source=resolution)
        view=ledger.view();self.assertEqual(view['required_pins'],[])
        self.assertIn(resolution,view['sources'])
    def test_cross_scope_resolution_rejected(self):
        ledger=self.ledger();oid=ledger.record('test','failed',status='failure',revision='a')
        other=self.s.add_source(self.other,'fake resolution')
        with self.assertRaises(E):ledger.resolve(oid,resolution_source=other)
    def test_unknown_status_is_unresolved(self):
        ledger=self.ledger();ledger.record('command','unknown termination',status='unknown',revision='a')
        self.assertEqual(len(ledger.view()['required_pins']),1)


if __name__=='__main__':unittest.main()
