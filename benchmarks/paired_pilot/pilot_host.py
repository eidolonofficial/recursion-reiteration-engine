"""Shared local benchmark host and native inference accounting."""
import ast
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from dataclasses import asdict
from fixtures import vet, SPEC, CORRECT_MONEY, BUGGY_MONEY, BUGGY_IMPORT

BASE='d8de4ccb4a3cb8e6c14486ab9f52caf36e2a40bd'  # reviewed ancestor; manifest freezes the repaired tree
MODEL='rre-lfm-real-pilot'
MAX_CALLS=32
MAX_NATIVE_TOKENS=36000
MAX_SECONDS=1200

def wire(obj):return json.dumps(obj,ensure_ascii=False,separators=(',',':'),allow_nan=False)
def sha(text):return hashlib.sha256(text.encode('utf-8') if isinstance(text,str) else text).hexdigest()
def read_json(path,default=None):return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default
def save_json(path,obj):path.write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
def closed(props):return {'type':'object','properties':props,'required':list(props),'additionalProperties':False}
def string(n=800):return {'type':'string','maxLength':n}
def array(item,n=4):return {'type':'array','items':item,'maxItems':n}
CODE_SCHEMA=closed({'code':string(6200),'regression_test':string(2500),'claimed_done':{'type':'boolean'}})
MEMORY_SCHEMA=closed({'key_fields':array(string(48),3),'kept_indices':array({'type':'integer','minimum':0,'maximum':4},5),'total_cents':{'type':'integer'},'source_explanation':string(400)})
NOTE_SCHEMA=closed({'note':string(900)})
BOOT_SCHEMA=closed({'tool':{'type':'string','enum':['recursion-reiteration-engine','direct']},'mode':{'type':'string','enum':['structured']}})


def role_schema(role,user):
    p=json.loads(user)
    if role=='controller':
        query=closed({'text':string(1000),'tags':array(string(40),3),'after':{'type':'null'},'before':{'type':'null'}})
        return closed({'queries':array(query,min(2,p['max_queries']))}),192
    if role=='selector':
        ids=[x['id'] for x in p['candidates']]
        return closed({'keep':array({'type':'string','enum':ids},p['K'])}),256
    props={'key':string(120),'summary':string(480),'kind':{'type':'string','enum':['fact','decision','constraint','failure','hypothesis','procedure','observation']},'tags':array(string(40),3)}
    if role=='consolidator':props['entries']=array({'type':'string','enum':[e['id'] for e in p['entries']]},4)
    return closed({'items':array(closed(props),2)}),512


class NativeClient:
    """Only explicit localhost calls; roles remain real LFM calls and are metered."""
    def __init__(self,session,repo,seed):
        sys.path.insert(0,str(repo/'src'))
        from headroom_recursion.lmstudio_client import LMStudioClient
        self.backend=LMStudioClient(port=1234,timeout_s=240)
        self.session=session;self.repo=repo;self.seed=seed
        self.calls=read_json(session/'calls.json',[])
        self.started=read_json(session/'session_state.json',{}).get('started',time.time())
        self.phase='startup';self.pause=None
    def role(self,system):
        from headroom_recursion.memory.pipeline import PROMPTS
        return next((k for k,v in PROMPTS.items() if system==v),'worker')
    def check_schema(self,model,schema):return self.backend.check_schema(model,schema)
    def complete(self, *, model,system,user,max_tokens=1024,temperature=0.1,use_headroom=False,response_schema=None):
        from headroom_recursion.clients import CallResult
        from headroom_recursion.runtime import BudgetExhausted
        role=self.role(system)
        if self.pause and role=='worker' and self.pause():
            raise KeyboardInterrupt('predeclared checkpoint-boundary interruption')
        if any(type(c.get('usage')) is not dict or
               type(c['usage'].get('total_tokens')) is not int for c in self.calls):
            raise BudgetExhausted('prior inference usage is unknown; no free retry')
        known=sum(c['usage']['total_tokens'] for c in self.calls)
        if len(self.calls)>=MAX_CALLS or known>=MAX_NATIVE_TOKENS or time.time()-self.started>=MAX_SECONDS:
            raise BudgetExhausted('shared session budget exhausted')
        if response_schema is None and role!='worker':response_schema,max_tokens=role_schema(role,user)
        if response_schema is not None:self.check_schema(model,response_schema)
        body={'model':model,'messages':[{'role':'system','content':system},{'role':'user','content':user}],
              'temperature':0.1,'top_k':50,'top_p':1.0,'repeat_penalty':1.05,'seed':self.seed,
              'max_tokens':max_tokens,'stream':False}
        if response_schema is not None:body['response_format']={'type':'json_schema','json_schema':{'name':'pilot_response','strict':True,'schema':response_schema}}
        before=self.backend.loaded_model(model)
        row={'index':len(self.calls)+1,'pid':os.getpid(),'phase':self.phase,'role':role,'request':body,'status':'attempted','started':time.time()}
        self.calls.append(row);save_json(self.session/'calls.json',self.calls)
        start=time.monotonic()
        try:
            value=self.backend._request('POST','/v1/chat/completions',body)
            row['raw_response']=value
            if self.backend.loaded_model(model)!=before:raise RuntimeError('model configuration changed')
            choice=value['choices'][0];message=choice['message'];text=message.get('content')
            row.update(usage=value.get('usage',{}),response=text,stop_reason=choice.get('finish_reason'),status='returned')
            if type(text)is not str or message.get('refusal'):raise RuntimeError('no usable response')
            return CallResult(text,stop_reason=choice.get('finish_reason','error'),usage={k:v for k,v in value.get('usage',{}).items() if type(v) is int})
        except BaseException as exc:row['status']=type(exc).__name__;row['error']=str(exc)[:200];raise
        finally:
            row['seconds']=time.monotonic()-start;save_json(self.session/'calls.json',self.calls)
            print(wire({'session':self.session.name,'phase':self.phase,'call':row['index'],'role':role,'status':row['status'],'seconds':round(row['seconds'],2),'tokens':row.get('usage',{}).get('total_tokens')}),flush=True)
    def send_role(self,**q):
        q.pop('role',None)
        return self.complete(**q)


class TestBroker:
    def __init__(self,session,fixture_root):self.session=session;self.fixture_root=fixture_root;self.cache={};self.events=read_json(session/'tool_events.json',[]);self.money_seen=False;self.ledger=None;self.pending=[]
    def event(self,kind,**data):self.events.append({'event':kind,'pid':os.getpid(),**data});save_json(self.session/'tool_events.json',self.events)
    def decode(self,answer):
        from headroom_recursion.response_schema import parse_payload
        obj=parse_payload(answer,CODE_SCHEMA);vet(obj['code']);vet(obj['regression_test'],True)
        if getattr(self,'phase1_only',False):
            node=next(n for n in ast.parse(obj['code']).body if isinstance(n,ast.FunctionDef) and n.name=='import_rows')
            if ast.get_source_segment(obj['code'],node)!=BUGGY_IMPORT.strip():
                raise ValueError('stage one may change parse_cents, not import_rows')
        return obj
    def syntax(self,answer):
        try:self.decode(answer);return True
        except Exception:return False
    def check(self,answer):
        key=sha(answer)
        if key in self.cache:return self.cache[key]
        try:obj=self.decode(answer)
        except Exception as exc:
            result={'syntax':False,'tests':{},'errors':{'schema_or_source':str(exc)[:200]},'all_passed':False,'passed':0};self.cache[key]=result;return result
        target=self.session/'proposals'/key;target.mkdir(parents=True,exist_ok=True)
        (target/'service.py').write_text(obj['code'],encoding='utf-8');(target/'test_regression.py').write_text(obj['regression_test'],encoding='utf-8')
        start=time.monotonic()
        try:
            p=subprocess.run([sys.executable,'-I',str(self.fixture_root/'check_candidate.py'),str(target)],capture_output=True,text=True,encoding='utf-8',timeout=5,cwd=target)
            result=json.loads(p.stdout) if p.returncode==0 else {'syntax':False,'tests':{},'errors':{'subprocess':p.stderr[-300:]}}
        except Exception as exc:result={'syntax':False,'tests':{},'errors':{'execution':type(exc).__name__}}
        result.setdefault('all_passed',False);result.setdefault('passed',0)
        save_json(target/'public_result.json',result);self.cache[key]=result
        self.money_seen |= all(result.get('tests',{}).get('money_'+str(i),False) for i in range(3))
        self.event('public_tests',candidate=key,seconds=time.monotonic()-start,result=result)
        if self.ledger:
            output=wire(result)
            oid=self.ledger.record('public tests',output,status='success' if result['all_passed'] else 'failure',revision=key,exit_code=0 if result['all_passed'] else 1,failed_tests=len([v for v in result.get('tests',{}).values() if not v]),outcome='Review exact test result; private grading is separate.')
            if result['all_passed']:
                ref=self.ledger.store.add_source(self.ledger.principal,output)
                for old in self.pending:self.ledger.resolve(old,resolution_source=ref)
                self.pending=[]
            else:self.pending.append(oid)
        return result
    def feedback(self,answer):return wire(self.check(answer))
    def milestone(self,answer):
        try:
            obj=self.decode(answer)
            tree=ast.parse(obj['code'])
            node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='import_rows')
            return self.money(answer) and ast.get_source_segment(obj['code'],node)==BUGGY_IMPORT.strip()
        except Exception:return False
    def money(self,answer):return all(self.check(answer).get('tests',{}).get('money_'+str(i),False) for i in range(3))
    def objective(self,answer):return float(self.check(answer)['passed'])
    def all_passed(self,answer):return self.check(answer)['all_passed']
    def commit(self,answer):
        obj=self.decode(answer);work=self.session/'workspace'
        (work/'service.py').write_text(obj['code'],encoding='utf-8');(work/'test_regression.py').write_text(obj['regression_test'],encoding='utf-8')
        self.event('commit_artifact',candidate=sha(answer),service_sha256=sha(obj['code']),regression_sha256=sha(obj['regression_test']))
