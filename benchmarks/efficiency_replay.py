"""Compare wire formats on explicitly supplied recorded research deltas.

No fresh inference, new mathematical result, or population benchmark. Original
candidate bytes, exact judge inputs, and registered finite-record identities must
agree. Tokenizer rank files must already be cached; this script cannot download.
The research fixture is external and is not shipped in the clean source export.
"""
from __future__ import annotations
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from headroom_recursion import RecurseConfig, Tier, WorkspacePolicy, recurse
from headroom_recursion.clients import CallResult
from headroom_recursion.progress import ProgressCheck
from headroom_recursion.workspace import encode


def sha(s): return hashlib.sha256(s.encode('utf-8')).hexdigest()


def reconstruct(original, edits):
    out = []; cursor = 0
    for e in edits:
        assert cursor <= e['start'] <= e['end'] <= len(original)
        out.extend([original[cursor:e['start']], e['text']]); cursor = e['end']
    return ''.join(out) + original[cursor:]


class Fixture:
    def __init__(self, path):
        raw = Path(path).read_bytes()
        if path.suffix == '.gz': raw = gzip.decompress(raw)
        o = json.loads(raw); assert o['schema'] == 2
        self.sha = hashlib.sha256(raw).hexdigest()
        self.problem, self.seed, self.notes = o['problem'], o['seed'], o['seed_notes']
        self.plan = o['plan']; self.stages = o['stages']; answer = self.seed
        self.targets = []
        for row in self.stages:
            answer = reconstruct(answer, row['edits']); self.targets.append(answer)
        assert sha(answer) == o['final_sha256']
        self.final = answer; self.seed_obj = json.loads(self.seed)
        self.registry = json.loads(answer)['certificates']
        self.old = set(self.seed_obj['certificates'])
        assert len(self.plan) == len(self.stages) == 100
    def check(self, text, key):
        try: return json.loads(text)['certificates'].get(key) == self.registry[key]
        except (ValueError, KeyError, TypeError): return False
    def gate(self, text):
        try:
            o = json.loads(text)
            return (set(o) == set(self.seed_obj) and o['target_status'] == 'unresolved'
                and o['established'][:len(self.seed_obj['established'])] == self.seed_obj['established']
                and self.old <= set(o['certificates'])
                and all(k in self.registry and v == self.registry[k] for k,v in o['certificates'].items()))
        except (ValueError, KeyError, TypeError): return False


class Recorded:
    def __init__(self, fixture, mode):
        self.f, self.mode = fixture, mode
        self.current = fixture.seed; self.note_index = {}; self.requests = []; self.responses = []
        self.judges = []; self.read_exchanges = 0; self.ranges_read = 0
        self.indices = {p['name']: i for i,p in enumerate(fixture.plan)}
    def complete(self, **q):
        self.requests.append(q)
        system, user = q['system'], q['user']
        p = json.loads(user) if user.startswith('{') else None
        compact = p is not None and p.get('schema') == 'workspace-v2'
        if system.startswith('Prepare a progress checkpoint'):
            d = p['planning']
            text = encode({'keep':[r['id'] for r in d['candidates'][:2]],
                           'next_check':self.f.plan[self.indices[d['entering_tier']]]['obligation']})
        elif system.startswith('Maintain concise visible working notes'):
            i = self.indices[q['model']]; j = self.note_index.get(i, 0); self.note_index[i] = j+1
            text = self.f.stages[i]['notes'][j]
        elif system.startswith('Use the visible working notes'):
            i = self.indices[q['model']]; edits = self.f.stages[i]['edits']
            assert reconstruct(self.current, edits) == self.f.targets[i]
            source = p['sources']['candidate']; shown = source['excerpts']
            ranges = [(e[0],e[0]+len(e[1])) for e in shown] if compact else [(e['start'],e['end']) for e in shown]
            for e in shown:
                a, t = (e[0], e[1]) if compact else (e['start'],e['text'])
                assert self.current[a:a+len(t)] == t
            missing = [e for e in edits if not (e['start']==e['end']==len(self.current))
                and not any(a <= e['start'] <= e['end'] <= b for a,b in ranges)]
            if missing:
                selected = missing[:8] if compact else missing[:1]
                reads = []; seen = set()
                for e in selected:
                    a=max(0,e['start']-1);b=min(len(self.current),max(e['end'],e['start']+1)+1)
                    if (a,b) not in seen: reads.append([source['id'],a,b]);seen.add((a,b))
                text = encode({'read':reads}) if compact else encode({'memory_request':dict(id=source['id'],start=reads[0][1],end=reads[0][2])})
                self.read_exchanges += 1; self.ranges_read += len(reads)
            else:
                if compact:
                    text = encode({'patch':{'ticket':p['ticket'], 'edits':[[e['start'],e['end'],e['text']] for e in edits]}})
                else:
                    text = encode({'workspace_patch':dict(version=1,scope=p['scope'],ticket=p['ticket'],base=p['base'],edits=edits)})
                self.current = self.f.targets[i]
        elif system.startswith('Check correctness and completeness'):
            assert self.current in user
            self.judges.append(sha(encode(q)))
            text='{"halt_prob":0.36,"reason":"Recorded heuristic control score; no new inference or proof authority."}'
        else: raise AssertionError(system[:100])
        self.responses.append(text)
        return CallResult(text)


def run(f, mode, count, label):
    worker = Recorded(f, mode)
    v2 = mode != 'workspace-v1'
    cfg = RecurseConfig(n=2,T=1,ladder=tuple(Tier(s['name'],max_steps=1,max_tokens=24000) for s in f.plan),
        judge_model='recorded-control-score',progress_model=f.plan[-1]['name'],judge_can_halt=False,
        judge_votes=1,halt_threshold=.98,token_counter=count,token_counter_label=label,
        memory_max_bytes=64_000_000,memory_max_rounds=20,memory_read_chars=12000,
        pinned_notes=('P=NP is a target, not an assumption. Finite experiments do not resolve universal claims.',
                      'Recorded transport test; not new inference or mathematical evaluation.'),
        enforce_progress=True,preseed_ladder=True,progress_k=2,progress_tokens=1800,
        progress_checks=tuple(ProgressCheck(k,'Preserve recorded finite evidence '+k,
                        lambda t,k=k:f.check(t,k),required=k in f.old) for k in f.registry),
        memory_scope='efficiency-paired-replay',validator=f.gate,oracle_sufficient=False,
        oracle_note='Schema and exact recorded identities only. Not general proof authority.',
        seed_answer=f.seed,seed_scratchpad=f.notes,max_total_calls=1500,max_wall_seconds=3600,
        workspace=WorkspacePolicy(budget=4096,chunk_chars=768,max_edits=128,compact=v2,
                                  max_optional_chunks=6 if v2 else None,
                                  required_passages=('"target_status": "unresolved"',)),
        progress_seed_mode='local' if mode=='efficient-v2' else 'model',
        reuse_exact_judgments=mode=='efficient-v2')
    t=time.monotonic();trace=recurse(f.problem,client=worker,config=cfg)
    if trace.final_answer != f.final or len(trace.steps)!=100:
        raise AssertionError((mode,trace.stop_reason,trace.error,len(trace.steps),trace.tier_stops[-3:]))
    assert all(s.progress_accepted and f.gate(s.answer) for s in trace.steps)
    assert set(trace.locked_checks)==set(f.registry)
    judge_index={i for i,q in enumerate(worker.requests) if q['system'].startswith('Check correctness and completeness')}
    inputs=[count(q['system'],q['model'])+count(q['user'],q['model']) for q in worker.requests]
    outputs=[count(s,q['model']) for s,q in zip(worker.responses,worker.requests)]
    result=dict(mode=mode,counter=label,seconds=time.monotonic()-t,calls=trace.total_calls,
        actual_input=sum(inputs),actual_output=sum(outputs),judge_input=sum(inputs[i] for i in judge_index),
        worker_input=sum(n for i,n in enumerate(inputs) if i not in judge_index),
        input_characters=sum(len(q['system'])+len(q['user']) for q in worker.requests),
        output_characters=sum(map(len,worker.responses)),max_worker_input=max(n for i,n in enumerate(inputs) if i not in judge_index),
        read_exchanges=worker.read_exchanges,ranges_read=worker.ranges_read,steps=len(trace.steps),
        progress_locks=len(trace.locked_checks),final_sha256=sha(trace.final_answer),judge_request_hashes=worker.judges,
        reused_judgments=sum(e['event']=='exact-judge-reuse' for e in trace.progress_events),
        stop_reason=trace.stop_reason,halted=trace.halted)
    assert result['max_worker_input']<=4096
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('fixture',type=Path);parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--encoding',choices=['characters','cl100k_base','o200k_base'],default='characters')
    args=parser.parse_args()
    if args.out.exists():raise SystemExit('refusing to overwrite evidence')
    if args.encoding=='characters':
        count=lambda s,m:len(s);label='exact-Unicode-characters'
        tokenizer_version=None
    else:
        import tiktoken,tiktoken.load,importlib.metadata
        def no_download(path):raise RuntimeError('Tokenizer ranks not cached; benchmark does not download')
        tiktoken.load.read_file=no_download
        enc=tiktoken.get_encoding(args.encoding)
        count=lambda s,m:len(enc.encode_ordinary(s));label='tiktoken/'+args.encoding+'/text-only'
        tokenizer_version=importlib.metadata.version('tiktoken')
    f=Fixture(args.fixture);results=[]
    for mode in ('workspace-v1','compact-v2','efficient-v2'):
        row=run(f,mode,count,label);results.append(row)
        print(encode({k:v for k,v in row.items() if k!='judge_request_hashes'}),flush=True)
    assert results[0]['judge_request_hashes']==results[1]['judge_request_hashes']==results[2]['judge_request_hashes']
    data=dict(schema=1,fixture_sha256=f.sha,tokenizer_version=tokenizer_version,results=results,
              scope='Recorded-response transport comparison; no new inference or mathematical experiment.',
              input_reduction_vs_v1=1-results[-1]['actual_input']/results[0]['actual_input'],
              total_reduction_vs_v1=1-(results[-1]['actual_input']+results[-1]['actual_output'])/(results[0]['actual_input']+results[0]['actual_output']))
    args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(json.dumps(data,indent=2)+'\n')


if __name__=='__main__':main()
