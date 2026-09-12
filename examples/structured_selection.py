"""Run the finite task with an explicit local model or the existing exact solver."""
from __future__ import annotations
import argparse
import json
import time
from dataclasses import replace
from headroom_recursion import RecurseConfig, recurse
from headroom_recursion.progress import ProgressCheck
from project_selection import ROWS, REQUIRES, CONFLICTS, check, reference

SCHEMA = {'type':'object','properties':{'selected':{'type':'array',
    'items':{'type':'string','enum':[r[0] for r in ROWS]},'maxItems':len(ROWS)}},
    'required':['selected'],'additionalProperties':False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--model', help='exact identifier already loaded in LM Studio')
    mode.add_argument('--exact', action='store_true', help='Python enumeration; no model call')
    parser.add_argument('--port', type=int, default=1234)
    args = parser.parse_args()
    started = time.monotonic()
    oracle = reference()  # Never transmitted to the model.
    if args.exact:
        witness = oracle['witnesses'][0]
        print(json.dumps({'mode':'solver-assisted','model_calls':0,**oracle,
                          'checked_witness':check(json.dumps({'selected':witness['selected']})),
                          'seconds':time.monotonic()-started}, indent=2))
        return
    from headroom_recursion.lmstudio_client import LMStudioClient
    task = ('Maximize total value. Return only an object with a selected array of unique labels.\n'
        'PROJECTS [label,cost,crew,value]: '+json.dumps(ROWS)+'\n'
        'Total cost <= 24; total crew <= 12. At least one of C,E,K is required.\n'
        'REQUIRES: '+json.dumps(REQUIRES)+'\nEXCLUDED PAIRS: '+json.dumps(CONFLICTS))
    cfg = RecurseConfig.structured(SCHEMA, model=args.model, workload='research', rungs=6,
        verification_id='finite-twelve-projects-v1', temperature=0,
        validator=lambda a:check(a)['feasible'] and check(a)['value']==oracle['optimum'],
        objective=lambda a:check(a)['value'],
        candidate_identity=lambda a:json.dumps(sorted(json.loads(a)['selected'])),
        feedback=lambda a:json.dumps({'proposal':json.loads(a),'check':check(a)}),
        progress_checks=(ProgressCheck('feasible','All task constraints hold.',
                                     lambda a:check(a)['feasible'],required=True),),
        max_total_calls=12,max_wall_seconds=180)
    cfg.ladder = tuple(replace(t,max_tokens=128) for t in cfg.ladder)
    trace = recurse(task, client=LMStudioClient(args.port), config=cfg)
    print(json.dumps({'mode':'model-proposal','stop_reason':trace.stop_reason,
        'model_calls':trace.total_calls,'candidate_steps':len(trace.steps),
        'answer':trace.final_answer,'checked':check(trace.final_answer),
        'best_feasible_value':trace.best_objective,'optimal':trace.halted and trace.stop_reason=='validated',
        'native_usage':[e.get('native_usage') for e in trace.call_events],
        'seconds':time.monotonic()-started}, indent=2))


if __name__ == '__main__':
    main()
