"""Paired transport replay of the supplied 100-tier archive; NOT new inference.

The recorded responses are fixtures. Both controllers receive identical authored
notes/candidates/judge scores. The workspace backend translates those recorded
candidate changes into patches, asking for any spans it was not offered. This
checks transport size, reconstruction, budgets and locks, not model quality.
Original mathematical experiments are not rerun or newly certified here.
"""
from __future__ import annotations
import argparse
import difflib
import hashlib
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from headroom_recursion import RecurseConfig,Tier,WorkspacePolicy,recurse
from headroom_recursion.clients import CallResult
from headroom_recursion.progress import ProgressCheck
from headroom_recursion.workspace import encode


def sha(text):return hashlib.sha256(text.encode('utf-8')).hexdigest()

def edits_between(a,b):
    # Input is the same canonical JSON layout in both arms. Content strings are
    # untouched. A one-time fixture migration changes only seed JSON whitespace
    # and key ordering; its exact original is archived and separately identified.
    # Compare whole JSON string tokens, not individual popular punctuation.
    # Character-level autojunk can misalign an unchanged trailing history and
    # demand dozens of unnecessary reads. Offsets still address original bytes
    # (Unicode characters); the patch controller remains format-agnostic.
    pattern = r'"(?:\\.|[^"\\])*"|[^"]+'
    left, right = re.findall(pattern, a), re.findall(pattern, b)
    assert "".join(left) == a and "".join(right) == b
    offsets = [0]
    for token in left: offsets.append(offsets[-1] + len(token))
    return [dict(start=offsets[i], end=offsets[j], text="".join(right[k:l]))
            for tag,i,j,k,l in difflib.SequenceMatcher(a=left,b=right,autojunk=False).get_opcodes()
            if tag != "equal"]


class Fixture:
    def __init__(self,folder):
        self.root=folder
        self.ex=folder/'exchange'
        self.plan=json.loads((folder/'plan.json').read_text(encoding="utf-8"))
        first=json.loads((self.ex/'001.request.json').read_text(encoding="utf-8"))
        self.problem=first['user'].split('PROBLEM:\n',1)[1].split('\n\nCANDIDATE ANSWER:',1)[0]
        self.original_seed=first['user'].split('\nCANDIDATE ANSWER:\n',1)[1].split('\n\nVISIBLE WORKING NOTES:',1)[0]
        self.seed= json.dumps(json.loads(self.original_seed),ensure_ascii=False,sort_keys=True)
        raw=json.loads((folder/'live-trace.json').read_text(encoding="utf-8"))
        self.seed_notes=first['user'].split('\nVISIBLE WORKING NOTES:\n',1)[1].split('\n\nCheck the candidate',1)[0]
        self.final=raw['final_answer']
        self.final_obj=json.loads(self.final)
        self.registry=self.final_obj['certificates']
        self.seed_obj=json.loads(self.seed)
        self.answers={t:(self.ex/f'{5*t:03d}.response.txt').read_text(encoding="utf-8").strip() for t in range(1,101)}
        self.notes={(t,j):(self.ex/f'{5*(t-1)+2+j:03d}.response.txt').read_text(encoding="utf-8").strip()
                    for t in range(1,101) for j in (1,2)}
        self.old=set(self.seed_obj['certificates'])
        for t,a in self.answers.items():
            obj=json.loads(a)
            assert obj['target_status']=='unresolved'
            assert all(v==self.registry[k] for k,v in obj['certificates'].items())
    def check(self,text,key):
        try:return json.loads(text)['certificates'].get(key)==self.registry[key]
        except (ValueError,KeyError,TypeError):return False
    def gate(self,text):
        try:
            obj=json.loads(text)
            return (set(obj)==set(self.seed_obj) and obj['target_status']=='unresolved' and
                    obj['established'][:len(self.seed_obj['established'])]==self.seed_obj['established'] and
                    self.old<=set(obj['certificates']) and
                    all(k in self.registry and v==self.registry[k] for k,v in obj['certificates'].items()))
        except (ValueError,KeyError,TypeError):return False


class RecordedClient:
    def __init__(self,fixture,compact):
        self.f=fixture;self.compact=compact;self.stage=0;self.note_index={};self.current=fixture.seed
        self.requests=[];self.responses=[];self.pending=None;self.retrievals=0;self.judges=[]
    def complete(self,**request):
        self.requests.append(request)
        system=request['system']; user=request['user']
        p=json.loads(user) if user.startswith('{') else None
        if system.startswith('Prepare a progress checkpoint'):
            if self.compact:
                data=p['planning'];assert p['base']==sha(self.current)
            else:
                data=json.loads(next(s for s in user.splitlines() if s.startswith('{"approved_ladder"')))
                assert data['incumbent_answer']==self.current
            self.stage=next(s['tier'] for s in self.f.plan if s['name']==data['entering_tier'])
            text=json.dumps({'keep':[x['id'] for x in data['candidates'][:2]],'next_check':self.f.plan[self.stage-1]['obligation']})
        elif system.startswith('Maintain concise visible working notes'):
            if self.compact:assert p['base']==sha(self.current)
            j=self.note_index.get(self.stage,0)+1;self.note_index[self.stage]=j
            text=self.f.notes[self.stage,j]
        elif system.startswith('Use the visible working notes'):
            target=self.f.answers[self.stage]
            if not self.compact:
                text=target;self.current=target
            else:
                assert p['base']==sha(self.current)
                if self.pending is None:self.pending=edits_between(self.current,target)
                shown=p['sources']['candidate']['excerpts']
                missing=next((e for e in self.pending if not (e['start']==e['end']==len(self.current)) and
                              not any(x['start']<=e['start']<=e['end']<=x['end'] for x in shown)),None)
                if missing is not None:
                    a=max(0,missing['start']-8);b=min(len(self.current),max(missing['end'],missing['start']+1)+8)
                    text=encode({'memory_request':dict(id=p['base'],start=a,end=b)});self.retrievals+=1
                else:
                    text=encode({'workspace_patch':dict(version=1,scope=p['scope'],ticket=p['ticket'],base=p['base'],edits=self.pending)})
                    self.current=target;self.pending=None
        elif system.startswith('Check correctness and completeness'):
            self.judges.append(request)
            assert self.current in user
            text='{"halt_prob":0.36,"reason":"Recorded uncalibrated control score; no new inference or proof authority."}'
        else:raise AssertionError(system[:100])
        self.responses.append(text)
        return CallResult(text)


def run_arm(f,compact,out):
    client=RecordedClient(f,compact)
    cfg=RecurseConfig(n=2,T=1,ladder=tuple(Tier(s['name'],max_steps=1,max_tokens=24000) for s in f.plan),
        judge_model='recorded-control-score',progress_model=f.plan[-1]['name'],
        judge_votes=1,halt_threshold=.98,use_headroom=True,compression_min_tokens=1,
        scratchpad_tokens=1800,context_tokens=1200,
        token_counter=lambda text,model:len(text),token_counter_label='exact-unicode-characters/text-only',
        memory_max_bytes=64_000_000,memory_max_rounds=20,memory_read_chars=12000,
        pinned_notes=('P=NP is a target, not an assumption. No finite benchmark resolves an asymptotic universal claim.',
                      'Recorded-response transport test; not new neural inference or a new mathematical evaluation.'),
        enforce_progress=True,preseed_ladder=True,progress_k=2,progress_tokens=1800,
        progress_checks=tuple(ProgressCheck(name=k,statement='Preserve recorded finite evidence '+k,
                             check=lambda s,k=k:f.check(s,k),required=k in f.old) for k in f.registry),
        memory_scope='workspace-paired-fixture-v1',validator=f.gate,oracle_sufficient=False,
        oracle_note='Schema, immutable prior claim prefix and recorded result hashes only. Not general proof authority.',
        seed_answer=f.seed,seed_scratchpad=f.seed_notes,max_total_calls=1500,max_wall_seconds=1800,
        workspace=WorkspacePolicy(budget=10000,chunk_chars=1000,max_edits=128,
                       required_passages=('"target_status": "unresolved"',)) if compact else None)
    t=time.monotonic();trace=recurse(f.problem,client=client,config=cfg);elapsed=time.monotonic()-t
    # Retain the exact pre-migration seed independently in the archive receipt.
    assert json.loads(f.original_seed)==json.loads(f.seed)
    assert trace.final_answer==f.final,(trace.stop_reason,trace.error,len(trace.steps),trace.tier_stops[-3:])
    assert len(trace.steps)==100 and all(s.progress_accepted for s in trace.steps)
    assert set(trace.locked_checks)==set(f.registry)
    assert all(f.gate(s.answer) for s in trace.steps)
    summary=dict(mode='workspace' if compact else 'legacy',attempted_calls=trace.total_calls,
                 input_characters=sum(len(r['system'])+len(r['user']) for r in client.requests),
                 output_characters=sum(len(s) for s in client.responses),
                 worker_input_characters=sum(len(r['system'])+len(r['user']) for r in client.requests
                    if not r['system'].startswith('Check correctness and completeness')),
                 full_judge_input_characters=sum(len(r['system'])+len(r['user']) for r in client.judges),
                 retrieval_exchanges=client.retrievals,accepted_steps=len(trace.steps),locked_checks=len(trace.locked_checks),
                 final_sha256=sha(trace.final_answer),elapsed_seconds=elapsed,stop_reason=trace.stop_reason,
                 workspace_max_input=max([len(r['system'])+len(r['user']) for r in client.requests
                    if r['user'].startswith('{') and json.loads(r['user']).get('schema')=='workspace-v1'] or [0]),
                 counter=trace.token_count_kind)
    folder=out/summary['mode'];folder.mkdir(parents=True,exist_ok=True)
    (folder/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    (folder/'events.json').write_text(json.dumps({'calls':trace.call_events,'workspace':trace.workspace_events,'progress':trace.progress_events},ensure_ascii=False,indent=2)+'\n')
    # No huge duplicate historical corpus in the delivery: event digests plus a
    # small real prompt pair suffice; original evidence remains in the input ZIP.
    (folder/'last-worker-request.json').write_text(json.dumps(next(r for r in reversed(client.requests) if r['system'].startswith('Use the visible working notes')),ensure_ascii=False,indent=2)+'\n')
    return summary,[sha(encode(r)) for r in client.judges]


def main():
    ap=argparse.ArgumentParser();ap.add_argument('recorded_run',type=Path);ap.add_argument('--out',type=Path,required=True);a=ap.parse_args()
    f=Fixture(a.recorded_run);a.out.mkdir(parents=True,exist_ok=True)
    baseline,j1=run_arm(f,False,a.out);print('BASELINE',baseline,flush=True)
    compact,j2=run_arm(f,True,a.out);print('WORKSPACE',compact,flush=True)
    assert j1==j2,'whole-candidate judge requests changed'
    result={'scope':'Recorded-response paired transport replay; no new model inference or mathematical experiments',
            'original_seed_sha256':sha(f.original_seed),'canonical_fixture_seed_sha256':sha(f.seed),
            'seed_parsed_value_unchanged':True,'whole_judge_requests_identical':True,
            'baseline':baseline,'workspace':compact,
            'input_reduction_pct':100*(1-compact['input_characters']/baseline['input_characters']),
            'input_and_output_reduction_pct':100*(1-(compact['input_characters']+compact['output_characters'])/(baseline['input_characters']+baseline['output_characters'])),
            'no_semantic_quality_or_upstream_headroom_performance_claim':True}
    (a.out/'comparison.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2),flush=True)
if __name__=='__main__':main()
