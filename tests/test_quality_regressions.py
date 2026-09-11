"""Equal aggregate successes must not hide matched compression regressions."""
import json
import unittest
from headroom_recursion.clients import CallResult
from headroom_recursion.quality_eval import EvaluationCase, evaluate

class Client:
    def __init__(self, fn):self.fn=fn
    def complete(self, **q):return self.fn(json.loads(q['user']))

class QualityRegressionTests(unittest.TestCase):
    def run_cases(self,cases,fn):
        return evaluate(cases,client=Client(fn),verifier=lambda c,t:t=='correct',
            model='test',backend_kind='deterministic-test',backend_identity='test-only',
            counter=lambda t,m:len(t),counter_label='Unicode characters',max_tokens=100)

    def test_equal_totals_do_not_cancel_a_regression(self):
        cases=[EvaluationCase('a','a','full-a','reduced-a'),EvaluationCase('b','b','full-b','reduced-b')]
        report=self.run_cases(cases,lambda q:CallResult('correct' if q['context'] in {'full-a','reduced-b'} else 'wrong'))
        self.assertEqual(report['summary']['full']['checked_successes'],1)
        self.assertEqual(report['summary']['reduced']['checked_successes'],1)
        self.assertEqual(report['regression_gate']['regressions'],1)
        self.assertFalse(report['regression_gate']['passed'])
        self.assertTrue(report['accounting_complete'])
        self.assertEqual([r['case'] for r in report['paired'] if r['regression']],['a'])

    def test_timeout_is_not_measured_zero_cost(self):
        def fn(q):
            if q['context']=='full':raise TimeoutError('unobserved backend output')
            return CallResult('correct')
        report=self.run_cases([EvaluationCase('a','task','full','reduced')],fn)
        self.assertFalse(report['accounting_complete'])
        self.assertFalse(report['regression_gate']['passed'])
        self.assertEqual(report['regression_gate']['incomplete_attempts'],1)
        self.assertEqual(report['summary']['full']['unobserved_output_attempts'],1)
        self.assertGreater(report['summary']['full']['all_visible_units'],0)
        self.assertIsNone(report['summary']['full']['units_per_checked_success'])

    def test_passing_finite_screen_has_no_population_authority(self):
        report=self.run_cases([EvaluationCase('a','task','full','reduced')],lambda q:CallResult('correct'))
        self.assertTrue(report['regression_gate']['passed'])
        self.assertTrue(report['accounting_complete'])
        self.assertFalse(report['population_claim'])
        self.assertIn('not statistical promotion',report['regression_gate']['scope'])

if __name__=='__main__':unittest.main()
