"""A real compact controller exchange with a scripted worker, not neural inference."""
from __future__ import annotations
import json
from headroom_recursion import RecurseConfig, Tier, recurse
from headroom_recursion.clients import CallableClient
from headroom_recursion.progress import ProgressCheck


def main():
    def worker(**request):
        if request['user'].startswith('{'):
            p=json.loads(request['user'])
            if p['role']=='notes':return 'Checked candidate. Preserve the exact pinned condition.'
            if p['role']=='answer':
                n=p['sources']['candidate']['length']
                return json.dumps({'patch':{'ticket':p['ticket'],'edits':[[n,n,'\nCHECKED: 2+2=4.']]}})
        return '{"halt_prob":0.2,"reason":"Scripted demonstration, not a proof judge."}'
    cfg=RecurseConfig.efficient(n=1,T=1,ladder=(Tier('local'),),
        seed_answer='PIN: arithmetic uses integers.',seed_scratchpad='Review the arithmetic.',
        max_total_calls=10,judge_can_halt=False,
        progress_checks=(ProgressCheck('pin','Preserve integer assumption',lambda t:t.startswith('PIN:'),True),))
    trace=recurse('Append a checked arithmetic observation without dropping the assumption.',
                  client=CallableClient(worker),config=cfg)
    assert trace.final_answer.endswith('CHECKED: 2+2=4.')
    assert trace.locked_checks==['pin']
    assert trace.total_calls==4
    print(trace.summary())


if __name__=='__main__':main()
