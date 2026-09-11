import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from headroom_recursion import RecurseConfig, Tier, recurse, WorkspacePolicy
from headroom_recursion.clients import CallResult, TransportError
from headroom_recursion.compression import ContextLimitError
from headroom_recursion.progress import ProgressCheck
from headroom_recursion.runtime import MeteredClient
from headroom_recursion.trace import RunTrace
from headroom_recursion.workspace import build_view, encode
from headroom_recursion import checkpoint, prompts


class Capture:
    def __init__(self, fn=None):
        self.calls = []
        self.fn = fn or (lambda request: 'notes')
    def complete(self, **request):
        self.calls.append(request)
        return CallResult(self.fn(request))


def cfg(**kwargs):
    return RecurseConfig(n=1,T=1,preseed_ladder=False,
                         token_counter=lambda t,m:len(t), token_counter_label='characters',
                         workspace=WorkspacePolicy(budget=7000,chunk_chars=400),
                         memory_scope='test',**kwargs)


def runtime(client=None, **kwargs):
    c = cfg(**kwargs)
    return MeteredClient(client or Capture(), c, RunTrace(problem='task'), None)


def view(text=None, policy=None, role='answer'):
    r=runtime()
    if policy is not None:r.cfg.workspace=policy
    text=text if text is not None else ''.join(f'Claim {i}: retained evidence line.\n' for i in range(500))
    v=build_view(r,role=role,model='local',system='review',
                 values=dict(problem='Improve the latest claim.',answer=text,scratchpad='next test',context=''))
    return r,v


def patch(v, edits, **changes):
    obj={k:v.packet[k] for k in ('scope','ticket','base')}
    obj.update(version=1,edits=edits);obj.update(changes)
    return encode({'workspace_patch':obj})


def append_reply(packet,text):
    return encode({'workspace_patch':dict(version=1,scope=packet['scope'],ticket=packet['ticket'],
                   base=packet['base'],edits=[dict(start=packet['sources']['candidate']['length'],
                   end=packet['sources']['candidate']['length'],text=text)])})


class WorkspaceTests(unittest.TestCase):
    def test_complete_prompt_is_bounded_and_original_archived(self):
        r,v=view();self.assertLessEqual(len(v.system)+len(v.render()),7000)
        self.assertLess(len(v.render()),len(v.texts['candidate']))
        self.assertEqual(r.store.records[v.base],v.texts['candidate'])
    def test_excerpts_exact_unicode_offsets(self):
        r,v=view('αβγ🙂\n'*2000)
        for name, source in json.loads(v.render())['sources'].items():
            for e in source['excerpts']:
                self.assertEqual(e['text'],v.texts[name][e['start']:e['end']])
    def test_append_preserves_unseen_content(self):
        r,v=view();n=len(v.texts['candidate'])
        self.assertEqual(v.patch(patch(v,[dict(start=n,end=n,text='new')]),r.store),v.texts['candidate']+'new')
    def test_noop_preserves_original_exactly(self):
        r,v=view(' \n theorem X = 0 \n ')
        self.assertEqual(v.patch(patch(v,[]),r.store),v.texts['candidate'])
    def test_visible_replacement(self):
        r,v=view('alpha beta')
        self.assertEqual(v.patch(patch(v,[dict(start=0,end=5,text='gamma')]),r.store),'gamma beta')
    def test_unseen_replacement_rejected(self):
        r,v=view();covered={i for a,b in v.ranges['candidate'] for i in range(a,b)}
        i=next(i for i in range(len(v.texts['candidate'])) if i not in covered)
        with self.assertRaises(TransportError):v.patch(patch(v,[dict(start=i,end=i+1,text='x')]),r.store)
    def test_read_authorizes_edit(self):
        r,v=view();v.retrieve(dict(id=v.base,start=6000,end=6010),r.store,100)
        out=v.patch(patch(v,[dict(start=6000,end=6010,text='x')]),r.store)
        self.assertEqual(out,v.texts['candidate'][:6000]+'x'+v.texts['candidate'][6010:])
    def test_wrong_base_scope_ticket_version(self):
        for changes in ({'base':'0'*64},{'scope':'other'},{'ticket':'stale'},{'version':True},{'version':2}):
            r,v=view()
            with self.subTest(changes=changes),self.assertRaises(TransportError):v.patch(patch(v,[],**changes),r.store)
    def test_bad_edit_ranges_types_and_overlap(self):
        bad=[[dict(start=-1,end=0,text='')],[dict(start=0,end=999999,text='')],
             [dict(start=True,end=1,text='')],[dict(start=0,end=1,text=7)],
             [dict(start=2,end=3,text=''),dict(start=0,end=1,text='')],
             [dict(start=0,end=3,text=''),dict(start=2,end=4,text='')],
             [dict(start=0,end=0,text='a'),dict(start=0,end=0,text='b')]]
        for edits in bad:
            r,v=view('abcdef')
            with self.subTest(edits=edits),self.assertRaises(TransportError):v.patch(patch(v,edits),r.store)
    def test_plain_answer_cannot_erase_candidate(self):
        r,v=view()
        with self.assertRaises(TransportError):v.patch('a short new summary',r.store)
    def test_extra_fields_rejected(self):
        r,v=view();obj=json.loads(patch(v,[]));obj['workspace_patch']['verified']=True
        with self.assertRaises(TransportError):v.patch(encode(obj),r.store)
    def test_duplicate_json_keys_rejected(self):
        r,v=view()
        with self.assertRaises(TransportError):v.patch('{"workspace_patch":{},"workspace_patch":{}}',r.store)
    def test_archive_tamper_rejected(self):
        r,v=view();r.store.records[v.base]='tampered'
        with self.assertRaises(TransportError):v.patch(patch(v,[]),r.store)
        with self.assertRaises(TransportError):v.retrieve(dict(id=v.base,start=0,end=3),r.store,20)
    def test_unknown_read_source_rejected(self):
        r,v=view();other=r.store.put('private unrelated record')
        with self.assertRaises(TransportError):v.retrieve(dict(id=other,start=0,end=3),r.store,20)
    def test_read_range_caps(self):
        for a,b in [(0,100),(True,2),(10,5),(-1,4),(0,999999)]:
            r,v=view()
            with self.subTest(a=a,b=b),self.assertRaises(TransportError):v.retrieve(dict(id=v.base,start=a,end=b),r.store,20)
    def test_exact_required_passage_and_dependency_closure(self):
        text='A'*3000+'\nDEPENDENT STATEMENT\n'+'B'*3000+'\nREQUIRED ASSUMPTION\n'+'C'*3000
        policy=WorkspacePolicy(budget=7000,chunk_chars=300,required_passages=('DEPENDENT STATEMENT',),
                               dependencies=(('DEPENDENT STATEMENT','REQUIRED ASSUMPTION'),))
        r,v=view(text,policy)
        shown=''.join(e['text'] for e in json.loads(v.render())['sources']['candidate']['excerpts'])
        self.assertIn('DEPENDENT STATEMENT',shown);self.assertIn('REQUIRED ASSUMPTION',shown)
    def test_missing_or_ambiguous_requirement_fails(self):
        for text in ('absent','pin pin'):
            with self.subTest(text=text),self.assertRaises(ContextLimitError):view(text,WorkspacePolicy(required_passages=('pin',)))
    def test_required_passage_cannot_be_removed(self):
        r,v=view('PIN and text',WorkspacePolicy(required_passages=('PIN',)))
        with self.assertRaises(ContextLimitError):v.patch(patch(v,[dict(start=0,end=3,text='')]),r.store)
    def test_duplicate_dependency_selected_at_later_occurrence_fails(self):
        text='CLAIM first then ASSUMPTION then CLAIM'
        r,v=view(text)
        v.policy=replace(v.policy,dependencies=(('CLAIM','ASSUMPTION'),))
        start=text.rfind('CLAIM')
        with self.assertRaises(ContextLimitError):
            v._close_dependencies([(start,start+5)])
    def test_dependency_cycles_terminate(self):
        r,v=view('first then second',WorkspacePolicy(required_passages=('first',),dependencies=(('first','second'),('second','first'))))
        self.assertIn('second',v.render())
    def test_pin_or_retrieval_budget_is_fail_closed(self):
        with self.assertRaises(ContextLimitError):view('x',WorkspacePolicy(budget=10))
        r,v=view()
        with self.assertRaises(ContextLimitError):v.retrieve(dict(id=v.base,start=0,end=10000),r.store,12000)
    def test_workspace_config_and_policy_binding(self):
        for kw in ({'budget':True},{'chunk_chars':0},{'max_edits':0},{'max_patch_chars':-1},{'required_passages':['x']},{'dependencies':(('x',),)}):
            with self.subTest(kw=kw),self.assertRaises(ValueError):WorkspacePolicy(**kw).validate()
        c=cfg();c.compress_judge=True
        with self.assertRaises(ValueError):c.validate()
        c=cfg();p=checkpoint.policy(c);c.workspace=replace(c.workspace,budget=8000)
        self.assertNotEqual(checkpoint.digest(p),checkpoint.digest(checkpoint.policy(c)))
    def test_deltas_flow_to_full_validator_and_judge(self):
        initial='Historical proof.\n'*600;got=[]
        def respond(req):
            if req['system'].startswith(prompts.HALT_SYSTEM):
                got.append(req);return '{"halt_prob":0.2,"reason":"partial"}'
            p=json.loads(req['user'])
            return append_reply(p,'\nNEW') if p['role']=='answer' else 'current notes'
        checks=[]
        c=cfg(seed_answer=initial,validator=lambda s:checks.append(s) or True,oracle_sufficient=False)
        trace=recurse('Continue',client=Capture(respond),config=c)
        self.assertEqual(trace.final_answer,initial+'\nNEW')
        self.assertEqual(checks[-1],trace.final_answer)
        self.assertIn(initial,got[0]['user']);self.assertIn(trace.final_answer,got[-1]['user'])
        self.assertEqual(len(trace.steps),1)
        self.assertEqual(trace.workspace_events[-1]['status'],'reconstructed-not-yet-accepted')
    def test_invalid_patch_rolls_back_pair(self):
        initial='KEEP\n';client=Capture(lambda r:'{"halt_prob":0.2}' if r['system'].startswith(prompts.HALT_SYSTEM) else 'new notes' if json.loads(r['user'])['role']=='notes' else 'erase')
        trace=recurse('task',client=client,config=cfg(seed_answer=initial,seed_scratchpad='old notes'))
        self.assertEqual(trace.final_answer,initial);self.assertEqual(trace.best_scratchpad,'old notes')
    def test_progress_checks_reject_reconstructed_regression(self):
        def respond(req):
            if req['system'].startswith(prompts.HALT_SYSTEM):return '{"halt_prob":0.2}'
            p=json.loads(req['user'])
            if p['role']=='notes':return 'new notes'
            return encode({'workspace_patch':dict(version=1,scope=p['scope'],ticket=p['ticket'],base=p['base'],edits=[dict(start=0,end=4,text='LOST')])})
        client=Capture(respond)
        c=cfg(seed_answer='KEEP initial',seed_scratchpad='old',progress_checks=(ProgressCheck('keep','Keep evidence',lambda s:'KEEP' in s,True),))
        trace=recurse('task',client=client,config=c)
        self.assertEqual(trace.final_answer,'KEEP initial');self.assertEqual(trace.best_scratchpad,'old')
        self.assertEqual(sum(r['system'].startswith(prompts.HALT_SYSTEM) for r in client.calls),1)
    def test_retrieval_is_metered_and_counted(self):
        calls=0
        def fn(req):
            nonlocal calls;calls+=1;p=json.loads(req['user']);s=p['sources']['candidate']
            return encode({'memory_request':dict(id=s['id'],start=1000,end=1010)}) if calls==1 else 'returned notes'
        client=Capture(fn);r=runtime(client)
        out=r.complete_prompt(role='notes',model='local',system='notes',template='{answer}',values={'answer':'A'*15000},max_tokens=50,temperature=0)
        self.assertEqual(out.text,'returned notes');self.assertEqual(r.trace.total_calls,2)
        self.assertEqual(r.trace.call_events[-1]['role'],'workspace_retrieval')
        self.assertTrue(r.trace.call_events[-1]['auxiliary'])
        self.assertTrue(all(len(x['system'])+len(x['user'])<=7000 for x in client.calls))
    def test_retrieval_call_cap(self):
        def fn(req):
            p=json.loads(req['user']);return encode({'memory_request':dict(id=p['base'],start=0,end=10)})
        client=Capture(fn);r=runtime(client,max_total_calls=1)
        from headroom_recursion.runtime import BudgetExhausted
        with self.assertRaises(BudgetExhausted):r.complete_prompt(role='notes',model='local',system='x',template='{answer}',values={'answer':'A'*15000},max_tokens=50,temperature=0)
        self.assertEqual(len(client.calls),1)
    def test_truncated_patch_cannot_replace(self):
        class Truncated(Capture):
            def complete(self,**kw):return CallResult('{}',stop_reason='length')
        r=runtime(Truncated())
        with self.assertRaises(TransportError):r.complete_prompt(role='answer',model='local',system='x',template='{answer}',values={'answer':'data'},max_tokens=20,temperature=0)
    def test_checkpoint_resume_retains_archive_and_checks(self):
        initial='proof\n'*200
        def respond(req):
            if req['system'].startswith(prompts.HALT_SYSTEM):return '{"halt_prob":0.2}'
            p=json.loads(req['user']);return append_reply(p,'\nnext') if p['role']=='answer' else 'notes'
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'state.json'
            c=cfg(seed_answer=initial,checkpoint_path=path,verification_id='test-v1')
            first=recurse('task',client=Capture(respond),config=c)
            resumed=recurse('task',client=Capture(respond),config=replace(c,seed_answer='',resume_from=path))
            self.assertEqual(first.final_answer,resumed.final_answer)
            self.assertTrue(resumed.resumed)
            self.assertIn(initial,resumed.memory_archive.values())
    def test_scratchpad_retrievable_even_when_mathematical(self):
        r=runtime();notes='Exact mathematical constraint x_1+x_2=7.\n'*300
        v=build_view(r,role='notes',model='local',system='notes',values={'problem':'task','answer':'current','scratchpad':notes})
        shown=''.join(e['text'] for e in json.loads(v.render())['sources']['scratchpad']['excerpts'])
        self.assertLess(len(shown),len(notes));self.assertEqual(r.store.records[v.source_names['scratchpad']],notes)
    def test_obligations_catalog_not_repeated_but_all_checks_run(self):
        touched=[]
        r=runtime(progress_checks=tuple(ProgressCheck(str(i),'Long obligation '+str(i)*100,lambda s,i=i:touched.append(i) or True) for i in range(123)))
        v=build_view(r,role='notes',model='local',system='notes',values={'problem':'task','answer':'data'})
        p=json.loads(v.render());self.assertEqual(p['enforcement']['registered'],123)
        self.assertLess(len(v.render()),len(r.guard.render()))
        r.guard.evaluate('data');self.assertEqual(len(touched),123)

class WorkspaceIntegrationTests(unittest.TestCase):
    def test_many_exact_patch_roundtrips(self):
        import random
        rnd=random.Random(1123)
        for _ in range(200):
            text="".join(rnd.choice("abc α🙂\n") for _ in range(100))
            r,v=view(text,WorkspacePolicy(budget=12000))
            a,b=sorted(rnd.sample(range(101),2));replacement="".join(rnd.choice("z±λ") for _ in range(12))
            actual=v.patch(patch(v,[dict(start=a,end=b,text=replacement)]),r.store)
            self.assertEqual(actual,text[:a]+replacement+text[b:])
    def test_dependency_cannot_disappear_while_claim_retained(self):
        r,v=view('THEOREM depends on ASSUMPTION',WorkspacePolicy(dependencies=(('THEOREM','ASSUMPTION'),)))
        start=v.texts['candidate'].index('ASSUMPTION')
        with self.assertRaises(ContextLimitError):v.patch(patch(v,[dict(start=start,end=start+10,text='')]),r.store)
    def test_patch_limits_and_zero_edit_position(self):
        r,v=view('abcd',WorkspacePolicy(max_edits=1))
        with self.assertRaises(TransportError):v.patch(patch(v,[dict(start=0,end=1,text=''),dict(start=2,end=3,text='')]),r.store)
        r,v=view('abc',WorkspacePolicy(max_patch_chars=20))
        with self.assertRaises(TransportError):v.patch(patch(v,[]),r.store)
    def test_whole_judge_unchanged_despite_workspace_budget(self):
        client=Capture(lambda r:'{"halt_prob":0.1}')
        r=runtime(client);r.cfg.workspace=WorkspacePolicy(budget=500)
        r.complete_prompt(role='judge',model='local',system='judge',template='{answer}\n{scratchpad}',values={'answer':'theorem '*1000,'scratchpad':'raw'*1000},max_tokens=20,temperature=0)
        self.assertIn('theorem '*1000,client.calls[0]['user']);self.assertIn('raw'*1000,client.calls[0]['user'])
    def test_hard_global_limit_still_stops_full_judge(self):
        client=Capture();r=runtime(client,max_input_tokens=100)
        with self.assertRaises(ContextLimitError):r.complete_prompt(role='judge',model='local',system='judge',template='{answer}',values={'answer':'x'*101},max_tokens=20,temperature=0)
        self.assertEqual(client.calls,[])
    def test_actual_command_backend_receives_bounded_json_and_returns_patch(self):
        import sys
        from headroom_recursion.clients import CommandClient
        with tempfile.TemporaryDirectory() as tmp:
            worker=Path(tmp)/'worker.py'
            worker.write_text("""import json,sys
r=json.load(sys.stdin)
p=json.loads(r['user'])
assert p['schema']=='workspace-v1'
assert len(r['system'])+len(r['user'])<=7000
s=p['sources']['candidate']
v={'version':1,'scope':p['scope'],'ticket':p['ticket'],'base':p['base'],
   'edits':[{'start':s['length'],'end':s['length'],'text':'APPENDED'}]}
print(json.dumps({'protocol_version':1,'ok':True,'text':json.dumps({'workspace_patch':v})}))
""")
            backend=CommandClient([sys.executable,'-S',str(worker)],timeout_s=10)
            r=runtime(backend)
            original='mathematical exact history x+y=z\n'*2000
            out=r.complete_prompt(role='answer',model='local',system='answer',template='{answer}',values={'answer':original},max_tokens=1000,temperature=0)
            self.assertEqual(out.text,original+'APPENDED')
            self.assertLess(r.trace.tokens_after,r.trace.tokens_before)
    def test_manual_backend_accepts_workspace_patch(self):
        import io
        from headroom_recursion.clients import ManualClient
        # Exercise its parser separately from the workspace's base/ticket logic.
        client=ManualClient(reader=io.StringIO('{"workspace_patch":{}}\nEND\n'),writer=io.StringIO())
        result=client.complete(model='local',system='answer',user='packet')
        self.assertIn('workspace_patch',result.text)
    def test_cli_workspace_dry_run(self):
        import contextlib,io
        from headroom_recursion.cli import main
        output=io.StringIO()
        with contextlib.redirect_stdout(output):code=main(['--dry-run','--workspace-tokens','4096'])
        self.assertEqual(code,0);self.assertIn('workspace',output.getvalue())

if __name__=='__main__':unittest.main()

