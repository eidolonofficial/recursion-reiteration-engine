"""A local deterministic transport demo, not a neural model or a proof engine."""
from __future__ import annotations
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from headroom_recursion import RecurseConfig, Tier, WorkspacePolicy, recurse
from headroom_recursion.clients import CallableClient
from headroom_recursion.progress import ProgressCheck


def local_demo(**request):
    if request['system'].startswith('Check correctness and completeness'):
        return '{"halt_prob":0.2,"reason":"Fixed demo control score, not proof."}'
    packet=json.loads(request['user'])
    if packet['role']=='progress_seed':
        return json.dumps({'keep':[x['id'] for x in packet['planning']['candidates'][:1]],'next_check':'Append one explicit check result.'})
    if packet['role']=='notes':
        return 'Keep the archived results unchanged; add the next explicit demo record.'
    source=packet['sources']['candidate']
    return json.dumps({'workspace_patch':dict(version=1,scope=packet['scope'],ticket=packet['ticket'],base=packet['base'],
        edits=[dict(start=source['length'],end=source['length'],text='\nDEMO RECORD: transport round trip completed.\n')])})


def main():
    seed='ASSUMPTION: demonstration only; no mathematical discovery.\n'+''.join(
        f'Recorded check {i:04d}: {i}+{i}={2*i}. Retain this historical result.\n' for i in range(1000))
    cfg=RecurseConfig(n=1,T=1,ladder=tuple(Tier(f'phase-{i}') for i in range(3)),seed_answer=seed,
        seed_scratchpad='Preserve archived arithmetic records.',preseed_ladder=True,
        workspace=WorkspacePolicy(budget=8000,required_passages=('ASSUMPTION: demonstration only; no mathematical discovery.',)),
        token_counter=lambda text,model:len(text),token_counter_label='exact-unicode-characters/text-only',
        progress_checks=(ProgressCheck('historical-prefix','Preserve every historical record exactly.',lambda text:text.startswith(seed),required=True),),
        max_total_calls=30,memory_scope='workspace-demo')
    trace=recurse('Add one demo record per phase while retaining all old checks.',client=CallableClient(local_demo),config=cfg)
    print(json.dumps({'stop_reason':trace.stop_reason,'steps':len(trace.steps),'calls':trace.total_calls,
        'full_historical_prefix_preserved':trace.final_answer.startswith(seed),
        'input_reference_characters':trace.tokens_before,'input_sent_characters':trace.tokens_after,
        'counter':trace.token_count_kind,'scope':'deterministic interface demonstration; no neural inference'},indent=2))
    assert len(trace.steps)==3 and trace.final_answer.startswith(seed)
if __name__=='__main__':main()
