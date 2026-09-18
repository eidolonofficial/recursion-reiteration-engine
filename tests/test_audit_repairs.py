"""Tests inspect the final transmitted packet, never just internal ranges."""
import json
import unittest
from dataclasses import replace
from test_structured_output import Backend, config, SCHEMA
from headroom_recursion import prompts, recurse
from headroom_recursion.runtime import MeteredClient
from headroom_recursion.trace import RunTrace
from headroom_recursion.compression import ContextLimitError
from test_private_memory import Fixture, ObservationLedger

class FinalPacketTests(unittest.TestCase):
    def invoke(self,backend,original='EXACT original <= 7; NOT optional',cfg=None):
        cfg=cfg or config(preseed_ladder=False)
        trace=RunTrace(problem='task',current_answer=original)
        runtime=MeteredClient(backend,cfg,trace,None)
        result=runtime.complete_prompt(role='answer',model='test',system=prompts.ANSWER_SYSTEM,
            template=prompts.ANSWER_UPDATE,values=dict(problem='task',context='',scratchpad='',answer=original),
            max_tokens=128,temperature=0)
        return result,trace
    def test_original_is_visible_without_preseed_or_memory(self):
        original='ORIGINAL unique: x <= y; "quote"; \u03c0\nKeep NOT and spaces. '
        backend=Backend(lambda q:'{"selected":["A"]}')
        self.invoke(backend,original)
        packet=json.loads(backend.requests[0]['user'])
        self.assertEqual(packet['sources']['candidate']['excerpts'],[[0,original]])
        self.assertNotIn('blocks',packet)
        self.assertEqual(backend.requests[0]['user'].count('ORIGINAL unique'),1)
    def test_format_retry_delivers_current_feedback(self):
        def answer(q):
            return '{"selected":["A"]}' if json.loads(q['user']).get('feedback') else '```bad```'
        backend=Backend(answer)
        trace=recurse('Select A',client=backend,config=config(validator=lambda a:True,preseed_ladder=False))
        self.assertEqual(trace.stop_reason,'validated')
        self.assertEqual(trace.total_calls,2)
        self.assertEqual(len(trace.steps),1)
        self.assertIn('Output-channel failure',json.loads(backend.requests[1]['user'])['feedback'])
        self.assertNotEqual(backend.requests[0]['user'],backend.requests[1]['user'])
    def test_original_escaping_counts_toward_final_budget(self):
        backend=Backend(lambda q:'{"selected":["A"]}')
        cfg=config(preseed_ladder=False,token_counter=lambda text,model:len(text),token_counter_label='chars')
        cfg.workspace=replace(cfg.workspace,budget=1000)
        with self.assertRaises(ContextLimitError):self.invoke(backend,'"\\\n'*1000,cfg)
        self.assertEqual(backend.requests,[])
    def test_empty_original_is_explicit(self):
        backend=Backend(lambda q:'{"selected":["A"]}')
        self.invoke(backend,'')
        source=json.loads(backend.requests[0]['user'])['sources']['candidate']
        self.assertEqual(source['excerpts'],[]);self.assertEqual(source['length'],0)

class ObservationPacketTests(Fixture):
    def test_exact_observation_sent_once_without_losing_judge_pin(self):
        session=self.session();ledger=ObservationLedger(self.s,self.p)
        output='UNRESOLVED_EXACT_SENTINEL: check x <= 7, NOT x < 7'
        oid=ledger.record('test',output,status='failure',revision='r1',exit_code=1,failed_tests=1)
        cfg=config(memory_session=session,observation_ledger=ledger,preseed_ladder=False)
        backend=Backend(lambda q:'{"selected":["A"]}')
        trace=RunTrace(problem='task');runtime=MeteredClient(backend,cfg,trace,None)
        runtime.memory_context('task','');trace.feedback=output
        runtime.complete_prompt(role='answer',model='test',system=prompts.ANSWER_SYSTEM,
            template=prompts.ANSWER_UPDATE,values=dict(problem='task',context='',scratchpad='',answer=''),
            max_tokens=128,temperature=0)
        packet=json.loads(backend.requests[0]['user'])
        self.assertEqual(backend.requests[0]['user'].count('UNRESOLVED_EXACT_SENTINEL'),1)
        self.assertEqual(packet['feedback'],{'observation':oid,'revision':'r1','field':'exact_output'})
        self.assertTrue(any(output in p for p in runtime.memory_pins))
        self.assertEqual(ledger.view()['required_pins'],runtime.memory_pins)
        self.assertFalse(ledger.rows()[0]['resolved'])


class AmbiguousObservationTests(Fixture):
    def test_same_output_at_different_revisions_is_not_misattributed(self):
        session=self.session();ledger=ObservationLedger(self.s,self.p)
        output='same failed test text'
        for revision in ('r1','r2'):
            ledger.record('test',output,status='failure',revision=revision,exit_code=1,failed_tests=1)
        cfg=config(memory_session=session,observation_ledger=ledger,preseed_ladder=False)
        backend=Backend(lambda q:'{"selected":["A"]}')
        trace=RunTrace(problem='task');runtime=MeteredClient(backend,cfg,trace,None)
        runtime.memory_context('task','');trace.feedback=output
        runtime.complete_prompt(role='answer',model='test',system=prompts.ANSWER_SYSTEM,
            template=prompts.ANSWER_UPDATE,values=dict(problem='task',context='',scratchpad='',answer=''),
            max_tokens=128,temperature=0)
        packet=json.loads(backend.requests[0]['user'])
        self.assertEqual(packet['feedback'],output)
        self.assertEqual({r['revision'] for r in packet['observations']['observations']},{'r1','r2'})
    def test_request_contract_changes_checkpoint_policy(self):
        from headroom_recursion.checkpoint import policy
        self.assertEqual(policy(config())['request_contract'],'visible-payload-feedback-v2')

if __name__=='__main__':unittest.main()
