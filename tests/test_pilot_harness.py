"""The grader must distinguish useful regressions and qualifying recovery."""
from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest
H=Path(__file__).resolve().parents[1]/'benchmarks'/'paired_pilot'
sys.path.insert(0,str(H))
from evaluation_utils import capture_report, regression_useful, recovery_grade
from fixtures import CORRECT_MONEY,GOLD_IMPORT,BUGGY_IMPORT

class HarnessTests(unittest.TestCase):
    def grade(self,code,test):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)
            (p/'service.py').write_text(CORRECT_MONEY+'\n'+code,encoding='utf-8')
            (p/'test_regression.py').write_text(test,encoding='utf-8')
            run=subprocess.run([sys.executable,'-I',str(H/'check_candidate.py'),str(p)],capture_output=True,text=True,encoding='utf-8',timeout=10)
            self.assertEqual(run.returncode,0,run.stderr)
            return json.loads(run.stdout)
    def test_stdout_does_not_contaminate_json(self):
        result=self.grade(GOLD_IMPORT,'from service import import_rows\ndef test_regression():\n    print("diagnostic only")\n    assert import_rows([])["rows"]==[]\n')
        self.assertTrue(result['all_passed'])
        self.assertEqual(result['program_stdout']['text'],'diagnostic only\n')
    def test_output_capture_is_bounded(self):
        def check():print('x'*10000);return {'ok':True}
        result=capture_report(check)
        self.assertEqual(len(result['program_stdout']['text']),8192)
        self.assertTrue(result['program_stdout']['truncated'])
    def test_recursive_test_is_not_bug_detection(self):
        test='def test_regression():\n    test_regression()\n'
        correct=self.grade(GOLD_IMPORT,test);buggy=self.grade(BUGGY_IMPORT,test)
        self.assertFalse(regression_useful(correct,buggy))
    def test_useful_regression_has_positive_and_negative_controls(self):
        test='from service import import_rows\ndef test_regression():\n    rows=[{"supplier_id":"s","transaction_id":x,"amount":"1"} for x in ("a","b")]\n    assert len(import_rows(rows)["rows"])==2\n'
        self.assertTrue(regression_useful(self.grade(GOLD_IMPORT,test),self.grade(BUGGY_IMPORT,test)))
    def test_restart_without_milestone_never_qualifies(self):
        stages=[{'stop_reason':'repeated-rejection'}, {'resumed':True}]
        result=recovery_grade(stages,[1,2],False)
        self.assertTrue(result['process_restarted'])
        self.assertFalse(result['recovery_passed'])
        self.assertFalse(result['qualifying_milestone_reached'])
    def test_recovery_requires_exact_state_budget_and_further_progress(self):
        first={'qualifying_milestone_reached':True,'answer_sha256':'exact','candidate_steps':1,'reserved_calls':2}
        second={'resumed':True,'candidate_steps':2,'resume_input':{'answer_sha256':'exact','calls':2,'steps':1}}
        self.assertTrue(recovery_grade([first,second],[1,2],True)['recovery_passed'])
        for field,value in [('answer_sha256','stale'),('calls',0),('steps',0)]:
            changed=dict(second,resume_input=dict(second['resume_input'],**{field:value}))
            self.assertFalse(recovery_grade([first,changed],[1,2],True)['recovery_passed'])
        self.assertFalse(recovery_grade([first,dict(second,candidate_steps=1)],[1,2],True)['recovery_passed'])
    def test_actual_separate_process_recovery_preflight(self):
        result=subprocess.run([sys.executable,'-I',str(H/'preflight_engine.py')],capture_output=True,text=True,encoding='utf-8',timeout=60)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('RECOVERY_PASS off',result.stdout)
        self.assertIn('RECOVERY_PASS on',result.stdout)
