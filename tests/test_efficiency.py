"""Compact protocol invariants and actual-call accounting; no inference needed."""
from __future__ import annotations
import copy
import json
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from headroom_recursion import RecurseConfig, Tier, WorkspacePolicy, recurse
from headroom_recursion import checkpoint, halting, prompts
from headroom_recursion.clients import CallResult, TransportError
from headroom_recursion.compression import ContextLimitError
from headroom_recursion.progress import ProgressCheck
from headroom_recursion.runtime import BudgetExhausted, MeteredClient
from headroom_recursion.trace import RunTrace
from headroom_recursion.workspace import build_view, encode


class Capture:
    def __init__(self, fn=None):
        self.requests = []
        self.fn = fn or (lambda request: '{"halt_prob":0.2,"reason":"fixture"}')
    def complete(self, **request):
        self.requests.append(request)
        out = self.fn(request)
        return out if isinstance(out, CallResult) else CallResult(out)


def runtime(**overrides):
    c = RecurseConfig.efficient(n=1, T=1, token_counter=lambda t, m: len(t),
        token_counter_label="Unicode characters", **overrides)
    c.validate()
    return MeteredClient(Capture(), c, RunTrace(problem="task"), None)


def view(text="α=β🙂\n" * 2000, **policy):
    r = runtime()
    r.cfg.workspace = WorkspacePolicy(budget=5000, compact=True, chunk_chars=300,
                                      max_optional_chunks=2, **policy)
    v = build_view(r, role="answer", model="local", system="refine",
                   values=dict(problem="Improve the last claim", answer=text, scratchpad="next check", context=""))
    return r, v


def delta(v, rows, ticket=None):
    return encode({"patch": {"ticket": ticket or v.packet["ticket"], "edits": rows}})


def judge(r, **updates):
    args = dict(model="local", problem="task", answer="answer", scratchpad="notes",
                max_tokens=100, use_headroom=False, votes=1)
    args.update(updates)
    return halting.judge(r, **args)


class CompactTests(unittest.TestCase):
    def test_wire_contains_no_full_hash_except_ticket(self):
        r, v = view(); p = json.loads(v.render())
        self.assertEqual(p['schema'], 'workspace-v2')
        self.assertNotIn('base', p); self.assertNotIn('scope', p)
        self.assertNotIn(v.base, v.render())
        self.assertEqual(p['sources']['candidate']['id'], 's0')
        self.assertLessEqual(len(v.system) + len(v.render()), 5000)
    def test_exact_unicode_excerpts(self):
        r, v = view()
        for name, source in json.loads(v.render())['sources'].items():
            for a, text in source['excerpts']:
                self.assertEqual(text, v.texts[name][a:a+len(text)])
    def test_compact_versus_readable_same_selected_data_smaller(self):
        r, v = view('short statement')
        compact = len(v.render())
        v.policy = replace(v.policy, compact=False)
        self.assertLess(compact, len(v.render()))
    def test_noop_and_append_preserve_every_byte(self):
        r, v = view(); text = v.texts['candidate']; n = len(text)
        self.assertEqual(v.patch(delta(v, []), r.store), text)
        self.assertEqual(v.patch(delta(v, [[n, n, '\nnext']]), r.store), text+'\nnext')
    def test_unseen_edits_are_not_authorized_by_alias(self):
        r, v = view()
        with self.assertRaises(TransportError): v.patch(delta(v, [[0, 1, 'x']]), r.store)
    def test_batch_read_authorizes_exact_replacements(self):
        r, v = view(); n = v.texts['candidate']; alias = json.loads(v.render())['sources']['candidate']['id']
        rows = v.retrieve_batch([[alias, 10, 20], [alias, 50, 60]], r.store, 50)
        self.assertEqual([x['id'] for x in rows], [v.base, v.base])
        self.assertEqual(v.patch(delta(v, [[10, 20, 'A'], [50, 60, 'B']]), r.store),
                         n[:10]+'A'+n[20:50]+'B'+n[60:])
    def test_batch_read_is_atomic_on_failure(self):
        r, v = view(); old = copy.deepcopy((v.ranges, v.mandatory))
        with self.assertRaises(TransportError):
            v.retrieve_batch([['s0', 10, 20], ['s0', 50000, 50001]], r.store, 100)
        self.assertEqual((v.ranges, v.mandatory), old)
    def test_batch_sum_not_just_individual_read_is_bounded(self):
        r, v = view()
        with self.assertRaises(TransportError):
            v.retrieve_batch([['s0', 10, 30], ['s0', 50, 70]], r.store, 30)
    def test_batch_duplicate_and_unknown_alias_rejected(self):
        for rows in ([['s0',0,1],['s0',0,1]], [['s20',0,1]], [], [['s0',True,2]], [['s0',0,0]]):
            r,v=view()
            with self.subTest(rows=rows),self.assertRaises(TransportError):v.retrieve_batch(rows,r.store,100)
    def test_full_hash_has_no_compact_lookup_capability(self):
        r,v=view()
        with self.assertRaises(TransportError):v.retrieve_batch([[v.base,0,1]],r.store,100)
    def test_same_alias_cannot_access_unoffered_record(self):
        r,v=view(); private=r.store.put('not offered')
        with self.assertRaises(TransportError):v.retrieve_batch([[private,0,1]],r.store,100)
    def test_stale_cross_scope_and_other_candidate_tickets_rejected(self):
        r,v=view('abcdef'); r2,v2=view('changed')
        with self.assertRaises(TransportError):v.patch(delta(v,[],ticket=v2.packet['ticket']),r.store)
        r.cfg.memory_scope='other'; v2=build_view(r,role='answer',model='local',system='refine',values=dict(answer='abcdef',problem='task'))
        with self.assertRaises(TransportError):v.patch(delta(v,[],ticket=v2.packet['ticket']),r.store)
    def test_malformed_edit_matrix_fails_closed(self):
        bad=([[True,1,'']], [[0,2,None]], [[3,4,''],[0,1,'']], [[0,3,''],[2,4,'']],
             [[0,0,'a'],[0,0,'b']], [[-1,0,'']], [[0,99999,'']], [{}])
        for rows in bad:
            r,v=view('abcdef')
            with self.subTest(rows=rows),self.assertRaises(TransportError):v.patch(delta(v,rows),r.store)
    def test_authority_fields_and_plain_summary_rejected(self):
        r,v=view('text')
        for s in ('summary', '{"patch":{},"verified":true}',
                  encode({'patch':{'ticket':v.packet['ticket'],'edits':[],'verified':True}}),
                  '{"patch":{},"patch":{}}'):
            with self.subTest(s=s),self.assertRaises(TransportError):v.patch(s,r.store)
    def test_dependency_closure_survives_compact_mode(self):
        r,v=view('CLAIM\n'+'z'*10000+'\nASSUMPTION',required_passages=('CLAIM',),dependencies=(('CLAIM','ASSUMPTION'),))
        wire=v.render();self.assertIn('CLAIM',wire);self.assertIn('ASSUMPTION',wire)
        with self.assertRaises(ContextLimitError):v.patch(delta(v,[[0,5,'removed']]),r.store)
    def test_corrupt_archive_rejected(self):
        r,v=view();r.store.records[v.base]='wrong'
        with self.assertRaises(TransportError):v.patch(delta(v,[]),r.store)
        with self.assertRaises(TransportError):v.retrieve_batch([['s0',0,1]],r.store,100)
    def test_extra_large_required_input_stops_not_truncates(self):
        with self.assertRaises(ContextLimitError):view('x'*10000,required_passages=('x'*10000,))
    def test_optional_chunk_cap_does_not_limit_pins(self):
        r=runtime();r.cfg.workspace=WorkspacePolicy(compact=True,max_optional_chunks=0,required_passages=('PIN',))
        v=build_view(r,role='answer',model='local',system='s',values=dict(answer='PIN more text',problem='task'))
        self.assertIn('PIN',v.render()); self.assertNotIn('more text',v.render())
    def test_policy_validation_and_resume_fingerprint(self):
        for kw in ({'compact':1},{'max_optional_chunks':True},{'max_optional_chunks':-1},{'max_reads_per_round':0}):
            with self.subTest(kw=kw),self.assertRaises(ValueError):WorkspacePolicy(**kw).validate()
        r=runtime(); old=checkpoint.policy(r.cfg);r.cfg.progress_seed_mode='model'
        self.assertNotEqual(old,checkpoint.policy(r.cfg))
        r=runtime();old=checkpoint.policy(r.cfg);r.cfg.reuse_exact_judgments=False
        self.assertNotEqual(old,checkpoint.policy(r.cfg))


class JudgeReuseTests(unittest.TestCase):
    def test_identical_single_judge_reuses_snapshot_without_call_charge(self):
        r=runtime();a=judge(r);b=judge(r)
        self.assertEqual(a.halt_prob,b.halt_prob);self.assertEqual(b.calls,0)
        self.assertEqual(r.trace.total_calls,1)
        self.assertEqual(r.trace.progress_events[-1]['event'],'exact-judge-reuse')
    def test_new_answer_notes_model_and_budget_invalidate(self):
        r=runtime();judge(r)
        for kw in ({'answer':'answer '},{'scratchpad':'new'},{'model':'other'},{'max_tokens':101},{'problem':'new'}):judge(r,**kw)
        self.assertEqual(r.trace.total_calls,6)
    def test_pins_obligations_and_verifier_invalidate(self):
        r=runtime();judge(r);r.cfg.pinned_notes=('pin',);judge(r)
        r.cfg.verification_id='changed';judge(r)
        r.guard.checks=(ProgressCheck('c','check',lambda t:True),);judge(r)
        r.guard.locked.add('c');judge(r)
        self.assertEqual(r.trace.total_calls,5)
    def test_multi_votes_never_reuse(self):
        r=runtime();judge(r,votes=3);judge(r,votes=3)
        self.assertEqual(r.trace.total_calls,6)
        self.assertFalse(r.judgment_cache)
    def test_invalid_and_truncated_replies_not_cached(self):
        for value in ('NaN', '{"halt_prob":true}', CallResult('{"halt_prob":1}',stop_reason='length')):
            r=runtime();r.client=Capture(lambda request:value)
            judge(r);judge(r);self.assertEqual(r.trace.total_calls,4);self.assertFalse(r.judgment_cache)
    def test_compressed_judge_not_cached(self):
        r=runtime();judge(r,use_headroom=True);judge(r,use_headroom=True)
        self.assertEqual(r.trace.total_calls,2)
    def test_budget_applies_before_reuse(self):
        r=runtime(max_total_calls=1);judge(r)
        with self.assertRaises(BudgetExhausted):judge(r)
    def test_cache_is_not_cross_run(self):
        a=runtime();judge(a);b=runtime();judge(b)
        self.assertEqual(b.trace.total_calls,1);self.assertFalse(b.trace.progress_events)
    def test_cache_entry_and_retained_text_caps(self):
        r=runtime()
        for i in range(20):judge(r,answer=str(i))
        self.assertLessEqual(len(r.judgment_cache),16)
        judge(r,answer='q'*1_000_001)
        self.assertFalse(any('q'*1_000_001 in k for k in r.judgment_cache))
        r=runtime();r.cfg.pinned_notes=('p'*1_000_001,)
        judge(r);self.assertFalse(r.judgment_cache)
    def test_disabled_reuse_always_calls(self):
        r=runtime(reuse_exact_judgments=False);judge(r);judge(r)
        self.assertEqual(r.trace.total_calls,2)


class ExecutionTests(unittest.TestCase):
    def test_actual_controller_compact_batch_read_patch_and_local_seed(self):
        counter={'reads':False}; seen=[]; original='KEEP\n'+'abcdef'*500
        def fn(q):
            seen.append(q)
            if q['system']==prompts.HALT_SYSTEM:return '{"halt_prob":0.2,"reason":"fixture"}'
            p=json.loads(q['user'])
            if p['role']=='notes':return 'visible public progress'
            if not counter['reads']:
                counter['reads']=True
                return encode({'read':[['s0',6,9],['s0',18,21]]})
            return encode({'patch':{'ticket':p['ticket'],'edits':[[6,9,'X'],[18,21,'Y']]}})
        cfg=RecurseConfig.efficient(n=1,T=1,seed_answer=original,seed_scratchpad='previous work',
             judge_can_halt=False, max_total_calls=10,token_counter=lambda t,m:len(t),
             workspace=WorkspacePolicy(compact=True,budget=6000,chunk_chars=100,max_optional_chunks=1),
             progress_checks=(ProgressCheck('pin','preserve KEEP',lambda t:t.startswith('KEEP'),True),))
        trace=recurse('edit the test',client=Capture(fn),config=cfg)
        expected=original[:6]+'X'+original[9:18]+'Y'+original[21:]
        self.assertEqual(trace.final_answer,expected)
        self.assertEqual(trace.total_calls,5)
        self.assertFalse(any(x['role']=='progress_seed' for x in trace.call_events))
        self.assertEqual(len([x for x in trace.call_events if x['role']=='workspace_retrieval']),1)
        self.assertEqual(trace.locked_checks,['pin'])
        self.assertIn(original, seen[0]['user'])
        self.assertIn(expected, seen[-1]['user'])
    def test_efficient_overrides_preserve_operator_choice(self):
        cfg=RecurseConfig.efficient(n=7,progress_seed_mode='model',reuse_exact_judgments=False)
        self.assertEqual(cfg.n,7);self.assertEqual(cfg.progress_seed_mode,'model');self.assertFalse(cfg.reuse_exact_judgments)
    def test_sqlite_failed_constructor_closes_its_connection(self):
        from headroom_recursion.folding.store import Store
        closed=[]
        class Tracked(sqlite3.Connection):
            def close(self):closed.append(True);super().close()
        connect=sqlite3.connect
        def factory(*a,**kw):return connect(*a,**kw,factory=Tracked)
        with tempfile.TemporaryDirectory() as directory, patch('headroom_recursion.folding.store.sqlite3.connect',factory):
            with patch.object(Store,'audit',side_effect=ValueError('intentional failure')):
                with self.assertRaises(ValueError):Store(directory)
            self.assertEqual(closed,[True])
            Path(directory,'fold.sqlite3').unlink()


if __name__=='__main__':unittest.main()
