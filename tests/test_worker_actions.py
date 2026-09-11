"""Regressions for one-action workers, exact host checks and bounded failures."""
import json
import tempfile
import unittest
from pathlib import Path
from dataclasses import replace
from headroom_recursion import RecurseConfig, Tier, recurse, prompts
from headroom_recursion.clients import CallResult, TransportError
from headroom_recursion.worker_actions import checked_notes, parse_action, apply_action
from headroom_recursion.progress import ProgressCheck
from headroom_recursion.runtime import MeteredClient
from headroom_recursion.trace import RunTrace
from headroom_recursion.workspace import build_view
from test_efficiency import Capture


def proposal(packet, value):
    return json.dumps({'action':'propose','block':next(iter(packet['blocks'])),'value':value})


def config(**kw):
    values=dict(model='test-small', workload='research', rungs=6, budget=10000,
                token_counter=lambda t,m:len(t), token_counter_label='characters',
                verification_id='worker-boundary-tests-v1', max_total_calls=30)
    values.update(kw)
    return RecurseConfig.simple(**values)


class ActionParsingTests(unittest.TestCase):
    def test_valid_note_and_proposal(self):
        self.assertEqual(parse_action('{"action":"note","text":"Keep the assumption."}','notes')['text'],'Keep the assumption.')
        self.assertEqual(parse_action('{"action":"propose","block":"b1","value":{"selected":["A"]}}','answer')['value'],{'selected':['A']})

    def test_combined_unknown_wrong_role_and_extra_fields(self):
        cases=[('{}','notes'), ('[]','notes'), ('{"action":"unknown"}','notes'),
               ('{"action":"note","text":"ok","read":[]}','notes'),
               ('{"action":"note","text":"ok"}','answer'),
               ('{"action":"read","source":"s0","page":true}','notes'),
               ('{"action":"read","source":"s0","page":-1}','notes'),
               ('{"action":"note","action":"note","text":"x"}','notes'),
               ('{"action":"note","text":"x"} {}','notes')]
        for text,role in cases:
            with self.subTest(text=text),self.assertRaises(TransportError):parse_action(text,role)

    def test_note_cannot_wrap_a_command(self):
        text=json.dumps({'action':'note','text':'{"read": []}'})
        with self.assertRaises(TransportError):parse_action(text,'notes')

    def test_malformed_command_notes_are_not_prose(self):
        for text in ['{"read":[[{"alias":"s0"}]}', '{"read":[],"find":[]}', '```json\n{"find": [\n```']:
            with self.subTest(text=text),self.assertRaises(TransportError):checked_notes(text)
        for text in ['Use x<=y, not x<y.', 'Example request: {"read":[]}', '{"lemma":"not proved"}']:
            self.assertEqual(checked_notes(text),text)


class WorkerControlTests(unittest.TestCase):
    def test_one_proposal_no_note_or_judge_calls_when_host_validates(self):
        for model in ('tiny-local', 'frontier-operator-choice'):
            client=Capture(lambda q:proposal(json.loads(q['user']),{'selected':['A']}))
            trace=recurse('Return A',client=client,config=config(model=model,validator=lambda a:json.loads(a)=={'selected':['A']}))
            self.assertEqual(trace.stop_reason,'validated');self.assertEqual(trace.total_calls,1)
            self.assertEqual(json.loads(trace.final_answer),{'selected':['A']})
            self.assertEqual(len(client.requests),1)

    def test_same_rejected_candidate_stops_across_rungs(self):
        client=Capture(lambda q:proposal(json.loads(q['user']),{'selected':['invalid']}))
        check=ProgressCheck('valid','Only valid candidates',lambda a:False,required=True)
        trace=recurse('Find a valid candidate',client=client,config=config(progress_checks=(check,)))
        self.assertEqual(trace.stop_reason,'repeated-rejection');self.assertEqual(trace.total_calls,2)
        self.assertFalse(trace.halted);self.assertEqual(trace.final_answer,'')
        self.assertEqual(len(trace.steps),2);self.assertFalse(any(s.converged for s in trace.steps))
        self.assertTrue(all(s.judge_calls==0 for s in trace.steps))

    def test_host_feedback_survives_handoff_without_polluting_notes(self):
        packets=[]
        def worker(q):
            packet=json.loads(q['user']);packets.append(packet)
            return proposal(packet,'GOOD' if packet.get('feedback') else 'BAD')
        check=ProgressCheck('valid','GOOD only',lambda a:a=='GOOD',required=True)
        cfg=config(progress_checks=(check,),validator=lambda a:a=='GOOD',feedback=lambda a:'cost=36 > limit=24; reduce selection')
        trace=recurse('Obey the exact checks',client=Capture(worker),config=cfg)
        self.assertEqual(trace.stop_reason,'validated');self.assertEqual(trace.total_calls,2)
        self.assertIn('cost=36',packets[1]['feedback'])
        self.assertNotIn('cost=36',trace.best_scratchpad)

    def test_legacy_malformed_notes_never_become_working_state(self):
        malformed='{"read":[[{"alias":"s0"}]}'
        client=Capture(lambda q:malformed)
        cfg=config(n=2,seed_scratchpad='Retain this exact assumption.')
        cfg.workspace=replace(cfg.workspace,typed_actions=False)
        trace=recurse('A task',client=client,config=cfg)
        self.assertEqual(trace.stop_reason,'repeated-rejection')
        self.assertEqual(trace.current_scratchpad,'Retain this exact assumption.')
        self.assertEqual(trace.steps,[]);self.assertEqual(trace.total_calls,2)

    def test_stale_block_and_combined_actions_cannot_mutate_candidate(self):
        for output in ['{"action":"propose","block":"stale","value":"changed"}',
                       '{"action":"note","text":"ok","read":[]}']:
            cfg=config(seed_answer='KEEP',oracle_sufficient=False,validator=lambda a:a=='KEEP')
            def worker(q):
                return '{"halt_prob":0.2,"reason":"fixture"}' if q['system']==prompts.HALT_SYSTEM else output
            trace=recurse('Keep the accepted candidate',client=Capture(worker),config=cfg)
            self.assertEqual(trace.stop_reason,'repeated-rejection')
            self.assertEqual(trace.final_answer,'KEEP');self.assertFalse(trace.halted)

    def test_failed_host_checker_cannot_be_replaced_by_model_approval(self):
        def failed(a):raise ValueError('checker unavailable')
        client=Capture(lambda q:proposal(json.loads(q['user']),'unverified'))
        trace=recurse('Verify before accepting',client=client,config=config(validator=failed))
        self.assertFalse(trace.halted);self.assertEqual(trace.final_answer,'')
        self.assertEqual(trace.stop_reason,'repeated-rejection')
        self.assertTrue(all(s.judge_calls==0 for s in trace.steps))

    def test_rejection_count_survives_checkpoint_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'checkpoint.json';calls=[0]
            def worker(q):
                calls[0]+=1
                if calls[0]==2:raise KeyboardInterrupt()
                return proposal(json.loads(q['user']),'BAD')
            check=ProgressCheck('valid','Never admit BAD',lambda a:a!='BAD',required=True)
            cfg=config(checkpoint_path=path,progress_checks=(check,))
            first=recurse('A task',client=Capture(worker),config=cfg)
            self.assertEqual(first.stop_reason,'interrupted')
            second=recurse('A task',client=Capture(lambda q:proposal(json.loads(q['user']),'BAD')),
                           config=replace(cfg,resume_from=path))
            self.assertEqual(second.stop_reason,'repeated-rejection');self.assertEqual(second.total_calls,3)
            blocked=Capture()
            third=recurse('A task',client=blocked,config=replace(cfg,resume_from=path))
            self.assertEqual(third.stop_reason,'repeated-rejection');self.assertEqual(blocked.requests,[])

    def test_truncated_typed_action_never_commits(self):
        def worker(q):return CallResult(proposal(json.loads(q['user']),'unverified'),stop_reason='length')
        trace=recurse('A task',client=Capture(worker),config=config())
        self.assertEqual(trace.final_answer,'');self.assertFalse(trace.halted)
        self.assertEqual(trace.stop_reason,'repeated-rejection')


class ActionSourceTests(unittest.TestCase):
    def view(self, candidate, **policy):
        cfg=config();cfg.workspace=replace(cfg.workspace,**policy)
        runtime=MeteredClient(Capture(),cfg,RunTrace(problem='task'),None)
        runtime.trace.current_answer=candidate
        view=build_view(runtime,role='answer',model='test-small',system='sys',
                        values={'problem':'task','answer':candidate})
        return runtime,view

    def test_host_resolves_blocks_without_model_offset_arithmetic(self):
        runtime,view=self.view('original')
        packet=json.loads(view.render())
        action=parse_action(proposal(packet,'replacement'),'answer')
        self.assertEqual(apply_action(view,action,runtime.store,1000),'replacement')
        self.assertNotIn('ticket',packet)

    def test_partial_block_does_not_authorize_whole_candidate_replacement(self):
        runtime,view=self.view('a'*3000,chunk_chars=128,max_optional_chunks=1)
        packet=json.loads(view.render());key=next(iter(packet['blocks']))
        with self.assertRaises(TransportError):
            apply_action(view,{'action':'propose','block':key,'value':{'whole':'not seen'}},runtime.store,1000)

    def test_read_page_is_resolved_by_python_and_unknown_source_is_rejected(self):
        runtime,view=self.view('x'*400+'EXACT'+'y'*400,chunk_chars=128,max_optional_chunks=0)
        apply_action(view,{'action':'read','source':'s0','page':3},runtime.store,1000)
        self.assertIn('EXACT',view.render())
        with self.assertRaises(TransportError):
            apply_action(view,{'action':'read','source':'not-offered','page':0},runtime.store,1000)



class RetryIdentityTests(unittest.TestCase):
    def test_protocol_failure_is_limited_even_when_request_handles_change(self):
        def worker(q):
            return CallResult(proposal(json.loads(q['user']), 'partial'), stop_reason='length')
        trace = recurse('Return a complete action', client=Capture(worker), config=config())
        self.assertEqual(trace.stop_reason, 'repeated-rejection')
        self.assertEqual(trace.total_calls, 2)
        self.assertFalse(trace.halted)
        self.assertEqual(trace.final_answer, '')

    def test_framing_changes_do_not_reset_rejected_proposals(self):
        from headroom_recursion.worker_actions import rejection_key
        self.assertEqual(rejection_key('candidate','{ "n": 3 }'), rejection_key('candidate','{"n":3}'))
        self.assertNotEqual(rejection_key('candidate','{"n":3}'), rejection_key('candidate','{"n":4}'))

    def test_decoded_control_keys_cannot_be_notes(self):
        text = '{"' + '\\u0072' + 'ead": []}'
        with self.assertRaises(TransportError): checked_notes(text)

    def test_unavailable_seed_checker_does_not_invoke_model_judge(self):
        def failed(answer): raise OSError('unavailable')
        client = Capture()
        trace = recurse('Keep the seed unverified', client=client,
                        config=config(seed_answer='UNVERIFIED', validator=failed))
        self.assertEqual(trace.stop_reason, 'seed-unscored')
        self.assertFalse(trace.halted)
        self.assertEqual(client.requests, [])

if __name__ == '__main__': unittest.main()
