"""Bounded counterbalanced development pilots; no tuning between rounds."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import zipfile
from pilot_host import *
from fixtures import *


def snapshot(repo):
    head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip()
    subprocess.run(['git','merge-base','--is-ancestor',BASE,'HEAD'],cwd=repo,check=True,capture_output=True)
    if subprocess.check_output(['git','status','--porcelain'],cwd=repo,text=True).strip():raise RuntimeError('uncommitted engine')
    manifest=read_json(repo/'EXPORT_MANIFEST.json')
    for name,h in manifest['files'].items():
        if sha((repo/name).read_bytes())!=h:raise RuntimeError('manifest mismatch '+name)
    return {'head':head,'files':dict(manifest['files']),'manifest_sha256':sha((repo/'EXPORT_MANIFEST.json').read_bytes())}


def preflight(root):
    testdir=root/'harness-preflight';testdir.mkdir()
    (testdir/'service.py').write_text(CORRECT_MONEY+'\n'+GOLD_IMPORT,encoding='utf-8')
    test='from service import import_rows\n\ndef test_regression():\n    rows=[{"supplier_id":"s","transaction_id":"a","amount":"1"},{"supplier_id":"s","transaction_id":"b","amount":"1"}]\n    assert len(import_rows(rows)["rows"])==2\n'
    (testdir/'test_regression.py').write_text(test,encoding='utf-8')
    p=subprocess.run([sys.executable,'-I',str(Path(__file__).with_name('check_candidate.py')),str(testdir),'--private'],capture_output=True,text=True,encoding='utf-8',timeout=5)
    result=json.loads(p.stdout);assert result['all_passed'],result
    (testdir/'service.py').write_text(CORRECT_MONEY+'\n'+BUGGY_IMPORT,encoding='utf-8')
    p=subprocess.run([sys.executable,'-I',str(Path(__file__).with_name('check_candidate.py')),str(testdir)],capture_output=True,text=True,encoding='utf-8',timeout=5)
    buggy=json.loads(p.stdout);assert not buggy['all_passed'];assert not buggy['tests']['model_regression']
    for malicious in ['import os\ndef parse_cents(x): return 0\ndef import_rows(x): return []', 'def parse_cents(x):\n return open("x").read()\ndef import_rows(x): return []']:
        try:vet(malicious)
        except ValueError:pass
        else:raise AssertionError('test runner vet did not block unsupported source')
    save_json(root/'preflight.json',{'golden_fixture':result,'buggy_fixture':buggy,'no_model_called':True})


def grade_one(session,task,seed):
    result={'task':task,'session':session.name}
    calls=read_json(session/'calls.json',[]);states=read_json(session/'session_state.json',{})
    result.update(native_calls=len(calls),native_input=sum(c.get('usage',{}).get('prompt_tokens',0) for c in calls),
        native_output=sum(c.get('usage',{}).get('completion_tokens',0) for c in calls),
        native_tokens=sum(c.get('usage',{}).get('total_tokens',0) for c in calls),
        usage_complete=all('total_tokens' in c.get('usage',{}) for c in calls),
        model_seconds=sum(c.get('seconds',0) for c in calls),peak_native_input=max([c.get('usage',{}).get('prompt_tokens',0) for c in calls] or [0]),
        roles={role:sum(c['role']==role for c in calls) for role in sorted(set(c['role'] for c in calls))},
        pids=states.get('pids',[]),activation=read_json(session/'activation.json'))
    if task=='memory':
        memory=read_json(session/'memory-result.json',{'passed':False});result.update(task_passed=memory['passed'],memory=memory)
        g=memory.get('grade',{});result['recall_passed']=g.get('key_fields_correct') is True and g.get('scope_clean') is True
        result['application_passed']=g.get('indices_correct') is True and g.get('total_correct') is True
        retrieval=read_json(session/'retrieval-evidence.json',{})
        result['memory_features']={'records_retrieved':len(retrieval.get('records',[])),
            'selected_source_count':len(retrieval.get('sources',{})),
            'correction_exact_source_retrieved':any(EPISODES[1][1] in text for text in retrieval.get('sources',{}).values()),
            'masked_observations':sum(o.get('masked',False) for o in json.loads(retrieval.get('observations',{}).get('text','{}')).get('observations',[])),
            'source_bytes':retrieval.get('observations',{}).get('raw_chars',0),
            'consolidation_staged':bool(read_json(session/'consolidation.json',{}).get('staged'))}
    else:
        try:
            p=subprocess.run([sys.executable,'-I',str(Path(__file__).with_name('check_candidate.py')),str(session/'workspace'),'--private','--seed',str(seed+8000)],capture_output=True,text=True,encoding='utf-8',timeout=5)
            verdict=json.loads(p.stdout)
        except Exception as exc:verdict={'all_passed':False,'error':type(exc).__name__}
        # Does the model-authored regression actually fail on the original replay defect?
        probe=session/'regression-original-probe';probe.mkdir(exist_ok=True)
        (probe/'service.py').write_text(CORRECT_MONEY+'\n'+BUGGY_IMPORT,encoding='utf-8')
        try:
            (probe/'test_regression.py').write_bytes((session/'workspace'/'test_regression.py').read_bytes())
            p=subprocess.run([sys.executable,'-I',str(Path(__file__).with_name('check_candidate.py')),str(probe)],capture_output=True,text=True,encoding='utf-8',timeout=5)
            wrong=json.loads(p.stdout)
            control=session/'regression-correct-probe';control.mkdir(exist_ok=True)
            (control/'service.py').write_text(CORRECT_MONEY+'\n'+GOLD_IMPORT,encoding='utf-8')
            (control/'test_regression.py').write_bytes((session/'workspace'/'test_regression.py').read_bytes())
            p=subprocess.run([sys.executable,'-I',str(Path(__file__).with_name('check_candidate.py')),str(control)],capture_output=True,text=True,encoding='utf-8',timeout=5)
            correct=json.loads(p.stdout)
            from evaluation_utils import regression_useful
            useful=regression_useful(correct,wrong)
        except Exception:useful=False
        stages=[read_json(session/f'stage-{i}.json',{}) for i in (1,2)]
        from evaluation_utils import recovery_grade
        recovery=recovery_grade(stages,result['pids'],bool(verdict.get('all_passed')))
        restarted=recovery['recovery_passed'] if task=='restart' else True
        if task=='restart':result['recovery']=recovery
        result.update(task_passed=bool(verdict.get('all_passed') and useful and restarted),private_grade=verdict,
            regression_detects_original=useful,restart_verified=restarted,stages=stages,
            false_done_claim=bool(any(s.get('claimed_done') for s in stages) and not verdict.get('all_passed')),
            protected_readme_unchanged=(session/'workspace'/'README.md').read_text(encoding='utf-8')==SPEC)
    if task!='memory' and not result.get('protected_readme_unchanged'):
        result['task_passed']=False
    result['runtime_errors']=[read_json(p) for p in sorted(session.glob('process-complete-*.json')) if read_json(p).get('status')!='completed']
    if result['runtime_errors']:result['task_passed']=False
    save_json(session/'posthoc-grade.json',result)
    return result


def main():
    p=argparse.ArgumentParser();p.add_argument('--repo',required=True,type=Path);p.add_argument('--out',required=True,type=Path);p.add_argument('--rounds',type=int,choices=[1,2,3],default=1);p.add_argument('--tasks',choices=['coding','memory','restart','all'],default='coding');a=p.parse_args()
    root=a.out;root.mkdir(parents=True,exist_ok=False);source=snapshot(a.repo)
    for item in Path(__file__).parent.glob('*.py'):
        (root/item.name).write_bytes(item.read_bytes())
    preflight(root)
    lms=str(Path.home()/'.lmstudio/bin/lms.exe')
    records=json.loads(subprocess.check_output([lms,'ps','--json'],text=True,encoding='utf-8'))
    info=next(m for m in records if m['identifier']==MODEL)
    assert info['modelKey']=='lfm2-24b-a2b' and info['contextLength']==8192 and info['parallel']==1
    assert info['quantization']['name']=='Q4_K_M'
    save_json(root/'backend-before.json',info)
    schedule=[]
    for repeat,seed in enumerate((27201,27202,27203)[:a.rounds],1):
        for j,task in enumerate(('coding','memory','restart') if a.tasks=='all' else (a.tasks,)):
            for arm in (('off','on') if (repeat+j)%2 else ('on','off')):
                schedule.append(dict(repeat=repeat,seed=seed,task=task,arm=arm,name=f'r{repeat}-{task}-{arm}'))
    plan={'schema':1,'source':source,'schedule':schedule,'baseline':'same narrow edit-and-test host, persistent model-written project notes, bounded recent context and file-based resume; no RRE controller',
        'skill_on':'explicitly installed/host-dispatched skill plus repaired RRE structured controller; optional writer only for the memory task; exact observation masking and checked checkpoint/resume',
        'scope':'controlled synthetic repository/data pilot, not native Codex/Claude discovery, arbitrary shell autonomy, trained LightMem reproduction or population benchmark',
        'max_native_calls_per_session':MAX_CALLS,'native_token_admission_ceiling':MAX_NATIVE_TOKENS,'max_seconds_per_session':MAX_SECONDS,
        'coding_candidate_ceiling':4,'per_candidate_max_output':2400,'loaded_context':8192,'model':MODEL,'temperature':.1,'top_k':50,'repeat_penalty':1.05,
        'tasks_frozen':{'coding':SPEC,'memory_episodes':EPISODES,'memory_final':MEMORY_TASK,'restart':'same repair with first session parse_cents only, process termination after an eligible milestone then new-process resume'},
        'fairness':'same models/tools/public tests and native structured decoding; code public feedback shared; notes baseline retained; private grading only after every scheduled session; no human solving interventions',
        'deferred_cost':'staged consolidation counted in skill-on total; no automatic promotion/application of its unreviewed summaries',
        'incomplete_usage':'unknown output/native usage marked, never assigned measured zero',
        'files':{f.name:sha(f.read_bytes()) for f in root.glob('*.py')}}
    save_json(root/'plan.json',plan);frozen=sha((root/'plan.json').read_bytes());(root/'plan.sha256').write_text(frozen)
    print('FROZEN',root,frozen,'SESSIONS',len(schedule),flush=True)
    start=time.time();execution=[]
    for spec in schedule:
        session=root/spec['name'];session.mkdir();runstart=time.time()
        for phase in ([1,2] if spec['task']=='restart' else [1]):
            cmd=[sys.executable,'-B','-S',str(root/'session.py'),'--session',str(session),'--repo',str(a.repo),'--task',spec['task'],'--arm',spec['arm'],'--seed',str(spec['seed']),'--phase',str(phase)]
            with (session/f'process-{phase}.log').open('wb') as log:
                child=subprocess.Popen(cmd,stdout=log,stderr=subprocess.STDOUT,env=dict(os.environ,PYTHONIOENCODING='utf-8'))
                try:exitcode=child.wait(timeout=MAX_SECONDS+60)
                except subprocess.TimeoutExpired:child.kill();child.wait();exitcode=-999
            execution.append(dict(**spec,phase=phase,pid=child.pid,exitcode=exitcode,finished=time.time()))
            save_json(root/'execution.json',execution)
            print('PROCESS_FINISHED',spec['name'],'phase',phase,'exit',exitcode,flush=True)
            if phase==1 and spec['task']=='restart' and not read_json(session/'stage-1.json',{}).get('qualifying_milestone_reached'):
                print('NO_QUALIFYING_MILESTONE',spec['name'],flush=True);break
        save_json(session/'timing.json',{'session_seconds':time.time()-runstart})
        print('SESSION_FINISHED',spec['name'],'seconds',round(time.time()-runstart,2),flush=True)
    # No test policy changes, retries of whole sessions or new solving hints after inspection.
    assert frozen==sha((root/'plan.json').read_bytes());assert source==snapshot(a.repo)
    results=[]
    for spec in schedule:
        try:result=grade_one(root/spec['name'],spec['task'],spec['seed'])
        except Exception as exc:result={'task_passed':False,'grading_error':type(exc).__name__+': '+str(exc)}
        result.update(**spec);result.update(read_json(root/spec['name']/'timing.json',{}));results.append(result)
    save_json(root/'results.json',results)
    summary={}
    for arm in ('off','on'):
        rows=[r for r in results if r['arm']==arm];success=sum(r['task_passed'] for r in rows);tokens=sum(r.get('native_tokens',0) for r in rows)
        summary[arm]={'sessions':len(rows),'passed':success,'tokens':tokens,'calls':sum(r.get('native_calls',0) for r in rows),
            'tokens_per_success':tokens/success if success else None,'usage_complete':all(r.get('usage_complete',False) for r in rows),
            'wall_seconds':sum(r.get('session_seconds',0) for r in rows)}
    receipt={'schema':1,'plan_sha256':frozen,'engine_commit':source['head'],'source_unchanged':True,'three_rounds_complete':a.rounds==3 and a.tasks=='all' and len(results)==18,'planned_sessions':len(schedule),'all_scheduled_sessions_finished':len(results)==len(schedule),
        'sessions':results,'summary':summary,'suite_wall_seconds':time.time()-start,'human_solving_interventions':0,'repository_changed':False,
        'interpretation':'Post-repair development pilot with explicitly selected tasks and seed count. No claim of IID tasks, statistical significance, automatic skill discovery or general superiority.'}
    save_json(root/'verification.json',receipt)
    print('COMPLETE',wire(summary),flush=True)

if __name__=='__main__':main()
