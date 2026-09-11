import json
import math
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from headroom_recursion import CallResult, CallableClient, RecurseConfig, Tier, Verdict, recurse, plan_schedule
from headroom_recursion import demo, halting, prompts, trm
from headroom_recursion.trace import RunTrace
from headroom_recursion.retrieval import CorpusRetriever
from headroom_recursion import claims


def score(value):
    return json.dumps({"halt_prob": value, "reason": "test score"})


class Scripted:
    def __init__(self, values):
        self.values = iter(values)
        self.requests = []

    def complete(self, **request):
        self.requests.append(request)
        value = next(self.values)
        if isinstance(value, BaseException):
            raise value
        return value if isinstance(value, CallResult) else CallResult(value)


class CoreTests(unittest.TestCase):
    def run_case(self, values, **config):
        worker = Scripted(values)
        # These legacy wire-sequence regressions intentionally disable the new
        # seed/planning calls. The default enforced path is tested separately.
        options = dict(enforce_progress=False, preseed_ladder=False)
        options.update(config)
        cfg = RecurseConfig(n=1, T=1, **options)
        return recurse("test task", client=worker, config=cfg), worker

    def test_default_recurrence(self):
        cfg = RecurseConfig()
        self.assertEqual((cfg.n, cfg.T), (6, 3))
        self.assertEqual(cfg.ladder, (Tier("local"),))
        self.assertIn("maximum including judge retries: 27", plan_schedule(cfg))

    def test_operation_order_and_state(self):
        worker = Scripted(["note-one", "note-two", "candidate", score(.2)])
        result = recurse("task", client=worker, config=RecurseConfig(n=2, T=1))
        self.assertEqual([r["system"] for r in worker.requests],
                         [prompts.LATENT_SYSTEM, prompts.LATENT_SYSTEM, prompts.ANSWER_SYSTEM, prompts.HALT_SYSTEM])
        self.assertIn("note-one", worker.requests[1]["user"])
        self.assertIn("note-two", worker.requests[2]["user"])
        self.assertEqual(result.total_calls, 4)
        self.assertEqual(result.steps[0].scratchpad, "note-two")

    def test_validated_short_circuits_judge(self):
        result, _ = self.run_case(["note", "4"], validator=lambda answer: answer == "4")
        self.assertEqual((result.stop_reason, result.total_calls), ("validated", 2))
        self.assertFalse(result.needs_human_review)

    def test_judged_halt_is_not_proof(self):
        result, _ = self.run_case(["note", "answer", score(.95)])
        self.assertEqual(result.stop_reason, "halt")
        self.assertTrue(result.needs_human_review)

    def test_failed_sufficient_check_delegates_without_validation(self):
        result, _ = self.run_case(["note", "answer", score(.95)], validator=lambda a: False)
        self.assertEqual(result.stop_reason, "halt")
        self.assertTrue(result.needs_human_review)

    def test_gate_pass_cannot_validate(self):
        result, _ = self.run_case(["note", "answer", score(.95)],
                                  validator=lambda a: True, oracle_sufficient=False)
        self.assertEqual(result.stop_reason, "halt")
        self.assertTrue(result.needs_human_review)

    def test_gate_rejection_skips_judge(self):
        result, _ = self.run_case(["note", "wrong"], validator=lambda a: False, oracle_sufficient=False)
        self.assertFalse(result.halted)
        self.assertEqual(result.total_calls, 2)
        self.assertTrue(result.steps[0].gate_rejected)
        self.assertEqual(result.best_step_index, -1)

    def test_broken_gate_is_not_a_mechanical_rejection(self):
        def broken(answer):
            raise OSError("unavailable")
        result, _ = self.run_case(["note", "answer", score(.2)], validator=broken, oracle_sufficient=False)
        self.assertFalse(result.steps[0].gate_rejected)
        self.assertIn("OSError", result.steps[0].validator_error)
        self.assertEqual(result.total_calls, 2)
        self.assertFalse(result.steps[0].progress_accepted)
        self.assertEqual(result.steps[0].judge_calls, 0)

    def test_truthy_validator_is_not_boolean_validation(self):
        result, _ = self.run_case(["note", "answer", score(.1)], validator=lambda a: "False")
        self.assertNotEqual(result.stop_reason, "validated")
        self.assertIn("TypeError", result.steps[0].validator_error)

    def test_provisional_needs_review(self):
        result, _ = self.run_case(["note", "answer"], validator=lambda a: Verdict(True, settles_at="2099-01-01"))
        self.assertEqual(result.stop_reason, "validated")
        self.assertTrue(result.needs_human_review)
        self.assertEqual(result.settles_at, "2099-01-01")

    def test_statistical_needs_review(self):
        result, _ = self.run_case(["note", "answer"], validator=lambda a: Verdict(True, confidence=.8))
        self.assertTrue(result.needs_human_review)

    def test_empty_output_preserves_state(self):
        result, _ = self.run_case(["  ", " ", score(.1)], seed_answer="incumbent", seed_scratchpad="original notes")
        self.assertEqual(result.final_answer, "incumbent")
        self.assertEqual(result.current_scratchpad, "original notes")
        self.assertEqual(result.steps[0].rejected_updates, 2)

    def test_empty_candidate_cannot_halt(self):
        result, _ = self.run_case(["note", ""], validator=lambda a: True)
        self.assertFalse(result.halted)
        self.assertEqual(result.total_calls, 2)

    def test_truncated_candidate_cannot_halt(self):
        result, _ = self.run_case(["note", CallResult("partial", stop_reason="max_tokens")], validator=lambda a: True)
        self.assertFalse(result.halted)
        self.assertTrue(result.steps[0].truncated)
        self.assertEqual(result.final_answer, "")

    def test_truncated_notes_are_not_installed(self):
        result, _ = self.run_case([CallResult("partial", stop_reason="length"), "answer", score(.2)], seed_scratchpad="old notes")
        self.assertEqual(result.current_scratchpad, "old notes")

    def test_median_judge(self):
        result, _ = self.run_case(["note", "answer", score(.99), score(.1), score(.2)], judge_votes=3)
        self.assertEqual(result.steps[0].halt_prob, .2)
        self.assertFalse(result.halted)
        self.assertEqual(result.total_calls, 5)

    def test_invalid_judge_gets_one_retry(self):
        result, _ = self.run_case(["note", "answer", "3 errors", score(.1)])
        self.assertEqual(result.steps[0].judge_calls, 2)
        self.assertEqual(result.total_calls, 4)

    def test_two_invalid_judges_fail_closed(self):
        result, _ = self.run_case(["note", "answer", "3 errors", "1 error"])
        self.assertEqual(result.steps[0].halt_prob, 0)
        self.assertFalse(result.halted)

    def test_budget_inside_notes(self):
        result, worker = self.run_case(["note"], max_total_calls=1, seed_answer="seed")
        self.assertEqual(result.stop_reason, "budget")
        self.assertEqual(len(worker.requests), 1)
        self.assertEqual(result.final_answer, "seed")
        self.assertEqual(result.current_scratchpad, "note")

    def test_budget_in_judge_retry(self):
        result, worker = self.run_case(["note", "candidate", "garbage"], max_total_calls=3)
        self.assertEqual(result.stop_reason, "budget")
        self.assertEqual(result.total_calls, 3)
        self.assertEqual(result.current_answer, "candidate")
        self.assertEqual(len(worker.requests), 3)

    def test_failed_attempt_counts_against_budget(self):
        result, worker = self.run_case([RuntimeError("fail")], max_total_calls=1,
                                       ladder=(Tier("first"), Tier("second")))
        self.assertEqual(result.stop_reason, "budget")
        self.assertEqual(result.total_calls, 1)
        self.assertEqual(len(worker.requests), 1)

    def test_failed_tier_preserves_partial_state(self):
        result, worker = self.run_case(["notes", "candidate", RuntimeError("judge failed"),
                                       "repaired notes", "better", score(.1)],
                                      ladder=(Tier("first"), Tier("second")))
        self.assertIn("candidate", worker.requests[3]["user"])
        self.assertIn("notes", worker.requests[3]["user"])
        self.assertEqual(result.total_calls, 6)

    def test_keyboard_interrupt_preserves_notes(self):
        result, _ = self.run_case(["new note", KeyboardInterrupt()], seed_answer="seed")
        self.assertEqual(result.stop_reason, "interrupted")
        self.assertEqual(result.final_answer, "seed")
        self.assertEqual(result.current_scratchpad, "new note")
        self.assertEqual(result.total_calls, 2)

    def test_refusal_is_not_an_answer(self):
        result, _ = self.run_case([CallResult("not a completion", stop_reason="refusal")])
        self.assertEqual(result.stop_reason, "failed")
        self.assertEqual(result.final_answer, "")

    def test_best_answer_and_model_are_paired(self):
        result, worker = self.run_case(["good notes", "best", score(.8), "later notes", "worse", score(.2)],
                                      ladder=(Tier("small-local"), Tier("large-local")))
        self.assertEqual(result.final_answer, "best")
        self.assertEqual(result.final_model, "small-local")
        self.assertIn("best", worker.requests[3]["user"])
        self.assertIn("good notes", worker.requests[3]["user"])
        self.assertIn("small-local", result.trajectory())

    def test_answer_cycle_converges(self):
        worker = Scripted(["n1", "A", score(.1), "n2", "B", score(.1), "n3", "A", score(.1)])
        result = recurse("task", client=worker, config=RecurseConfig(n=1, T=5))
        self.assertEqual(result.stop_reason, "converged")
        self.assertEqual(len(result.steps), 3)

    def test_case_distinction_is_not_convergence(self):
        worker = Scripted(["n1", "A", score(.1), "n2", "a", score(.1)])
        result = recurse("task", client=worker, config=RecurseConfig(n=1, T=2))
        self.assertEqual(result.stop_reason, "exhausted")
        self.assertFalse(result.steps[-1].converged)

    def test_math_normalization_preserves_meaning(self):
        for left, right in [("A", "a"), ("x*y", "xy"), ("x_1", "x1"), ("x~y", "xy")]:
            with self.subTest(left=left):
                self.assertNotEqual(trm._norm(left), trm._norm(right))

    def test_retrieval_bound_is_exact(self):
        self.assertLessEqual(sum(map(len, trm._bound_snippets(["a"*100, "b"*100], 17))), 17)

    def test_local_retrieval(self):
        corpus = CorpusRetriever(["Euler (1748) wrote about functions.", "Unrelated material."])
        self.assertEqual(len(corpus.resolve("Euler (1748)")), 1)
        self.assertEqual(corpus.resolve("Euler (1749)"), [])
        self.assertEqual(len(corpus.retrieve("functions", k=1)), 1)

    def test_unresolved_citation_is_not_confirmed_by_fuzzy_hit(self):
        corpus = CorpusRetriever(["Functions and related mathematics."])
        found = claims.audit_claims(claims.parse_claims("[KNOWN] Euler (1748) proved this."), corpus)
        self.assertEqual(found[0].label, "UNSOURCED")

    def test_exact_rational_demo_without_sockets(self):
        with patch("socket.socket", side_effect=AssertionError("network forbidden in this test")):
            result = recurse(demo.PROBLEM, client=CallableClient(demo.complete),
                             config=RecurseConfig(n=1, T=8, validator=demo.validator))
        self.assertEqual(result.stop_reason, "validated")
        self.assertEqual(len(result.steps), 5)
        self.assertEqual(result.total_calls, 14)
        self.assertTrue(demo.validator(result.final_answer).passed)

    def test_wall_deadline_is_cooperative(self):
        def slow(**request):
            time.sleep(.02)
            return "late notes"
        result = recurse("task", client=CallableClient(slow),
                         config=RecurseConfig(n=1, T=1, max_wall_seconds=.005))
        self.assertEqual(result.stop_reason, "budget")
        self.assertEqual(result.total_calls, 1)
        self.assertEqual(result.current_scratchpad, "")

    def test_trace_persists_complete_state(self):
        result, _ = self.run_case(["full notes", "full answer", score(.2)])
        with tempfile.TemporaryDirectory() as temp:
            path = result.persist(temp, "evidence")
            data = json.loads(Path(path).read_text())
            self.assertEqual(data["steps"][0]["answer"], "full answer")
            self.assertEqual(data["steps"][0]["scratchpad"], "full notes")
            with self.assertRaises(FileExistsError):
                result.persist(temp, "evidence")
            with self.assertRaises(ValueError):
                result.persist(temp, "../escape")

    def test_generated_checker_execution_disabled(self):
        with self.assertRaises(ValueError):
            RecurseConfig(oracle_auto=True).validate()

    def test_valid_score_endpoints(self):
        for number in [0, 1, .333]:
            self.assertEqual(halting._parse(score(number))[0], number)


INVALID_JUDGES = [
    "3 errors", "1 error", "0 errors", "1", "-1", "true", "[]",
    '{"halt_prob":true}', '{"halt_prob":false}', '{"halt_prob":-1}',
    '{"halt_prob":2}', '{"halt_prob":NaN}', '{"halt_prob":Infinity}',
    '{"halt_prob":1e309}', '{"halt_prob":"1"}', '{"halt_prob":0,"halt_prob":1}',
    '{"halt_prob":1,"reason":[]}', 'prefix {"halt_prob":1}',
    '{"halt_prob":1} trailing', '```json\n{"halt_prob":1}\n```',
]
for index, value in enumerate(INVALID_JUDGES):
    def check(self, value=value):
        self.assertEqual(halting._parse(value), (0.0, halting._UNPARSEABLE))
    setattr(CoreTests, f"test_invalid_judge_{index:02}", check)

INVALID_CONFIGS = [dict(n=-1), dict(n=True), dict(n=1.5), dict(T=0), dict(ladder=()),
                   dict(ladder=(Tier(""),)), dict(ladder=(Tier("local", max_tokens=0),)),
                   dict(judge_votes=0), dict(judge_votes=True), dict(halt_threshold=float("nan")),
                   dict(halt_threshold=0), dict(halt_threshold=2), dict(temperature=float("inf")),
                   dict(max_total_calls=True), dict(max_total_calls=0), dict(max_wall_seconds=float("nan")),
                   dict(judge_model=""), dict(retrieval_max_chars=0)]
for index, value in enumerate(INVALID_CONFIGS):
    def check(self, value=value):
        with self.assertRaises((ValueError, TypeError)):
            RecurseConfig(**value).validate()
    setattr(CoreTests, f"test_invalid_config_{index:02}", check)


if __name__ == "__main__":
    unittest.main()
