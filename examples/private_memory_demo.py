"""Offline private-memory demonstration. No neural model, network or shared data."""
from __future__ import annotations
import json
import tempfile
from pathlib import Path
from headroom_recursion import RecurseConfig,recurse
from headroom_recursion.clients import CallableClient
from headroom_recursion.memory import MemoryStore,MemorySession,Principal,ObservationLedger


def main():
    with tempfile.TemporaryDirectory(prefix='private-memory-demo-') as directory:
        with MemoryStore(Path(directory)/'memory.sqlite') as store:
            principal=Principal('demo-user','demo-project')
            source=store.add_source(principal,'Use integers; do not remove this assumption.')
            store.write(principal,key='integer-assumption',summary='Use integers; do not remove this assumption.',
                        kind='constraint',sources=[source],pinned=True)
            session=MemorySession(store,principal)
            ledger=ObservationLedger(store,principal)
            raw='PASS exact arithmetic test\n'*1000
            ledger.record('arithmetic-tests',raw,status='success',revision='demo-v1',exit_code=0,failed_tests=0,
                          outcome='All constructed integer cases passed; no universal research claim.')
            observation=ledger.view(revision='demo-v1')
            def worker(**request):
                if request['user'].startswith('{'):
                    packet=json.loads(request['user'])
                    if packet['role']=='notes':
                        assert 'do not remove this assumption.' in packet['memory_advice']
                        return 'Preserve integer assumption and exact evidence.'
                    if packet['role']=='answer':
                        n=packet['sources']['candidate']['length']
                        return json.dumps({'patch':{'ticket':packet['ticket'],'edits':[[n,n,'\nFINITE: 2+2=4.']]}})
                return '{"halt_prob":0.2,"reason":"Constructed fixture; not a neural judge."}'
            cfg=RecurseConfig.for_workload('research',model='deterministic-demo',n=1,budget=8000,
                memory_session=session,observation_ledger=ledger,verification_id='demo-v1',
                seed_answer='ASSUMPTION: integers.',max_total_calls=10)
            trace=recurse('Preserve the integer assumption; add one exact finite observation.',
                          client=CallableClient(worker),config=cfg)
            assert trace.final_answer.endswith('FINITE: 2+2=4.')
            assert not trace.halted and store.audit()
            print(json.dumps({'scope':'Constructed offline fixture, not neural quality evidence',
                'full_success_log_characters':len(raw),'bounded_observation_view_characters':len(observation['text']),
                'calls':trace.total_calls,'memory_records':len(store.candidates(principal)),
                'counter':trace.token_count_kind,'source_retained_exactly':raw in observation['sources'].values(),
                'final_answer':trace.final_answer},indent=2))


if __name__=='__main__':main()
