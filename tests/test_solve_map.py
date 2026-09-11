"""Exact fields, bounded dependency views, live bindings and lossless JSON."""
import json
import unittest
from dataclasses import replace
from test_private_memory import Fixture, E, CallResult, ContextLimitError
from test_efficiency import Capture
from headroom_recursion.solve_map import SolveMap, decode_ascii
from headroom_recursion.json_transport import compact_json
from headroom_recursion.memory import MemorySession
from headroom_recursion import RecurseConfig, WorkspacePolicy, recurse, prompts, checkpoint
from headroom_recursion.runtime import MeteredClient
from headroom_recursion.trace import RunTrace
from headroom_recursion.workspace import build_view

class SolveMapTests(Fixture):
    def graph(self):
        a=self.write('precondition','No certificate found is NOT an UNSAT proof.',pinned=True)
        b=self.write('experiment','Try codimension two; result remains uncertain.',dependencies=[a])
        c=self.write('next','Inspect the experiment under the exact precondition.',dependencies=[b])
        session=self.session()
        return session,SolveMap.search(session,'Inspect',k=2),[a,b,c]

    def test_existing_store_and_whole_dependency_closure(self):
        session,g,refs=self.graph()
        self.assertEqual(len(g.roots),2)
        self.assertEqual({r['id'] for r in g.records},set(refs))
        value=g.data({self.src:'s3'})
        self.assertEqual(value['needs'],[['n1','n0'],['n2','n1']])
        self.assertEqual(value['roots'],['n0','n2'])
        self.assertEqual(value['coverage'],'advisory')

    def test_ascii_roundtrip_retains_whole_fields(self):
        session,g,refs=self.graph();variants=g.variants({self.src:'s3'})
        self.assertTrue(variants['ascii'].isascii())
        self.assertEqual(decode_ascii(variants['ascii']),variants['json'])
        self.assertIn('NOT',variants['ascii']);self.assertNotIn(self.src,variants['ascii'])
        self.assertTrue(g.assert_fresh())

    def test_closure_budget_never_drops_dependency(self):
        session,g,refs=self.graph()
        with self.assertRaises(ContextLimitError):SolveMap.search(session,'Inspect',k=2,max_nodes=2)
        self.assertTrue(all(self.s.get(self.p,r) for r in refs))

    def test_other_principal_cannot_use_selection(self):
        session,g,refs=self.graph();other=MemorySession(self.s,self.other)
        with self.assertRaises(E):SolveMap(other,session.last_selection)
        self.assertEqual(SolveMap.search(other,'Inspect').records,())

    def test_dependency_update_invalidates_snapshot(self):
        session,g,refs=self.graph()
        self.write('experiment','Changed experiment.',expected=refs[1],dependencies=[refs[0]])
        with self.assertRaises(E):g.assert_fresh()

    def test_new_pin_between_selection_and_snapshot_is_not_hidden(self):
        session,g,refs=self.graph();selection=session.last_selection
        self.write('new-pin','New required restriction.',pinned=True)
        with self.assertRaises(E):SolveMap(session,selection)
        with self.assertRaises(E):g.assert_fresh()

    def test_unicode_controls_and_quotes_roundtrip(self):
        summary='Use '+chr(960)+'; x'+chr(8804)+'y does NOT imply x<y. '+chr(10)+'N is data. "quoted"'
        self.write('unicode',summary)
        g=SolveMap.search(self.session(),'unicode')
        self.assertEqual(decode_ascii(g.variants({self.src:'s0'})['ascii'])['nodes'][0][-1],summary)

    def test_wrong_source_aliases_rejected(self):
        session,g,refs=self.graph()
        for aliases in ({},{self.src:'not-an-alias'},{self.src:'s-1'}):
            with self.subTest(aliases=aliases),self.assertRaises(E):g.data(aliases)

    def test_duplicate_source_aliases_rejected(self):
        other=self.s.add_source(self.p,'Another exact source')
        self.s.write(self.p,key='two',summary='Both sources matter.',kind='constraint',sources=[self.src,other])
        g=SolveMap.search(self.session(),'two')
        with self.assertRaises(E):g.data({self.src:'s0',other:'s0'})

    def test_selection_content_forgery_rejected(self):
        session,g,refs=self.graph()
        session.last_selection.records[0]['summary']='wrong'
        with self.assertRaises(E):SolveMap(session,session.last_selection)

    def test_snapshot_read_does_not_create_another_store(self):
        session,g,refs=self.graph()
        before=[tuple(r) for r in self.s.db.execute('SELECT id,body FROM entry ORDER BY id')]
        g.data({self.src:'s0'});g.assert_fresh()
        after=[tuple(r) for r in self.s.db.execute('SELECT id,body FROM entry ORDER BY id')]
        self.assertEqual(before,after)

class SolveMapIntegration(Fixture):
    def config(self, **overrides):
        self.write('constraint','Keep SOURCE exactly; do not infer omitted evidence.',pinned=True)
        cfg=RecurseConfig.for_workload('research',model='fixture',n=1,budget=16000,
            seed_answer='BASE',seed_scratchpad='visible notes',memory_session=self.session(),
            verification_id='test-v1',token_counter=lambda t,m:len(t),token_counter_label='characters')
        cfg.workspace=replace(cfg.workspace,solve_map=True)
        return replace(cfg,**overrides)

    def test_actual_search_map_and_full_judge(self):
        cfg=self.config();calls=[];searched=[False]
        def worker(q):
            calls.append(q)
            if q['system']==prompts.HALT_SYSTEM:return '{"halt_prob":0.2,"reason":"fixture"}'
            packet=json.loads(q['user']);mapping=packet['solve_map']
            value=decode_ascii(mapping) if isinstance(mapping,str) else mapping
            self.assertIn('do not',value['nodes'][0][-1])
            alias=value['sources'][0][1]
            self.assertIn(alias,[s['id'] for s in packet['sources'].values()])
            if packet['role']=='notes' and not searched[0]:
                searched[0]=True
                return json.dumps({'find':[[alias,'exception',0]]})
            if packet['role']=='notes':
                self.assertIn('Keep the exception.',q['user']);return 'Keep exact evidence.'
            return json.dumps({'patch':{'ticket':packet['ticket'],'edits':[[4,4,'; DONE']]}})
        trace=recurse('Keep SOURCE',client=Capture(worker),config=cfg)
        self.assertEqual(trace.final_answer,'BASE; DONE')
        self.assertEqual(sum(e['role']=='workspace_retrieval' for e in trace.call_events),1)
        judges=[q for q in calls if q['system']==prompts.HALT_SYSTEM]
        self.assertIn('BASE; DONE',judges[-1]['user'])
        self.assertNotIn('solve_map',judges[-1]['user'])
        self.assertTrue(any('solve_map' in e for e in trace.workspace_events))

    def test_changed_pin_during_generation_rejects_response(self):
        cfg=self.config()
        def worker(q):
            if q['system']==prompts.HALT_SYSTEM:return '{"halt_prob":0.2,"reason":"fixture"}'
            self.write('new','New host constraint',pinned=True)
            return 'unsafe stale proposal'
        trace=recurse('SOURCE',client=Capture(worker),config=cfg)
        self.assertEqual(trace.final_answer,'BASE')
        self.assertFalse(trace.halted)
        self.assertEqual(len(trace.steps),0)

    def test_whole_map_budget_is_enforced(self):
        cfg=self.config();cfg.workspace=replace(cfg.workspace,budget=100)
        r=MeteredClient(Capture(),cfg,RunTrace(problem='SOURCE'),None)
        r.memory_context('SOURCE','')
        with self.assertRaises(ContextLimitError):
            build_view(r,role='notes',model='fixture',system='instructions',values=dict(problem='SOURCE',answer='BASE'))

    def test_counter_selects_smaller_complete_request(self):
        cfg=self.config();r=MeteredClient(Capture(),cfg,RunTrace(problem='SOURCE'),None)
        r.memory_context('SOURCE','')
        v=build_view(r,role='notes',model='fixture',system='instructions',values=dict(problem='SOURCE',answer='BASE'))
        packet=v.render();measurement=v.map_measurement
        self.assertEqual(len(v.system)+len(packet),min(measurement['complete_input_units'].values()))
        self.assertEqual(measurement['complete_input_units'][measurement['selected']],min(measurement['complete_input_units'].values()))

    def test_configuration_and_checkpoint_bind_opt_in(self):
        cfg=self.config();old=checkpoint.policy(cfg)
        cfg.workspace=replace(cfg.workspace,solve_map=False)
        self.assertNotEqual(old,checkpoint.policy(cfg))
        cfg.memory_session=None;cfg.workspace=replace(cfg.workspace,solve_map=True)
        with self.assertRaises(ValueError):cfg.validate()
        with self.assertRaises(ValueError):WorkspacePolicy(solve_map=True).validate()

class JsonTransportTests(unittest.TestCase):
    def test_exact_number_spellings_and_strings(self):
        original='{ "negative": -0.00, "large": 1e309, "precise": 0.123456789012345678901, "text": "do NOT delete spaces" }'
        compact=compact_json(original)
        self.assertEqual(compact,'{"negative":-0.00,"large":1e309,"precise":0.123456789012345678901,"text":"do NOT delete spaces"}')

    def test_unicode_and_escaped_strings(self):
        values={'text':chr(960)+' NOT '+chr(10)+'"quoted" '+chr(92)+' path','empty':None,'bool':False,'items':[1,2,3]}
        for ascii_only in (True,False):
            original=json.dumps(values,ensure_ascii=ascii_only,indent=4)
            compact=compact_json(original)
            self.assertEqual(json.loads(compact),values)
            self.assertEqual(compact,json.dumps(values,ensure_ascii=ascii_only,separators=(',',':')))

    def test_invalid_or_ambiguous_input_stays_exact(self):
        cases=['{ "x":1, "x":2 }','{ "n":NaN }','{ "x": 2, }','[1,','not JSON','"a b"','{ "n":01 }']
        for text in cases:
            with self.subTest(text=text):self.assertEqual(compact_json(text),text)

    def test_size_limit_and_idempotence(self):
        value='{ "n": [1, 2, 3] }'
        self.assertEqual(compact_json(value,max_chars=2),value)
        once=compact_json(value);self.assertEqual(compact_json(once),once)

    def request(self,counter,role='notes'):
        cfg=RecurseConfig(compact_json_transport=True,token_counter=counter,token_counter_label='test-units')
        client=Capture(lambda q:'response');r=MeteredClient(client,cfg,RunTrace(problem='test'),None)
        original='{ "n": [1, 2], "text": "exact evidence" }'
        r._send(dict(model='test',system='sys',user=original,max_tokens=20,temperature=0,use_headroom=False),raw_system='sys',raw_user=original,role=role)
        return original,client.requests[0],r.trace

    def test_measured_compaction_and_accounting(self):
        original,q,trace=self.request(lambda t,m:len(t))
        self.assertEqual(q['user'],compact_json(original))
        event=trace.call_events[0]['json_transport']
        self.assertTrue(event['applied']);self.assertLess(event['after'],event['before'])

    def test_counter_can_reject_a_shorter_spelling(self):
        def count(t,m):return 100 if t.startswith('{"n"') else len(t)
        original,q,trace=self.request(count)
        self.assertEqual(q['user'],original)
        self.assertFalse(trace.call_events[0]['json_transport']['applied'])

    def test_judge_and_generic_input_remain_exact(self):
        for role in ('judge','seed_judge','generic'):
            with self.subTest(role=role):
                original,q,trace=self.request(lambda t,m:len(t),role)
                self.assertEqual(q['user'],original)
                self.assertNotIn('json_transport',trace.call_events[0])

if __name__=='__main__':unittest.main()
