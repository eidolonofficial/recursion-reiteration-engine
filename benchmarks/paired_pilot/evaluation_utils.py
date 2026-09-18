"""Small evaluation contracts; no model calls and no outcome repair."""
from contextlib import redirect_stdout, redirect_stderr

class Capture:
    def __init__(self,limit=8192):self.limit=limit;self.parts=[];self.count=0
    def write(self,text):
        left=max(0,self.limit-self.count)
        if left:self.parts.append(text[:left])
        self.count+=len(text)
        return len(text)
    def flush(self):pass
    def record(self):return {'text':''.join(self.parts),'characters':self.count,'truncated':self.count>self.limit}

def capture_report(check):
    out,err=Capture(),Capture()
    with redirect_stdout(out),redirect_stderr(err):report=check()
    report['program_stdout']=out.record();report['program_stderr']=err.record()
    return report

def regression_useful(correct,buggy):
    return (correct.get('tests',{}).get('model_regression') is True
            and buggy.get('tests',{}).get('model_regression') is False
            and buggy.get('errors',{}).get('model_regression','').startswith('AssertionError:'))

def recovery_grade(stages,pids,final_passed):
    first,second=(stages+[{},{}])[:2]
    def steps(s):return sum(s.get('completed_steps',[])) if 'completed_steps' in s else s.get('candidate_steps',0)
    resumed=second.get('resume_input') or {}
    qualified=first.get('qualifying_milestone_reached') is True
    restarted=len(set(pids))==2 and second.get('resumed') is True
    preserved=bool(qualified and first.get('answer_sha256') and
                   resumed.get('answer_sha256')==first['answer_sha256'])
    consumed=first.get('engine_calls',first.get('reserved_calls',0))
    budget=bool(preserved and resumed.get('calls',-1)>=consumed and resumed.get('steps',-1)>=steps(first))
    continued=bool(preserved and steps(second)>steps(first) and final_passed)
    return {'process_restarted':restarted,'qualifying_milestone_reached':qualified,
            'accepted_state_preserved':preserved,'budget_preserved':budget,
            'continued_work_correct':continued,
            'recovery_passed':bool(restarted and qualified and preserved and budget and continued)}
