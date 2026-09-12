"""Schema transport and task correctness are separate, independently checked layers."""
import json
import unittest
from dataclasses import replace
from headroom_recursion import RecurseConfig, recurse
from headroom_recursion.clients import CallResult, TransportError
from headroom_recursion.response_schema import (schema_copy, parse_payload,
    UnsupportedStructuredOutput, InvalidStructuredOutput)
from headroom_recursion.progress import ProgressCheck
from test_efficiency import Capture

SCHEMA={'type':'object','properties':{'selected':{'type':'array','items':
    {'type':'string','enum':['A','B','C']},'maxItems':3}},
    'required':['selected'],'additionalProperties':False}

def config(**options):
    return RecurseConfig.structured(SCHEMA,model='test',workload='research',rungs=3,
        budget=16000,verification_id='schema-tests-v1',**options)

class Backend:
    def __init__(self, answer): self.answer=answer;self.requests=[];self.schemas=[]
    def check_schema(self, model, schema):
        self.schemas.append(schema_copy(schema));return True
    def complete(self, **request):
        self.requests.append(request)
        result=self.answer(request)
        return result if isinstance(result,CallResult) else CallResult(result)

class SchemaTests(unittest.TestCase):
    def test_narrow_payload(self):
        self.assertEqual(parse_payload('{"selected":["A"]}',SCHEMA),{'selected':['A']})
        for text in ('```json\n{"selected":["A"]}\n```','{"selected":["Z"]}',
                     '{"selected":["A"],"total":1}','{"selected":[],"selected":[]}',
                     '{"selected":[["A",1]]}','{"selected":["A","B","C","A"]}'):
            with self.subTest(text=text),self.assertRaises((InvalidStructuredOutput,ValueError)):
                parse_payload(text,SCHEMA)

    def test_unknown_features_fail_preflight(self):
        for key,value in (('uniqueItems',True),('$ref','#/anything'),('pattern','.*')):
            with self.subTest(key=key),self.assertRaises(UnsupportedStructuredOutput):
                schema_copy(dict(SCHEMA,**{key:value}))

    def test_legacy_backend_cannot_silently_ignore_schema(self):
        client=Capture()
        with self.assertRaises(UnsupportedStructuredOutput):
            recurse('task',client=client,config=config())
        self.assertEqual(client.requests,[])

    def test_host_validation_does_not_claim_uniqueness_from_schema(self):
        value=parse_payload('{"selected":["A","A"]}',SCHEMA)
        self.assertNotEqual(len(value['selected']),len(set(value['selected'])))

class IntegrationTests(unittest.TestCase):
    def test_payload_only_reaches_existing_validator(self):
        checked=[]
        backend=Backend(lambda q:'{"selected":["A"]}')
        cfg=config(validator=lambda a: checked.append(json.loads(a)) or True)
        trace=recurse('Select A',client=backend,config=cfg)
        self.assertEqual(trace.stop_reason,'validated')
        self.assertEqual(checked,[{'selected':['A']}])
        self.assertEqual(trace.total_calls,1)
        self.assertEqual(backend.requests[0]['response_schema'],SCHEMA)
        self.assertNotIn('blocks',json.loads(backend.requests[0]['user']))
        self.assertEqual(trace.current_scratchpad,'')

    def test_bad_format_retry_does_not_consume_reasoning_step(self):
        answers=iter(['```json\n{"selected":["A"]}\n```','{"selected":["A"]}'])
        backend=Backend(lambda q:next(answers))
        trace=recurse('Select A',client=backend,config=config(validator=lambda a:True))
        self.assertEqual(trace.stop_reason,'validated')
        self.assertEqual(trace.total_calls,2)
        self.assertEqual(len(trace.steps),1)

    def test_truncation_is_not_repaired_or_accepted(self):
        backend=Backend(lambda q:CallResult('{"selected":',stop_reason='length',usage={'total_tokens':9}))
        trace=recurse('Select',client=backend,config=config(validator=lambda a:self.fail('checker ran')))
        self.assertEqual(trace.stop_reason,'repeated-rejection')
        self.assertEqual(trace.steps,[])
        self.assertEqual(trace.final_answer,'')
        self.assertEqual(trace.call_events[0]['native_usage'],{'total_tokens':9})

    def test_best_feasible_candidate_is_retained_without_claiming_optimality(self):
        outputs=iter(['{"selected":["A"]}','{"selected":["B"]}','{"selected":["A"]}'])
        def objective(a): return {'A':1,'B':2,'C':3}[json.loads(a)['selected'][0]]
        cfg=config(validator=lambda a:False,objective=objective,
            progress_checks=(ProgressCheck('feasible','One label',lambda a:len(json.loads(a)['selected'])==1,required=True),))
        trace=recurse('Maximize score',client=Backend(lambda q:next(outputs)),config=cfg)
        self.assertEqual(json.loads(trace.final_answer),{'selected':['B']})
        self.assertEqual(trace.best_objective,2)
        self.assertFalse(trace.halted)
        self.assertEqual(trace.total_calls,3)
        self.assertTrue(all(s.judge_calls==0 for s in trace.steps))

    def test_set_identity_catches_permuted_rejections(self):
        outputs=iter(['{"selected":["A","B"]}','{"selected":["B","A"]}'])
        cfg=config(validator=lambda a:False,
            candidate_identity=lambda a:json.dumps(sorted(json.loads(a)['selected'])),
            progress_checks=(ProgressCheck('feasible','Reject these sets',lambda a:False,required=True),))
        trace=recurse('Select',client=Backend(lambda q:next(outputs)),config=cfg)
        self.assertEqual(trace.stop_reason,'repeated-rejection')
        self.assertEqual(trace.total_calls,2)

    def test_generation_refusal_records_usage_without_acceptance(self):
        backend=Backend(lambda q:CallResult('',stop_reason='refusal',usage={'total_tokens':5}))
        trace=recurse('Select',client=backend,config=config())
        self.assertEqual(trace.stop_reason,'repeated-rejection')
        self.assertEqual(trace.steps,[])
        self.assertEqual(trace.call_events[0]['native_usage'],{'total_tokens':5})

    def test_general_edits_keep_decoder_constrained_block_handles(self):
        def answer(q):
            packet=json.loads(q['user']);block=next(iter(packet['blocks']))
            return json.dumps({'action':'propose','block':block,'value':'DONE'})
        backend=Backend(answer)
        cfg=RecurseConfig.structured(model='frontier-adapter-contract-test',workload='research',
            validator=lambda a:a=='DONE')
        trace=recurse('Return DONE',client=backend,config=cfg)
        self.assertEqual(trace.stop_reason,'validated')
        self.assertEqual(trace.final_answer,'DONE')
        self.assertIsNotNone(backend.requests[0]['response_schema'])

    def test_newer_candidate_is_not_overwritten_by_late_response(self):
        from headroom_recursion.runtime import MeteredClient
        from headroom_recursion.trace import RunTrace
        from headroom_recursion import prompts
        cfg=config();trace=RunTrace(problem='Select',current_answer='{"selected":["B"]}')
        def answer(q):
            trace.current_answer='{"selected":["C"]}'
            return '{"selected":["A"]}'
        runtime=MeteredClient(Backend(answer),cfg,trace,None)
        with self.assertRaises(TransportError):
            runtime.complete_prompt(role='answer',model='test',system=prompts.ANSWER_SYSTEM,
                template=prompts.ANSWER_UPDATE,values=dict(problem='Select',context='',scratchpad='',answer=trace.current_answer),
                max_tokens=128,temperature=0)
        self.assertEqual(trace.current_answer,'{"selected":["C"]}')

    def test_payload_does_not_replace_an_unseen_large_candidate(self):
        from headroom_recursion.runtime import MeteredClient
        from headroom_recursion.trace import RunTrace
        from headroom_recursion.compression import ContextLimitError
        from headroom_recursion import prompts
        cfg=config();cfg.workspace=replace(cfg.workspace,budget=400)
        original='x'*10000;trace=RunTrace(problem='task',current_answer=original)
        backend=Backend(lambda q:'{"selected":["A"]}')
        runtime=MeteredClient(backend,cfg,trace,None)
        with self.assertRaises(ContextLimitError):
            runtime.complete_prompt(role='answer',model='test',system=prompts.ANSWER_SYSTEM,
                template=prompts.ANSWER_UPDATE,values=dict(problem='task',context='',scratchpad='',answer=original),
                max_tokens=128,temperature=0)
        self.assertEqual(backend.requests,[])
        self.assertEqual(trace.current_answer,original)

    def test_schema_contract_is_bound_to_checkpoint_policy(self):
        from headroom_recursion.checkpoint import policy,digest
        cfg=config();before=digest(policy(cfg))
        cfg.response_schema=json.loads(json.dumps(SCHEMA))
        cfg.response_schema['properties']['selected']['maxItems']=2
        self.assertNotEqual(before,digest(policy(cfg)))

class FinalBoundaryTests(unittest.TestCase):
    def test_invalid_enum_and_nonstring_property_fail_preflight(self):
        cases=[{'type':'integer','enum':[True]},
               {'type':'object','properties':{1:{'type':'string'}},'required':[],'additionalProperties':False}]
        for schema in cases:
            with self.subTest(schema=schema),self.assertRaises(UnsupportedStructuredOutput):
                schema_copy(schema)

    def test_cancelled_result_cannot_reach_checker(self):
        backend=Backend(lambda q:CallResult('{"selected":["A"]}',stop_reason='cancelled'))
        trace=recurse('Select',client=backend,config=config(validator=lambda a:self.fail('checker ran')))
        self.assertEqual(trace.stop_reason,'repeated-rejection')
        self.assertEqual(trace.steps,[])

    def test_resume_recomputes_feasible_objective_without_a_model_judge(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'checkpoint.json'
            calls=[0]
            def answer(q):
                calls[0]+=1
                if calls[0]==2: raise KeyboardInterrupt()
                return '{"selected":["A"]}'
            cfg=config(checkpoint_path=path,validator=lambda a:False,
                objective=lambda a:{'A':1,'B':2,'C':3}[json.loads(a)['selected'][0]],
                progress_checks=(ProgressCheck('feasible','One label',lambda a:len(json.loads(a)['selected'])==1,required=True),))
            first=recurse('Task',client=Backend(answer),config=cfg)
            self.assertEqual(first.stop_reason,'interrupted')
            second=recurse('Task',client=Backend(lambda q:'{"selected":["B"]}'),config=replace(cfg,resume_from=path))
            self.assertEqual(json.loads(second.final_answer),{'selected':['B']})
            self.assertEqual(second.best_objective,2)
            self.assertFalse(second.halted)

    def test_legacy_client_still_accepts_unstructured_calls(self):
        client=Capture(lambda q:'DONE')
        cfg=RecurseConfig(n=0,T=1,preseed_ladder=False,validator=lambda a:a=='DONE')
        self.assertEqual(recurse('Task',client=client,config=cfg).stop_reason,'validated')
        self.assertNotIn('response_schema',client.requests[0])

if __name__=='__main__':unittest.main()
