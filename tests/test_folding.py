import copy
import dataclasses
import json
import math
import tempfile
import unittest
from pathlib import Path
from headroom_recursion import RecurseConfig, Tier, recurse, CallResult, WorkspacePolicy
from headroom_recursion.folding import (Store,Folding,Policy,Proposal,Evaluator,Checker,ResearchBridge,
                                       FoldError,canonical,decode,sha,identity,generation_packet)
from headroom_recursion.folding.types import data,bounded_difference_summary


def toy_run(artifact,case):
    a=decode(artifact)
    loss=a['loss']
    return {'loss':loss,'cost':1,'output':{'unit':case['u'],'answer':'checked'}}


def toy_check(case,out):
    return out=={'unit':case['u'],'answer':'checked'}


class FoldingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=Store(Path(self.tmp.name)/'db')
        self.ev=Evaluator(sha(b'toy-evaluator-v1'),toy_run,toy_check)
        self.policy=Policy('test','test bounded metric','declared loss','synthetic independent toy units',
                           self.ev.code_hash,premise_units=2,screen_units=20,validation_units=48,holdout_units=48)
        self.units={p:[{'u':i+start}for i in range(n)]for p,start,n in
                    [('screen',0,20),('validation',100,48),('holdout',200,48)]}
        self.f=Folding.create(self.store,self.policy,canonical({'loss':1}),self.units,self.ev)
    def tearDown(self):
        self.store.close();self.tmp.cleanup()
    def candidate(self,loss=0,name='better',**kw):
        return self.f.freeze(Proposal(name,self.f.state['champion'],self.store.put_json({'loss':loss}),
                   'one declared intervention','reduce declared bounded loss','no checked reduction','deterministic',**kw))
    def stage(self,c,through='holdout'):
        out=[]
        for p in ('premise','screen','validation','holdout'):
            out.append(self.f.evaluate(c,p))
            if p==through:break
        return out
    def test_strict_json(self):
        for raw in ['{"x":1,"x":2}','{"x":NaN}','{"x":Infinity}','{"x":1e999}']:
            with self.subTest(raw=raw),self.assertRaises(FoldError):decode(raw)
    def test_policy_types(self):
        bad={'alpha':[float('nan'),float('inf'),True,0],'screen_units':[0,-1,False,2.5],
             'evaluator_hash':['abc','G'*64],'schema_version':[2,True],'objective':['',None]}
        for k,values in bad.items():
            for v in values:
                with self.subTest(k=k,v=v),self.assertRaises(FoldError):Policy.parse({**data(self.policy),k:v})
    def test_policy_unknown_fields(self):
        with self.assertRaises(FoldError):Policy.parse({**data(self.policy),'approved':True})
    def test_proposal_cannot_carry_authority(self):
        obj=data(Proposal('x',self.f.state['champion'],sha(b'x'),'m','p','f','unbiased'))
        for key in ['status','holdout_outcomes','primary_effect','ci_upper','promoted']:
            with self.subTest(key=key),self.assertRaises(FoldError):Proposal.parse({**obj,key:'x'})
    def test_artifact_must_exist(self):
        with self.assertRaises(FoldError):self.f.freeze(Proposal('x',self.f.state['champion'],sha(b'absent'),'m','p','f','b'))
    def test_stale_parent(self):
        with self.assertRaises(FoldError):self.f.freeze(Proposal('x',sha(b'wrong'),self.store.put_json({'loss':0}),'m','p','f','b'))
    def test_same_artifact_cannot_be_renamed(self):
        self.candidate()
        with self.assertRaises(FoldError):self.candidate(name='renamed')
    def test_overlap(self):
        bad=copy.deepcopy(self.units);bad['holdout'][0]=bad['screen'][0]
        with self.assertRaises(FoldError):Folding.create(self.store,dataclasses.replace(self.policy,scope='other'),b'parent',bad,self.ev)
    def test_cross_campaign_confirmation_reuse(self):
        with self.assertRaises(FoldError):Folding.create(self.store,dataclasses.replace(self.policy,scope='other'),b'parent',self.units,self.ev)
    def test_evaluator_binding(self):
        with self.assertRaises(FoldError):Folding(self.store,'test',Evaluator(sha(b'wrong'),toy_run,toy_check))
    def test_no_stage_skipping(self):
        c=self.candidate()
        for p in ['screen','validation','holdout']:
            with self.subTest(p=p),self.assertRaises(FoldError):self.f.evaluate(c,p)
        with self.assertRaises(FoldError):self.f.promote(c)
    def test_paired_complete_promotion(self):
        c=self.candidate();receipts=self.stage(c)
        a=self.f.promote(c)
        self.assertEqual(self.f.admission(a)['kind'],'empirical-promotion')
        self.assertEqual(self.f.state['champion'],self.store.json(c)['artifact'])
        self.assertEqual(len(self.f.state['previous_champions']),1)
        self.assertTrue(all(r['passed'] for r in receipts))
        self.store.audit()
    def test_no_repeat_or_double_promotion(self):
        c=self.candidate();self.stage(c);self.f.promote(c)
        for fn in [lambda:self.f.promote(c),lambda:self.f.evaluate(c,'holdout'),lambda:self.candidate(.2,'new')]:
            with self.assertRaises(FoldError):fn()
    def test_restart_does_not_restore_holdout(self):
        c=self.candidate();self.stage(c)
        self.store.close();self.store=Store(Path(self.tmp.name)/'db');self.f=Folding(self.store,'test',self.ev)
        with self.assertRaises(FoldError):self.f.evaluate(c,'holdout')
        self.f.promote(c)
    def test_generation_closes_at_validation(self):
        c=self.candidate();self.stage(c,'validation')
        for fn in [lambda:self.candidate(.2),lambda:generation_packet(self.f,c),
                   lambda:self.f.remember(c,summary='s',preserved='p',next_test='n')]:
            with self.assertRaises(FoldError):fn()
    def test_neutral_candidate_cannot_promote(self):
        c=self.candidate(.9);self.stage(c,'screen');r=self.f.evaluate(c,'validation')
        self.assertFalse(r['passed'])
        with self.assertRaises(FoldError):self.f.evaluate(c,'holdout')
        self.assertEqual(self.f.state['champion'],self.f.state['origin'])
    def test_invalid_numeric_measurements_kill_not_crash(self):
        def run(a,c):return {'loss':float('nan'),'cost':0,'output':{}}
        self.f.evaluator=Evaluator(self.ev.code_hash,run,toy_check)
        c=self.candidate();r=self.f.evaluate(c,'premise')
        self.assertFalse(r['passed']);self.assertGreater(r['summary']['failures'],0)
    def test_false_checker_kills(self):
        self.f.evaluator=Evaluator(self.ev.code_hash,toy_run,lambda c,o:False)
        c=self.candidate();self.assertFalse(self.f.evaluate(c,'premise')['passed'])
    def test_truthy_checker_does_not_pass(self):
        self.f.evaluator=Evaluator(self.ev.code_hash,toy_run,lambda c,o:'yes')
        c=self.candidate();self.assertFalse(self.f.evaluate(c,'premise')['passed'])
    def test_resource_excess_kills(self):
        def run(a,c):return {'loss':0,'cost':self.policy.max_cost+1,'output':{'unit':c['u'],'answer':'checked'}}
        self.f.evaluator=Evaluator(self.ev.code_hash,run,toy_check)
        c=self.candidate();self.assertFalse(self.f.evaluate(c,'premise')['passed'])
    def test_holdout_crash_is_consumed(self):
        c=self.candidate();self.stage(c,'validation')
        def run(a,c):raise KeyboardInterrupt()
        self.f.evaluator=Evaluator(self.ev.code_hash,run,toy_check)
        with self.assertRaises(KeyboardInterrupt):self.f.evaluate(c,'holdout')
        self.assertTrue(self.f.state['holdout_spent'])
        self.assertEqual(self.f.state['candidates'][c]['receipts']['holdout']['status'],'aborted')
        with self.assertRaises(FoldError):self.f.evaluate(c,'holdout')
    def test_one_holdout_candidate_only(self):
        a=self.candidate(0,'a');b=self.candidate(.01,'b')
        self.stage(a,'screen');self.stage(b,'screen')
        self.f.evaluate(a,'validation');self.f.evaluate(b,'validation');self.f.evaluate(a,'holdout')
        with self.assertRaises(FoldError):self.f.evaluate(b,'holdout')
    def test_packet_no_unrestricted_evidence_lookup(self):
        c=self.candidate();self.stage(c,'screen')
        secret=self.store.put_json({'holdout_outcomes':'SYNTHETIC-SECRET'})
        p=generation_packet(self.f,c)
        self.assertNotIn('SYNTHETIC-SECRET',p.text)
        with self.assertRaises(FoldError):p.read(secret)
        self.assertEqual(decode(p.read(self.f.state['champion'])),{'loss':1})
    def test_memory_is_source_bound_and_budgeted(self):
        c=self.candidate(.99);self.stage(c,'screen')
        for i in range(40):self.f.remember(c,summary=f'failed mechanism {i} '+'x'*100,
                 preserved='exact premise',next_test='use a new observable')
        p=generation_packet(self.f,c,max_chars=4000,k=3)
        self.assertLessEqual(len(p.text),4000);self.assertLessEqual(len(decode(p.text)['memory']),3)
        self.assertEqual(len(self.f.state['memory']),40)
    def test_packet_fails_closed_not_truncated(self):
        c=self.candidate()
        with self.assertRaises(FoldError):generation_packet(self.f,c,max_chars=256)
    def test_selector_cannot_rewrite_or_expand(self):
        c=self.candidate(.99);self.stage(c,'screen');self.f.remember(c,summary='bad',preserved='part',next_test='fix')
        for selection in [[sha(b'unknown')],[{'rewritten':'entry'}]]:
            with self.subTest(selection=selection),self.assertRaises(FoldError):
                generation_packet(self.f,c,selector=lambda p,k,sel=selection:sel)
    def test_no_salvage_from_unexecuted_or_confirmation(self):
        c=self.candidate()
        with self.assertRaises(FoldError):self.f.remember(c,summary='s',preserved='p',next_test='n')
        self.stage(c,'validation')
        with self.assertRaises(FoldError):self.f.remember(c,summary='s',preserved='p',next_test='n')
    def test_finite_claim_exact_statement_binding(self):
        statement={'name':'finite','coverage':'finite','statement':'2+2=4 on this calculation','domain':'integers, one calculation'}
        ch=Checker(sha(b'checker'), 'finite',lambda s,e,d:s==statement and e==b'4')
        a=self.f.admit_claim(statement,b'4',ch)
        self.assertEqual(self.f.admission(a)['kind'],'checked-finite')
        with self.assertRaises(FoldError):self.f.admit_claim({**statement,'statement':'P=NP'},b'4',ch)
    def test_finite_cannot_be_formal(self):
        s={'name':'fake','coverage':'formal','statement':'P=NP','domain':'all languages'}
        with self.assertRaises(FoldError):self.f.admit_claim(s,b'finite tests',Checker(sha(b'c'),'finite',lambda *a:True))
    def test_claim_failure_and_error_fail_closed(self):
        s={'name':'x','coverage':'finite','statement':'x','domain':'one case'}
        def boom(*a):raise RuntimeError('broken checker')
        for cb in [lambda *a:False,lambda *a:1,boom]:
            with self.subTest(cb=cb),self.assertRaises(FoldError):self.f.admit_claim(s,b'x',Checker(sha(b'c'),'finite',cb))
    def test_claim_unknown_dependency(self):
        s={'name':'x','coverage':'finite','statement':'x','domain':'one case'}
        with self.assertRaises(FoldError):self.f.admit_claim(s,b'x',Checker(sha(b'c'),'finite',lambda *a:True),dependencies=(sha(b'missing'),))
    def test_corruption_detected(self):
        ref=self.f.state['origin']
        self.store.db.execute('UPDATE blobs SET body=? WHERE ref=?',(b'bad',ref))
        with self.assertRaises(FoldError):self.store.get(ref)
        with self.assertRaises(FoldError):self.store.audit()
    def test_holdout_registry_tamper_detected(self):
        self.store.db.execute('DELETE FROM units WHERE phase=?',('holdout',))
        with self.assertRaises(FoldError):self.store.audit()
    def test_unsupported_store_schema(self):
        import sqlite3
        from unittest.mock import patch
        self.store.db.execute("UPDATE metadata SET value='99' WHERE key='schema'")
        opened = []
        connect = sqlite3.connect
        def tracked_connect(*args, **kwargs):
            connection = connect(*args, **kwargs)
            opened.append(connection)
            return connection
        with patch('headroom_recursion.folding.store.sqlite3.connect', side_effect=tracked_connect):
            with self.assertRaises(FoldError):
                Store(Path(self.tmp.name)/'db')
        self.assertEqual(len(opened), 1)
        with self.assertRaises(sqlite3.ProgrammingError):
            opened[0].execute('SELECT 1')
    def test_composition_requires_all_four_arms(self):
        a=self.candidate(.3,'A');b=self.candidate(.4,'B');self.stage(a,'screen');self.stage(b,'screen')
        c=self.candidate(0,'AB',components=(a,b))
        with self.assertRaises(FoldError):self.f.evaluate(c,'premise')
        r=self.f.evaluate(c,'interaction')
        self.assertEqual(len(r['measurements'][0]['arms']),4)
        self.assertIn('factorial_interaction_mean',r['summary'])
        self.stage(c);self.f.promote(c)
    def test_composition_unvalidated_parent(self):
        a=self.candidate(.3,'A');b=self.candidate(.4,'B')
        with self.assertRaises(FoldError):self.candidate(0,'AB',components=(a,b))
    def test_hoeffding_recomputed_and_family_adjusted(self):
        c=self.candidate();r=self.f.evaluate(c,'premise')
        s=bounded_difference_summary(r['measurements'],self.policy)
        self.assertEqual(s,r['summary'])
        self.assertEqual(s['alpha_per_gate'],.05/16)
        bad=copy.deepcopy(r['measurements']);bad[0]['child']['loss']=False
        with self.assertRaises(FoldError):bounded_difference_summary(bad,self.policy)
    def test_same_file_two_controllers_no_double_promotion(self):
        c=self.candidate();self.stage(c)
        other=Store(Path(self.tmp.name)/'db');f2=Folding(other,'test',self.ev)
        try:
            self.f.promote(c)
            with self.assertRaises(FoldError):f2.promote(c)
        finally:other.close()
    def test_bridge_exact_append_and_no_judge_halt(self):
        s={'name':'finite','coverage':'finite','statement':'finite-only evidence','domain':'one case'}
        a=self.f.admit_claim(s,b'yes',Checker(sha(b'c'),'finite',lambda *args:True))
        bridge=ResearchBridge(self.f,'HISTORICAL EVIDENCE',(a,))
        goal=bridge.render((a,))
        class Client:
            def complete(inner,**kw):
                if kw['system'].startswith('Check correctness and completeness'):
                    return CallResult('{"halt_prob":1,"reason":"model says solved"}')
                obj=decode(kw['user']);role=obj['role']
                if role=='progress_seed':return CallResult('{"keep":[],"next_check":"test"}')
                if role=='notes':return CallResult('Visible notes. Finite evidence is not a theorem.')
                length=obj['sources']['candidate']['length']
                return CallResult(json.dumps({'workspace_patch':{'version':1,**{k:obj[k]for k in ['scope','ticket','base']},
                           'edits':[{'start':length,'end':length,'text':goal[length:]}]}}))
        cfg=bridge.bind(RecurseConfig(n=1,T=1,ladder=(Tier('test'),),max_total_calls=10))
        trace=recurse('Test external evidence admission, not P=NP.',client=Client(),config=cfg)
        self.assertFalse(trace.halted)
        self.assertEqual(trace.final_answer,goal)
    def test_bridge_rejects_forgery_and_missing_history(self):
        s={'name':'finite','coverage':'finite','statement':'finite only','domain':'one case'}
        a=self.f.admit_claim(s,b'yes',Checker(sha(b'c'),'finite',lambda *args:True))
        b=ResearchBridge(self.f,'ORIGINAL',(a,))
        self.assertFalse(b.valid(b.render((a,)).replace('finite only','P=NP')))
        self.assertFalse(b.valid(b.render((a,)).replace('ORIGINAL','edited')))
        self.assertTrue(b.contains(b.render((a,)),a));self.assertFalse(b.contains('ORIGINAL',a))

    def test_rollback_preserves_spent_holdout(self):
        c=self.candidate();self.stage(c);self.f.promote(c)
        origin=self.f.state['origin']
        self.f.rollback('Operator detected a deployment limitation outside the tested population.')
        self.assertEqual(self.f.state['champion'],origin)
        self.assertTrue(self.f.state['holdout_spent'])
        self.assertEqual(self.f.state['candidates'][c]['status'],'rolled-back')
        with self.assertRaises(FoldError):self.f.rollback('cannot restore twice')
        with self.assertRaises(FoldError):self.f.evaluate(c,'holdout')
    def test_evaluator_mismatch_does_not_create_campaign(self):
        ev=Evaluator(sha(b'wrong-evaluator'),toy_run,toy_check)
        with self.assertRaises(FoldError):Folding.create(self.store,dataclasses.replace(self.policy,scope='bad-evaluator'),b'base',self.units,ev)
        with self.assertRaises(FoldError):self.store.state('bad-evaluator')
    def test_extreme_numeric_inputs_fail_as_contract_errors(self):
        for value in [10**10000,-10**10000]:
            with self.assertRaises(FoldError):Policy.parse({**data(self.policy),'alpha':value})
        for value in [False,0,-2,'large']:
            with self.assertRaises(FoldError):Store(Path(self.tmp.name)/'bad',max_blob_bytes=value)
    def test_utf8_public_reads_are_exact(self):
        ref=self.store.put('xéλ'.encode())
        from headroom_recursion.folding.packet import Packet
        p=Packet('{}',{ref:self.store.get(ref)},max_read_bytes=10)
        self.assertEqual(p.read(ref,1,3),'é')
        with self.assertRaises(FoldError):p.read(ref,1,2)
        with self.assertRaises(FoldError):p.read(ref,True,3)
    def test_formal_claim_cannot_depend_on_finite_claim(self):
        statement={'name':'small','coverage':'finite','statement':'finite case','domain':'one case'}
        admitted=self.f.admit_claim(statement,b'case',Checker(sha(b'finite'),'finite',lambda *a:True))
        ref=self.f.admission(admitted)['claim_ref']
        formal={**statement,'coverage':'formal','statement':'all cases'}
        with self.assertRaises(FoldError):self.f.admit_claim(formal,b'proof',Checker(sha(b'formal'),'formal',lambda *a:True),dependencies=(ref,))
    def test_formal_verifier_registration_does_not_ship_a_kernel(self):
        # This is a toy verifier exercising a registration contract, not a formal proof test.
        s={'name':'toy-identity','coverage':'formal','statement':'operator exact toy statement','domain':'test registration only'}
        ch=Checker(sha(b'registered-toy'), 'formal',lambda obj,e,d:obj==s and e==b'exact' and not d)
        ref=self.f.admit_claim(s,b'exact',ch)
        self.assertEqual(self.f.admission(ref)['kind'],'checked-formal')
        with self.assertRaises(FoldError):self.f.admit_claim({**s,'statement':'P=NP'},b'exact',ch)
    def test_middle_factorial_arm_is_validated(self):
        from headroom_recursion.folding.types import interaction_summary
        a=self.candidate(.3,'A');b=self.candidate(.4,'B');self.stage(a,'screen');self.stage(b,'screen')
        c=self.candidate(0,'AB',components=(a,b));r=self.f.evaluate(c,'interaction')
        bad=copy.deepcopy(r['measurements']);bad[0]['arms'][1]['loss']=float('nan')
        with self.assertRaises(FoldError):interaction_summary(bad,self.policy)
        bad=copy.deepcopy(r['measurements']);bad[0]['arms'][2]['cost']=self.policy.max_cost+1
        self.assertEqual(interaction_summary(bad,self.policy)['all_arm_failures'],1)
    def test_factorial_promotion_recomputes_stored_receipt(self):
        a=self.candidate(.3,'A');b=self.candidate(.4,'B');self.stage(a,'screen');self.stage(b,'screen')
        c=self.candidate(0,'AB',components=(a,b));r=self.f.evaluate(c,'interaction');self.stage(c)
        altered=copy.deepcopy(r);altered['summary']['factorial_interaction_mean']=99
        ref=self.store.put_json(altered)
        # Deliberate trusted-store fault injection: promotion must still recompute.
        def inject(s):
            s['candidates'][c]['receipts']['interaction']['ref']=ref
            return None,{'synthetic_fault':True}
        self.store.update('test','test-only-fault',inject)
        with self.assertRaises(FoldError):self.f.promote(c)
    def test_memory_selector_observes_only_bounded_pool(self):
        c=self.candidate(.99);self.stage(c,'screen')
        for i in range(70):self.f.remember(c,summary=f'failure {i}',preserved='component',next_test='change mechanism')
        seen=[]
        def choose(pool,k):seen.extend(pool);return [x['id']for x in pool[:k]]
        result=generation_packet(self.f,c,k=2,max_chars=4000,selector=choose)
        self.assertEqual(len(seen),4)
        self.assertLessEqual(len(decode(result.text)['memory']),2)
        self.assertLessEqual(len(result.text),4000)
    def test_no_new_candidate_after_failed_validation(self):
        c=self.candidate(.95);self.stage(c,'screen');r=self.f.evaluate(c,'validation')
        self.assertFalse(r['passed'])
        with self.assertRaises(FoldError):self.candidate(0,'retuned-after-confirmation')

if __name__=='__main__':unittest.main()
