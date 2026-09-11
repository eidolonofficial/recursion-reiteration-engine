"""Paired fresh-response evaluation seam; no predetermined response replay.

The operator supplies the actual local client and answer verifier. This runner
reports task success and total visible token units including failures. It does
not call statistical promotion from a small or dependent case bank.
"""
from __future__ import annotations
from dataclasses import dataclass
import time
from .clients import CallResult
from .compression import TokenMeter
from .memory.contracts import digest, bounded_text, wire


@dataclass(frozen=True)
class EvaluationCase:
    key: str
    task: str
    full_context: str
    reduced_context: str
    full_preparation_units: int = 0
    reduced_preparation_units: int = 0

    def __post_init__(self):
        for value in (self.full_preparation_units,self.reduced_preparation_units):
            if type(value)is not int or not 0<=value<=1000000000:raise ValueError('invalid preparation accounting')
        bounded_text(self.key,'case key',200)
        bounded_text(self.task,'task',16000)
        bounded_text(self.full_context,'full context',1000000,empty=True)
        bounded_text(self.reduced_context,'reduced context',1000000,empty=True)


def evaluate(cases, *, client, verifier, model, backend_kind, backend_identity,
             counter=None, counter_label=None, max_tokens=512, repeats=1):
    if backend_kind not in {'local-neural','deterministic-test'}:raise ValueError('declare actual backend kind')
    bounded_text(backend_identity,'backend identity',200)
    if type(repeats)is not int or not 1<=repeats<=10:raise ValueError('invalid repeats')
    if type(max_tokens)is not int or max_tokens<1:raise ValueError('invalid output allowance')
    if not callable(verifier) or not callable(getattr(client,'complete',None)):raise TypeError('client and verifier required')
    cases=list(cases)
    if not cases or len(cases)>1000 or any(not isinstance(c,EvaluationCase) for c in cases):raise ValueError('invalid cases')
    if len({c.key for c in cases})!=len(cases):raise ValueError('duplicate case IDs')
    meter=TokenMeter(counter,counter_label);rows=[]
    for i,c in enumerate(cases):
        for repeat in range(repeats):
            # Counterbalance order; this does not itself establish IID sampling.
            for arm in (('full','reduced') if (i+repeat)%2==0 else ('reduced','full')):
                system='Answer the exact task using the supplied context. State uncertainty when evidence is absent.'
                user=wire({'task':c.task,'context':c.full_context if arm=='full' else c.reduced_context})
                row={'case':c.key,'arm':arm,'repeat':repeat,'input':meter.prompt(system,user,model),'output':0,
                     'preparation':(c.full_preparation_units if arm=='full' else c.reduced_preparation_units) if repeat==0 else 0,
                     'checked_success':False,'request_hash':digest([system,user]),'status':'attempted'}
                start=time.monotonic()
                try:
                    result=client.complete(model=model,system=system,user=user,max_tokens=max_tokens,
                                           temperature=0.0,use_headroom=False)
                    if not isinstance(result,CallResult):raise TypeError('invalid model result')
                    row['output']=meter.count(result.text,model)
                    row['response_hash']=digest(result.text)
                    if row['output']>max_tokens or result.stop_reason in {'length','max_tokens','error','refusal','refused'}:
                        raise ValueError('incomplete result')
                    passed=verifier(c,result.text)
                    if type(passed)is not bool:raise TypeError('verifier must return bool')
                    row['checked_success']=passed;row['status']='checked'
                except Exception as exc:row['status']=type(exc).__name__
                row['seconds']=time.monotonic()-start;rows.append(row)
    summary={}
    for arm in ('full','reduced'):
        r=[row for row in rows if row['arm']==arm];success=sum(row['checked_success'] for row in r)
        units=sum(row['input']+row['output']+row['preparation'] for row in r)
        summary[arm]={'attempts':len(r),'checked_successes':success,'all_visible_units':units,
                      'unobserved_output_attempts':sum('response_hash' not in row for row in r),
                      'infrastructure_or_format_failures':sum(row['status']!='checked' for row in r),
                      'preparation_units':sum(row['preparation'] for row in r),
                      'units_per_checked_success':units/success if success else None}
    pairs=[]
    for case in cases:
        for repeat in range(repeats):
            arms={r['arm']:r for r in rows if r['case']==case.key and r['repeat']==repeat}
            full,reduced=arms['full'],arms['reduced']
            pairs.append({'case':case.key,'repeat':repeat,
                'full_success':full['checked_success'],'reduced_success':reduced['checked_success'],
                'regression':full['checked_success'] and not reduced['checked_success'],
                'gain':reduced['checked_success'] and not full['checked_success']})
    gate={'scope':'finite paired regression screen, not statistical promotion',
          'regressions':sum(p['regression'] for p in pairs),
          'incomplete_attempts':sum(r['status']!='checked' for r in rows)}
    gate['passed']=gate['regressions']==0 and gate['incomplete_attempts']==0 and all(p['reduced_success'] for p in pairs)
    return {'schema':1,'paired':pairs,'regression_gate':gate,
            'accounting_complete':all('response_hash' in r for r in rows),
            'backend_kind':backend_kind,'backend_identity':backend_identity,'model':model,
            'counter':meter.label,'rows':rows,'summary':summary,'population_claim':False,
            'preparation_scope':'Host-supplied measured context-preparation units are counted once per case; unspecified preparation is zero, not measured free.',
            'scope':'Fresh callback executions. Neural status is an operator attestation, not detected from response text.'}
