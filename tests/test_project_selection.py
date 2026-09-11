"""Python computes totals and checks every condition of the finite example."""
import json
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'examples'))
from project_selection import check, reference

class ProjectSelectionTests(unittest.TestCase):
    def test_exhaustive_finite_reference(self):
        r = reference()
        self.assertEqual((r['examined'], r['feasible'], r['optimum']), (4096, 99, 67))

    def test_previous_bad_model_proposal(self):
        r = check('{"selected":["A","B","C","E","I","K"]}')
        self.assertFalse(r['feasible'])
        self.assertEqual((r['cost'], r['crew'], r['value']), (36, 18, 98))
        self.assertEqual(r['missing'], [['I','H'], ['K','H']])

    def test_worker_cannot_supply_totals_or_duplicate_labels(self):
        for value in [{'selected':['A'], 'value':1000}, {'selected':['A','A']}, {'selected':[True]}]:
            self.assertFalse(check(json.dumps(value))['feasible'])

    def test_coverage_and_conflicts(self):
        self.assertFalse(check('{"selected":["A"]}')['feasible'])
        self.assertIn(['C','J'], check('{"selected":["A","C","J"]}')['conflicts'])
