"""Two real processes with scripted proposals; not a neural quality result."""
from pathlib import Path
import argparse,json,subprocess,sys,tempfile
H=Path(__file__).resolve().parent;R=H.parents[1]
sys.path.insert(0,str(H));sys.path.insert(0,str(R/'src'))
from session import run_code
from fixtures import CORRECT_MONEY,GOLD_IMPORT,BUGGY_IMPORT,SPEC
from pilot_host import wire
from evaluation_utils import recovery_grade
from headroom_recursion.clients import CallResult

class Fake:
    def __init__(self,phase):self.number=phase;self.phase=phase;self.pause=None;self.calls=[]
    def check_schema(self,*args):return True
    def complete(self,**q):
        if self.pause and self.pause():raise KeyboardInterrupt()
        self.calls.append({'phase':self.phase,'role':'worker'})
        test='from service import parse_cents\ndef test_regression():\n    assert parse_cents("0.29")==29\n'
        if self.number==2:
            test='from service import import_rows\ndef test_regression():\n    rows=[{"supplier_id":"s","transaction_id":x,"amount":"1"} for x in ("a","b")]\n    assert len(import_rows(rows)["rows"])==2\n'
        return CallResult(wire({'code':CORRECT_MONEY+'\n'+(BUGGY_IMPORT if self.number==1 else GOLD_IMPORT),
                               'regression_test':test,'claimed_done':self.number==2}),stop_reason='stop')
    def send_role(self,**q):q.pop('role',None);return self.complete(**q)

def main():
    p=argparse.ArgumentParser();p.add_argument('--phase',type=int,choices=[1,2])
    p.add_argument('--arm',choices=['on','off']);p.add_argument('--directory',type=Path);a=p.parse_args()
    if a.phase:
        run_code(a.directory,Fake(a.phase),R,'restart',a.arm,a.phase)
        return
    with tempfile.TemporaryDirectory() as directory:
        for arm in ('off','on'):
            d=Path(directory)/arm;d.mkdir();(d/'workspace').mkdir()
            (d/'workspace'/'README.md').write_text(SPEC,encoding='utf-8')
            stages=[]
            for phase in (1,2):
                child=subprocess.run([sys.executable,'-I',str(Path(__file__).resolve()),
                    '--phase',str(phase),'--arm',arm,'--directory',str(d)],capture_output=True,text=True,encoding='utf-8',timeout=25)
                assert child.returncode==0,child.stdout+child.stderr
                stage=json.loads((d/f'stage-{phase}.json').read_text(encoding='utf-8'));stages.append(stage)
                if phase==1:assert stage['qualifying_milestone_reached'],stage
            grade=subprocess.run([sys.executable,'-I',str(H/'check_candidate.py'),str(d/'workspace'),'--private'],capture_output=True,text=True,encoding='utf-8',timeout=10)
            assert grade.returncode==0,grade.stderr
            result=recovery_grade(stages,[s['pid'] for s in stages],json.loads(grade.stdout)['all_passed'])
            assert result['recovery_passed'],result
            print('RECOVERY_PASS',arm,json.dumps(result))

if __name__=='__main__':main()
