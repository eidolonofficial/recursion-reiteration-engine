"""Offered-source search, scoped verification, accounting and controller integration."""
from __future__ import annotations
import copy
import json
import tempfile
import unittest
from pathlib import Path
from dataclasses import replace
from headroom_recursion import RecurseConfig, WorkspacePolicy, recurse, prompts, checkpoint
from headroom_recursion.archive_search import find_literal
from headroom_recursion.clients import CallResult, TransportError
from headroom_recursion.compression import ContextLimitError
from headroom_recursion.memory import MemoryStore,MemorySession,MemoryModels,Principal,MemoryContractError as E,ObservationLedger
from headroom_recursion.scoped_review import ReviewGraph,ReviewRecord,Reviewer
from headroom_recursion.local_roles import LocalRoleRunner
from headroom_recursion.quality_eval import EvaluationCase,evaluate
from headroom_recursion.runtime import BudgetExhausted,MeteredClient
from headroom_recursion.tool_catalog import ToolCatalog
from headroom_recursion.workspace import build_view,encode
from headroom_recursion.trace import RunTrace
from test_efficiency import Capture,view,delta,judge,runtime


class SearchTests(unittest.TestCase):
    def test_overlap_unicode_and_paginated_scan(self):
        for text,needle in [('aaaaaa','aaa'),('??????????','??'),('xy'*100+'needle'+'xy'*100,'needle')]:
            for budget in (len(needle),len(needle)+1,20):
                cursor=0;positions=[]
                for _ in range(2000):
                    result=find_literal(text,needle,cursor,max_matches=1,scan_chars=budget)
                    positions.extend(h['start'] for h in result['matches'])
                    if result['complete']:break
                    self.assertGreater(result['next_start'],cursor);cursor=result['next_start']
                expected=[i for i in range(len(text)) if text.startswith(needle,i)]
                self.assertEqual(positions,expected)
    def test_invalid_arguments(self):
        for needle,start in [('',0),('x',True),('x',-1),('x',10),('x'*257,0)]:
            with self.subTest(needle=needle,start=start),self.assertRaises(TransportError):find_literal('abc',needle,start)
    def test_empty_and_no_match_complete(self):
        self.assertTrue(find_literal('','x',0)['complete'])
        self.assertEqual(find_literal('abc','z',0)['matches'],[])
    def test_only_offered_aliases(self):
        r,v=view(enable_search=True)
        with self.assertRaises(TransportError):v.find_batch([['private','secret',0]],r.store,1000)
        with self.assertRaises(TransportError):v.find_batch([[v.base,'?',0]],r.store,1000)
    def test_literal_not_regex(self):
        r=find_literal('a.*b aXb','.*',0)
        self.assertEqual([h['start'] for h in r['matches']],[1])
    def test_search_authorizes_only_exact_retrieved_candidate_region(self):
        original='prefix '*1000+'TARGET'+' suffix'*1000
        r,v=view(original,enable_search=True)
        found=v.find_batch([['s0','TARGET',0]],r.store,500)
        pos=original.index('TARGET')
        self.assertEqual(found[0]['matches'][0]['start'],pos)
        result=v.patch(delta(v,[[pos,pos+6,'NEW']]),r.store)
        self.assertEqual(result,original[:pos]+'NEW'+original[pos+6:])
        with self.assertRaises(TransportError):v.patch(delta(v,[[0,1,'X']]),r.store)
    def test_search_failure_rolls_back_ranges(self):
        r,v=view('q'*5000+'target'+'x'*5000,enable_search=True)
        before=copy.deepcopy((v.ranges,v.mandatory,v.packet))
        with self.assertRaises(TransportError):v.find_batch([['s0','target',0]],r.store,1)
        self.assertEqual((v.ranges,v.mandatory,v.packet),before)
    def test_search_disabled_means_no_capability(self):
        r,v=view()
        with self.assertRaises(TransportError):v.find_batch([['s0','?',0]],r.store,1000)
    def test_search_corrupt_source_rejected(self):
        r,v=view(enable_search=True);r.store.records[v.base]='forged'
        with self.assertRaises(TransportError):v.find_batch([['s0','?',0]],r.store,1000)


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.calls=[];self.g=ReviewGraph(scope='experiment')
        def check(record,closure):
            self.calls.append(record.key)
            return record.evidence=='checked'
        self.r=Reviewer('checker-v1','finite',check)
        self.g.register(ReviewRecord('a','exact A',evidence='checked'),self.r)
        self.g.register(ReviewRecord('b','exact B',dependencies=('a',),evidence='checked'),self.r)
    def test_incremental_cache_no_extra_checks(self):
        receipt=self.g.review('b');self.g.review('b')
        self.assertEqual(self.calls,['a','b'])
        self.assertFalse(receipt['settles_target']);self.assertEqual(receipt['covers'],['a','b'])
    def test_dependency_change_invalidates_descendants(self):
        old=self.g.review('b')
        self.g.register(ReviewRecord('a','changed A',evidence='checked'),self.r)
        with self.assertRaises(E):self.g.verify_receipt(old)
        self.g.review('b');self.assertEqual(self.calls,['a','b','a','b'])
    def test_receipt_mutation_does_not_mutate_host_receipt(self):
        receipt=self.g.review('b');receipt['covers'].append('not-reviewed')
        with self.assertRaises(E):self.g.verify_receipt(receipt)
        self.assertEqual(self.g.review('b')['covers'],['a','b'])
    def test_forged_coverage_or_scope_rejected(self):
        original=self.g.review('b')
        for field,value in [('settles_target',True),('scope','other'),('id','fake'),('evidence_class','formal')]:
            receipt=copy.deepcopy(original);receipt[field]=value
            with self.subTest(field=field),self.assertRaises(E):self.g.verify_receipt(receipt)
    def test_changed_callback_same_label_invalidates(self):
        old=self.g.review('b')
        self.g.register(self.g.records['a'],Reviewer('checker-v1','finite',lambda r,c:True))
        with self.assertRaises(E):self.g.verify_receipt(old)
    def test_reentrant_callback_change_cannot_issue_stale_receipt(self):
        def check(r,c):
            self.g.register(r,Reviewer('mutating','finite',lambda r,c:True))
            return True
        self.g.register(self.g.records['a'],Reviewer('mutating','finite',check))
        with self.assertRaises(E):self.g.review('a')
        self.assertNotIn('a',self.g.receipts)
    def test_cycle_and_missing_dependency_rollback(self):
        for r in [ReviewRecord('a','x',dependencies=('b',)),ReviewRecord('x','x',dependencies=('missing',))]:
            with self.assertRaises(E):self.g.register(r,self.r)
        self.assertEqual(self.g.records['a'].statement,'exact A')
        self.assertNotIn('x',self.g.records)
    def test_finite_cannot_silently_become_formal(self):
        with self.assertRaises(E):self.g.register(ReviewRecord('p','P=NP',evidence_class='formal'),self.r)
    def test_bool_required_and_checker_error_fail_closed(self):
        for fn in (lambda r,c:1,lambda r,c:False,lambda r,c:(_ for _ in ()).throw(RuntimeError('failure'))):
            self.g.register(self.g.records['a'],Reviewer('bad','finite',fn))
            with self.assertRaises(E):self.g.review('b')
            self.assertEqual(self.g.receipts,{})
    def test_closure_budget_no_shortened_review(self):
        g=ReviewGraph(scope='test',max_closure_chars=10)
        with self.assertRaises(E):g.register(ReviewRecord('a','too much exact content'),self.r)


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.s=MemoryStore(Path(self.tmp.name)/'m.sqlite');self.addCleanup(self.s.close)
        self.p=Principal('host-user','project');self.session=MemorySession(self.s,self.p)
        self.source=self.s.add_source(self.p,'The exact SOURCE includes a negation: do not erase it.')
        self.ref=self.s.write(self.p,key='source',summary='SOURCE must not be erased.',kind='constraint',sources=[self.source],pinned=True)
    def cfg(self,**kw):
        return RecurseConfig.for_workload('research',n=1,model='test',seed_answer='KEEP',seed_scratchpad='notes',
            budget=18000,token_counter=lambda text,model:len(text),token_counter_label='Unicode characters',
            memory_session=self.session,verification_id='test-verifier-v1',max_total_calls=20,**kw)
    def test_actual_source_search_and_full_judge(self):
        searched=[False];requests=[]
        def worker(q):
            requests.append(q)
            if q['system']==prompts.HALT_SYSTEM:return '{"halt_prob":0.2,"reason":"finite fixture"}'
            packet=json.loads(q['user'])
            if packet['role']=='notes' and not searched[0]:
                searched[0]=True
                alias=packet['sources']['memory_'+self.source]['id']
                return encode({'find':[[alias,'negation',0]]})
            if packet['role']=='notes':
                self.assertIn('do not erase it',q['user'])
                return 'Preserve SOURCE and KEEP.'
            return encode({'patch':{'ticket':packet['ticket'],'edits':[[4,4,' plus checked update']]}})
        trace=recurse('Retain SOURCE',client=Capture(worker),config=self.cfg())
        self.assertEqual(trace.final_answer,'KEEP plus checked update')
        self.assertEqual(sum(e['role']=='workspace_retrieval' for e in trace.call_events),1)
        judges=[q for q in requests if q['system']==prompts.HALT_SYSTEM]
        self.assertIn(trace.final_answer,judges[-1]['user'])
        self.assertIn('SOURCE must not be erased.',judges[0]['user'])
        self.assertFalse(trace.halted)
    def test_memory_packet_is_not_chunk_truncated(self):
        cfg=self.cfg();r=MeteredClient(Capture(),cfg,RunTrace(problem='SOURCE'),None)
        r.memory_context('SOURCE','')
        v=build_view(r,role='notes',model='test',system='notes',values=dict(problem='SOURCE',answer='KEEP'))
        packet=json.loads(v.render())
        memory=json.loads(packet['memory_advice'])
        self.assertEqual(memory['records'][0]['summary'],'SOURCE must not be erased.')
        self.assertIn('memory_'+self.source,packet['sources'])
    def test_judge_cache_includes_observation_pins(self):
        r=runtime();judge(r);r.memory_pins=['new unresolved exact failure'];judge(r)
        self.assertEqual(r.trace.total_calls,2)
    def test_config_rejects_scope_mismatch(self):
        other=ObservationLedger(self.s,Principal('other','project'))
        with self.assertRaises(ValueError):self.cfg(observation_ledger=other).validate()
    def test_checkpoint_policy_binds_private_store(self):
        cfg=self.cfg();before=checkpoint.policy(cfg)
        with MemoryStore(Path(self.tmp.name)/'other.sqlite') as store:
            cfg.memory_session=MemorySession(store,self.p)
            self.assertNotEqual(before,checkpoint.policy(cfg))
    def test_memory_model_calls_count_towards_global_cap(self):
        self.session.models=MemoryModels(controller='supplied')
        def worker(q):return '{"queries":[{"text":"SOURCE","tags":[],"after":null,"before":null}]}'
        cfg=self.cfg();cfg.max_total_calls=1
        trace=recurse('SOURCE',client=Capture(worker),config=cfg)
        self.assertEqual(trace.total_calls,1);self.assertEqual(trace.stop_reason,'budget')
        self.assertEqual(trace.call_events[0]['role'],'memory_controller')
    def test_no_automatic_writes_when_host_disables(self):
        cfg=self.cfg(memory_auto_write=False);r=MeteredClient(Capture(),cfg,RunTrace(problem='SOURCE'),None)
        before=len(self.s.candidates(self.p));r.memory_accept('SOURCE','a','b','')
        self.assertEqual(len(self.s.candidates(self.p)),before)
    def test_workload_and_explicit_rungs(self):
        cfg=RecurseConfig.for_workload('coding',model='supplied',rungs=100)
        self.assertEqual(cfg.n,1);self.assertEqual(len(cfg.ladder),100)
        self.assertEqual({tier.model for tier in cfg.ladder},{'supplied'})


class BudgetAndEvaluationTests(unittest.TestCase):
    def test_role_runner_accounts_failed_attempts(self):
        class Failed:
            def complete(self,**kw):raise RuntimeError('failed')
        runner=LocalRoleRunner(Failed(),max_calls=1)
        with self.assertRaises(RuntimeError):runner(role='test',model='local',system='s',user='u',max_tokens=10)
        self.assertEqual(len(runner.events),1);self.assertGreater(runner.units,0)
        with self.assertRaises(BudgetExhausted):runner(role='test',model='local',system='s',user='u',max_tokens=10)
    def test_role_reserves_output_before_call(self):
        client=Capture();runner=LocalRoleRunner(client,max_total_units=20,counter=lambda t,m:len(t))
        with self.assertRaises(BudgetExhausted):runner(role='test',model='local',system='x'*15,user='u'*15,max_tokens=10)
        self.assertEqual(client.requests,[])
    def test_role_rejects_truncation(self):
        runner=LocalRoleRunner(Capture(lambda q:CallResult('{}',stop_reason='length')))
        with self.assertRaises(TransportError):runner(role='writer',model='local',system='s',user='u',max_tokens=20)
    def test_paired_evaluation_counts_failed_reduced_arm_and_preparation(self):
        def worker(q):
            context=json.loads(q['user'])['context']
            return 'NEGATED' if 'NOT' in context else 'UNKNOWN'
        case=EvaluationCase('negation','status','NOT approved','approved',3,7)
        report=evaluate([case],client=Capture(worker),verifier=lambda c,a:a=='NEGATED',model='fixture',
                        backend_kind='deterministic-test',backend_identity='exact-text-interpreter',counter=lambda t,m:len(t),max_tokens=100)
        self.assertEqual(report['summary']['full']['checked_successes'],1)
        self.assertEqual(report['summary']['reduced']['checked_successes'],0)
        self.assertEqual(report['summary']['reduced']['preparation_units'],7)
        self.assertIsNone(report['summary']['reduced']['units_per_checked_success'])
        self.assertFalse(report['population_claim'])
    def test_tool_catalog_discloses_only_allowlisted_schemas(self):
        catalog=ToolCatalog([dict(name='read_source',description='Read exact sources',input_schema={'type':'object'})])
        self.assertEqual(catalog.discover('sources')[0]['name'],'read_source')
        with self.assertRaises(E):catalog.schema('run_shell')
        schema=catalog.schema('read_source');schema['name']='mutated'
        self.assertEqual(catalog.schema('read_source')['name'],'read_source')


class AdmissionTests(unittest.TestCase):
    def bridge(self):
        from headroom_recursion.folding import ResearchBridge
        class Registry:
            scope='finite-fixture'
            state={'policy':'declared-fixture'}
            def admission(self,ref):
                return {'id':ref,'evidence_class':'finite','settles_target':False}
        return ResearchBridge(Registry(),'Exact research history: P versus NP is not settled by this fixture.',tuple('record-'+str(i) for i in range(100)))
    def test_100_host_admissions_preserve_history_and_never_claim_proof(self):
        bridge=self.bridge();answer=bridge.history
        for i in range(100):
            receipt=bridge.admit_checked(answer,('record-'+str(i),))
            self.assertFalse(receipt['whole_proof_reviewed']);self.assertFalse(receipt['settles_target'])
            self.assertEqual(receipt['model_calls'],0);answer=receipt['answer']
        self.assertEqual(len(bridge.parse(answer)),100)
        self.assertTrue(answer.startswith(bridge.history))
    def test_immutable_history_and_exact_ids(self):
        from headroom_recursion.folding.types import FoldError
        bridge=self.bridge()
        with self.assertRaises(FoldError):bridge.admit_checked('changed',('record-0',))
        with self.assertRaises(FoldError):bridge.admit_checked(bridge.history,('forged',))
        with self.assertRaises(FoldError):bridge.admit_checked(bridge.history,([],))
    def test_confirmation_receipts_never_auto_written_into_generation_memory(self):
        cfg=self.bridge().bind(RecurseConfig.efficient())
        self.assertFalse(cfg.memory_auto_write);self.assertFalse(cfg.oracle_sufficient)
        self.assertFalse(cfg.judge_can_halt)


if __name__=='__main__':unittest.main()
