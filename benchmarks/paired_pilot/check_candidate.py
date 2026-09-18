"""Reviewed subprocess test runner. Application-level constraints, not an OS sandbox."""
import argparse
import importlib.util
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from fixtures import vet, reference_rows, PUBLIC_CASES, MONEY_PUBLIC, private_cases


def load(directory):
    code=(directory/'service.py').read_text(encoding='utf-8')
    tests=(directory/'test_regression.py').read_text(encoding='utf-8')
    vet(code);vet(tests,test=True)
    spec=importlib.util.spec_from_file_location('service',directory/'service.py')
    service=importlib.util.module_from_spec(spec);sys.modules['service']=service;spec.loader.exec_module(service)
    spec=importlib.util.spec_from_file_location('test_regression',directory/'test_regression.py')
    regression=importlib.util.module_from_spec(spec);spec.loader.exec_module(regression)
    return service,regression


def _evaluate(directory, private=False, seed=99173):
    flags={};details={}
    try:service,regression=load(directory)
    except Exception as exc:return {'syntax':False,'tests':{},'errors':{'load':type(exc).__name__+': '+str(exc)[:300]}}
    def attempt(name,fn):
        try:fn();flags[name]=True
        except Exception as exc:flags[name]=False;details[name]=type(exc).__name__+': '+str(exc)[:300]
    def money(value):
        result=service.parse_cents(value)
        rows=reference_rows([{'supplier_id':'s','transaction_id':'t','amount':value}])
        assert type(result)is int and result==rows['total_cents'],f'wrong exact cents for {value!r}: {result!r}'
    def invalid_money(value):
        try:service.parse_cents(value)
        except ValueError:return
        raise AssertionError('invalid amount was not rejected')
    def batch(rows):
        before=json.dumps(rows,sort_keys=True);actual=service.import_rows(rows)
        expected=reference_rows(json.loads(before))
        assert actual==expected,'retained rows or total differ from task contract'
        assert json.dumps(rows,sort_keys=True)==before,'input was mutated'
    for i,value in enumerate(MONEY_PUBLIC):attempt(f'money_{i}',lambda value=value:money(value))
    for name,rows in PUBLIC_CASES:attempt(name,lambda rows=rows:batch(json.loads(json.dumps(rows))))
    attempt('model_regression',regression.test_regression)
    if private:
        for value in ['900719925474099.91','-0.01','0002.01','+0.9','42','  -100  ']:
            attempt('exact_'+value,lambda value=value:money(value))
        for i,value in enumerate(['1.234','1.','1e2','nan','--1','',True,2.5,None]):
            attempt('invalid_'+str(i),lambda value=value:invalid_money(value))
        for name,rows in private_cases(seed):attempt(name,lambda rows=rows:batch(rows))
    return {'syntax':True,'tests':flags,'errors':details,'passed':sum(flags.values()),'count':len(flags),'all_passed':all(flags.values())}

def evaluate(directory, private=False, seed=99173):
    from evaluation_utils import capture_report
    return capture_report(lambda: _evaluate(directory, private, seed))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('directory',type=Path);p.add_argument('--private',action='store_true');p.add_argument('--seed',type=int,default=99173)
    a=p.parse_args();print(json.dumps(evaluate(a.directory,a.private,a.seed),sort_keys=True))
