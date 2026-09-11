"""Adversarial state-machine tests; no neural inference or network is implied."""
from __future__ import annotations

import json
import random
import re
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

from headroom_recursion import CallResult, CallableClient, RecurseConfig, Tier, Verdict, recurse
from headroom_recursion import prompts, checkpoint, halting
from headroom_recursion.compression import (MemoryStore, MemoryLimitError, TokenMeter,
    ContextCompressor, HeadroomCompressor, blocks)
from headroom_recursion.progress import (PLAN_SYSTEM, ProgressCheck, ProgressGuard,
    seed_candidates, parse_seed, fallback_seed)
from headroom_recursion.runtime import MeteredClient
from headroom_recursion.trace import RunTrace

PROSE = "The search explored a redundant branch and recorded its routine bookkeeping.\n\n"
MATH = "<verbatim>\nFor x > 0, f(x) = x^2 - 2.\nA != a; x*y != xy; x_1 != x1.\n</verbatim>\n\n"
LONG_NOTES = MATH + PROSE * 150 + "Next inspect the remaining branch carefully.\n"


class Worker:
    def __init__(self, notes=("working notes",), answers=("candidate",), scores=None,
                 plan=None, note_hook=None):
        self.notes, self.answers = iter(notes), iter(answers)
        self.scores = scores or {}
        self.plan, self.note_hook = plan, note_hook
        self.requests = []

    def complete(self, **request):
        self.requests.append(request)
        system = request["system"]
        if system == PLAN_SYSTEM:
            obj = json.loads(request["user"].split("(data):\n", 1)[1].split("\nOPERATOR PROGRESS", 1)[0])
            value = self.plan(obj) if self.plan else json.dumps({
                "keep": [row["id"] for row in obj["candidates"][:obj["max_keep"]]],
                "next_check": "Inspect the outstanding condition."})
        elif system.startswith(prompts.LATENT_SYSTEM):
            value = self.note_hook(request) if self.note_hook else next(self.notes)
        elif system == prompts.ANSWER_SYSTEM:
            value = next(self.answers)
        elif system == prompts.HALT_SYSTEM:
            answer = request["user"].split("CANDIDATE ANSWER:\n", 1)[1].split("\n\nVISIBLE WORKING NOTES:", 1)[0]
            value = self.scores.get(answer, .2)
            if isinstance(value, (float, int)):
                value = json.dumps({"halt_prob": value, "reason": "scripted, not an empirical score"})
        else:
            raise AssertionError("unexpected operation")
        if isinstance(value, BaseException):
            raise value
        return value if isinstance(value, CallResult) else CallResult(value)


class CompressionTests(unittest.TestCase):
    def view(self, text=LONG_NOTES, **kwargs):
        store, meter = MemoryStore(), TokenMeter()
        engine = ContextCompressor(store, meter, min_tokens=1, **kwargs)
        return engine.view(text, model="opaque", budget=320, query="inspect branch"), store

    def test_default_features_are_enabled(self):
        cfg = RecurseConfig()
        self.assertTrue(cfg.use_headroom and cfg.enforce_progress and cfg.preseed_ladder)

    def test_math_exact_and_prose_compressed(self):
        view, store = self.view()
        self.assertTrue(view.omitted)
        self.assertIn(MATH, view.text)
        self.assertLess(view.tokens_after, view.tokens_before)
        self.assertEqual(store.records[view.original_ref], LONG_NOTES)
        self.assertEqual(store.read(view.original_ref, 0, len(MATH)), MATH)

    def test_fenced_code_not_deduplicated(self):
        text = "```python\nvalue = A * a\n```\n\n" * 12
        view, _ = self.view(text)
        self.assertEqual(view.text, text)
        self.assertEqual(view.tokens_before, view.tokens_after)

    def test_negation_not_lost(self):
        statement = "The conclusion does not follow without the missing assumption.\n\n"
        view, _ = self.view(statement + PROSE * 150)
        self.assertIn(statement, view.text)

    def test_long_unprotected_paragraph_can_shrink(self):
        view, _ = self.view((PROSE.strip() + " ") * 150)
        self.assertLess(view.tokens_after, view.tokens_before)

    def test_block_segmentation_roundtrips(self):
        random.seed(17)
        samples = [MATH, LONG_NOTES, "```lean\n-- unclosed\n\n x = 1", "<verbatim>\n\nπ = 3"]
        for _ in range(50):
            samples.append("".join(random.choice(["abc ", "\n", "\n\n", "π", "=", "Not. ", "```", " "])
                                   for _ in range(50)))
        for text in samples:
            self.assertEqual("".join(b.text for b in blocks(text)), text)

    def test_protected_material_never_reaches_external_compressor(self):
        calls = []
        class Prose:
            def compress(self, text, *, model):
                calls.append(text)
                return "Routine bookkeeping."
        view, _ = self.view(prose=Prose())
        self.assertTrue(calls)
        self.assertTrue(all("x^2" not in text and "verbatim" not in text for text in calls))
        self.assertIn(MATH, view.text)

    def test_broken_compressor_is_visible_fallback(self):
        class Broken:
            def compress(self, text, *, model):
                return None
        view, _ = self.view(prose=Broken())
        self.assertIn("ValueError", view.error)
        self.assertIn(MATH, view.text)

    def test_inflating_compressor_cannot_report_savings(self):
        class Inflate:
            def compress(self, text, *, model):
                return text * 50
        view, _ = self.view("plain text " * 500, prose=Inflate())
        self.assertEqual(view.tokens_before, view.tokens_after)

    def test_archive_is_bounded_without_eviction(self):
        store = MemoryStore(5)
        key = store.put("abcd")
        with self.assertRaises(MemoryLimitError):
            store.put("xyz")
        self.assertEqual(store.read(key), "abcd")
        self.assertEqual(store.put("abcd"), key)

    def test_invalid_reads(self):
        store = MemoryStore()
        key = store.put("source")
        for start, end in [(-1, 1), (False, 1), (0, 99), (3, 2), (0, True)]:
            with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                store.read(key, start, end)
        with self.assertRaises(ValueError):
            store.read("unoffered")

    def test_archive_restore_is_atomic_and_verified(self):
        store = MemoryStore()
        old = store.put("original")
        with self.assertRaises(ValueError):
            store.restore({"0" * 64: "corrupted"})
        self.assertEqual(store.read(old), "original")

    def test_supplied_tokenizer_is_used(self):
        meter = TokenMeter(lambda text, model: len(text))
        self.assertEqual(meter.count("Δ > 0", "model"), 5)
        self.assertEqual(meter.label, "local-tokenizer/text-only")
        for bad in (True, -1, 0, 3.4, float("nan")):
            with self.assertRaises(ValueError):
                TokenMeter(lambda t, m, bad=bad: bad).count("x", "m")

    def test_headroom_adapter_options_and_opaque_model(self):
        seen = {}
        def compress(messages, *, model, config):
            seen.update(messages=messages, model=model, config=config)
            return SimpleNamespace(messages=[{"role": "user", "content": "Short."}])
        adapter = HeadroomCompressor(compress_fn=compress, config_factory=lambda **kw: kw)
        self.assertEqual(adapter.compress("Original prose", model="my-weights"), "Short.")
        self.assertEqual(seen["model"], "my-weights")
        self.assertEqual(seen["config"]["kompress_model"], "disabled")
        self.assertEqual(seen["config"]["protect_recent"], 0)
        self.assertFalse(seen["config"]["compress_system_messages"])

    def test_headroom_bad_shapes_and_unwired_retrieval_refused(self):
        for response in ([], None, [{"role": "system", "content": "bad"}],
                         [{"role": "user", "content": ""}],
                         [{"role": "user", "content": "<<ccr:deadbeef>>"}]):
            adapter = HeadroomCompressor(compress_fn=lambda *a, response=response, **k: response,
                                         config_factory=lambda **k: k)
            with self.subTest(response=response), self.assertRaises(ValueError):
                adapter.compress("text", model="local")

    def test_headroom_async_result_is_not_abandoned(self):
        async def async_compress(*a, **kw):
            return []
        adapter = HeadroomCompressor(compress_fn=async_compress, config_factory=lambda **k: k)
        with self.assertRaises(TypeError):
            adapter.compress("text", model="local")

    def test_compressed_scratchpad_actually_reaches_worker(self):
        worker = Worker(notes=(LONG_NOTES, "final notes"), answers=("result",))
        cfg = RecurseConfig(n=2, T=1, seed_scratchpad=LONG_NOTES,
                            preseed_ladder=False, scratchpad_tokens=320, compression_min_tokens=1)
        trace = recurse("Find a result", client=worker, config=cfg)
        note_requests = [r for r in worker.requests if r["system"].startswith(prompts.LATENT_SYSTEM)]
        self.assertEqual(len(note_requests), 2)
        for request in note_requests:
            self.assertIn(MATH, request["user"])
            self.assertLess(request["user"].count(PROSE.strip()), 150)
            self.assertFalse(request["use_headroom"])
        self.assertIn(LONG_NOTES, trace.memory_archive.values())
        self.assertGreater(trace.tokens_saved, 0)
        self.assertEqual(trace.tokens_before, sum(e["input_before"] for e in trace.call_events))
        self.assertEqual(trace.tokens_after, sum(e["input_after"] for e in trace.call_events))

    def test_reference_context_compressed_without_cutting_math(self):
        class Retriever:
            def retrieve(self, q, *, k):
                return [LONG_NOTES]
        worker = Worker()
        trace = recurse("inspect branch", client=worker, config=RecurseConfig(
            n=1, T=1, retriever=Retriever(), retrieval_max_chars=30000,
            context_tokens=320, compression_min_tokens=1))
        self.assertIn(MATH, worker.requests[0]["user"])
        self.assertTrue(any(e["field"] == "context" and e["after"] < e["before"] for e in trace.compression_events))

    def test_judge_default_receives_uncompressed_notes_and_exact_answer(self):
        worker = Worker(notes=(LONG_NOTES,), answers=("A != a; x_1 > 0",))
        trace = recurse("a task", client=worker, config=RecurseConfig(n=1, T=1, scratchpad_tokens=320))
        request = next(r for r in worker.requests if r["system"] == prompts.HALT_SYSTEM)
        self.assertIn(LONG_NOTES.strip(), request["user"])
        self.assertIn("A != a; x_1 > 0", request["user"])
        self.assertFalse(any(e["role"] == "judge" for e in trace.compression_events))

    def test_judge_optin_compresses_only_notes(self):
        candidate = "A != a; x_1 > 0"
        worker = Worker(notes=(LONG_NOTES,), answers=(candidate,))
        trace = recurse("a task", client=worker, config=RecurseConfig(n=1, T=1,
            scratchpad_tokens=320, compress_judge=True))
        request = next(r for r in worker.requests if r["system"] == prompts.HALT_SYSTEM)
        self.assertIn(candidate, request["user"])
        self.assertIn(MATH, request["user"])
        self.assertTrue(any(e["role"] == "judge" and e["after"] < e["before"] for e in trace.compression_events))

    def test_hard_context_limit_never_calls_model(self):
        worker = Worker()
        trace = recurse("x = y " * 1000, client=worker,
                        config=RecurseConfig(n=1, T=1, max_input_tokens=50))
        self.assertEqual(trace.stop_reason, "context-budget")
        self.assertFalse(worker.requests)
        self.assertEqual(trace.total_calls, 0)

    def test_read_request_rehydrates_exact_source_and_is_metered(self):
        seen = []
        def hook(request):
            seen.append(request)
            if len(seen) == 1:
                key = re.search(r"ARCHIVED SOURCE ([a-f0-9]{64})", request["user"]).group(1)
                return json.dumps({"memory_request": {"id": key, "start": 0, "end": len(MATH)}})
            self.assertIn(MATH, request["user"].split("EXACT ARCHIVED REFERENCE", 1)[1])
            return "repaired notes"
        worker = Worker(note_hook=hook)
        trace = recurse("inspect", client=worker, config=RecurseConfig(n=1, T=1,
            seed_scratchpad=LONG_NOTES, preseed_ladder=False, scratchpad_tokens=320))
        self.assertEqual(trace.total_calls, 4)
        self.assertEqual(sum(e["role"] == "memory_replay" for e in trace.call_events), 1)
        self.assertGreater(trace.auxiliary_tokens, 0)

    def test_invented_memory_ref_cannot_read_other_data(self):
        worker = Worker(note_hook=lambda r: json.dumps({"memory_request": {"id": "0"*64, "start": 0, "end": 1}}))
        trace = recurse("inspect", client=worker, config=RecurseConfig(n=1, T=1,
            seed_scratchpad=LONG_NOTES, preseed_ladder=False, scratchpad_tokens=320))
        self.assertEqual(trace.stop_reason, "failed")
        self.assertEqual(trace.total_calls, 1)
        self.assertEqual(trace.current_scratchpad, LONG_NOTES)

    def test_memory_requests_stop_at_call_budget(self):
        def hook(request):
            key = re.search(r"ARCHIVED SOURCE ([a-f0-9]{64})", request["user"]).group(1)
            return json.dumps({"memory_request": {"id": key, "start": 0, "end": 8}})
        worker = Worker(note_hook=hook)
        trace = recurse("inspect", client=worker, config=RecurseConfig(n=1, T=1,
            seed_scratchpad=LONG_NOTES, preseed_ladder=False, scratchpad_tokens=320, max_total_calls=1))
        self.assertEqual(trace.stop_reason, "budget")
        self.assertEqual(trace.total_calls, 1)

    def test_off_switch_preserves_raw_note_prompt(self):
        worker = Worker()
        trace = recurse("task", client=worker, config=RecurseConfig(n=1, T=1,
            seed_scratchpad=LONG_NOTES, use_headroom=False, preseed_ladder=False))
        self.assertIn(LONG_NOTES, worker.requests[0]["user"])
        self.assertFalse(trace.compression_events)
        self.assertEqual(trace.tokens_saved, 0)


class ProgressTests(unittest.TestCase):
    def test_seed_is_scored_before_first_refinement(self):
        worker = Worker(notes=("updated notes",), answers=("worse",), scores={"seed": .8, "worse": .1})
        trace = recurse("task", client=worker, config=RecurseConfig(n=1, T=1,
            seed_answer="seed", seed_scratchpad="prior notes"))
        self.assertEqual(worker.requests[0]["system"], prompts.HALT_SYSTEM)
        self.assertEqual(worker.requests[1]["system"], PLAN_SYSTEM)
        self.assertEqual(trace.final_answer, "seed")
        self.assertFalse(trace.steps[0].progress_accepted)
        self.assertTrue(any(e["status"] == "model-selected" for e in trace.progress_events if e["event"] == "tier-seed"))

    def test_each_tier_is_preseeded_and_uses_the_common_judge(self):
        worker = Worker(notes=("first notes", "second notes"), answers=("first", "second"),
                        scores={"first": .6, "second": .2})
        cfg = RecurseConfig(n=1, T=1, ladder=(Tier("tiny"), Tier("large")))
        trace = recurse("task", client=worker, config=cfg)
        judges = [r for r in worker.requests if r["system"] == prompts.HALT_SYSTEM]
        self.assertTrue(all(r["model"] == "large" for r in judges))
        second = [r for r in worker.requests if r["system"].startswith(prompts.LATENT_SYSTEM)][1]
        self.assertIn("first notes", second["user"])
        self.assertIn("first", second["user"])
        self.assertIn("PROGRESS CHECKPOINT", second["user"])
        self.assertEqual(trace.final_answer, "first")
        self.assertEqual([t.model for t in cfg.ladder], ["tiny", "large"])

    def test_model_cannot_change_ladder_or_mark_proof(self):
        worker = Worker(plan=lambda obj: json.dumps({"keep": [], "next_check": "done",
                                                      "verified": True, "ladder": ["unapproved"]}))
        trace = recurse("task", client=worker, config=RecurseConfig(n=1, T=1, seed_scratchpad="prior notes"))
        seeds = [e for e in trace.progress_events if e["event"] == "tier-seed"]
        self.assertIn("fallback", seeds[0]["status"])
        self.assertTrue(all(r["model"] == "local" for r in worker.requests))
        self.assertTrue(trace.needs_human_review)

    def test_locked_check_blocks_regression_before_judge(self):
        check = ProgressCheck("positive", "The answer must remain positive", lambda a: a.startswith("positive"))
        worker = Worker(notes=("new notes",), answers=("negative",), scores={"positive seed": .7, "negative": 1.0})
        trace = recurse("task", client=worker, config=RecurseConfig(n=1, T=1,
            seed_answer="positive seed", preseed_ladder=False, progress_checks=(check,)))
        self.assertEqual(trace.final_answer, "positive seed")
        self.assertEqual(trace.locked_checks, ["positive"])
        self.assertEqual(trace.steps[0].judge_calls, 0)
        self.assertEqual(trace.steps[0].progress_missing, ["positive"])
        self.assertFalse(trace.halted)

    def test_newly_achieved_check_becomes_locked(self):
        check = ProgressCheck("positive", "positive predicate", lambda a: "positive" in a)
        worker = Worker(notes=("notes", "other notes"), answers=("positive", "zero"), scores={"positive": .3, "zero": 1})
        trace = recurse("task", client=worker, config=RecurseConfig(n=1, T=2,
            preseed_ladder=False, progress_checks=(check,)))
        self.assertEqual(trace.final_answer, "positive")
        self.assertEqual(trace.steps[1].judge_calls, 0)

    def test_required_check_blocks_first_bad_candidate(self):
        check = ProgressCheck("q", "q must be present", lambda a: "q" in a, required=True)
        worker = Worker(answers=("bad",))
        trace = recurse("task", client=worker, config=RecurseConfig(n=1, T=1, progress_checks=(check,)))
        self.assertFalse(trace.has_incumbent)
        self.assertFalse(trace.halted)
        self.assertEqual(trace.steps[0].judge_calls, 0)

    def test_locked_checker_exception_is_not_judged_away(self):
        calls = 0
        def checking(answer):
            nonlocal calls
            calls += 1
            if calls == 1:
                return True
            raise RuntimeError("checker down")
        check = ProgressCheck("stable", "stable predicate", checking)
        worker = Worker(answers=("new",), scores={"seed": .5, "new": 1})
        trace = recurse("task", client=worker, config=RecurseConfig(n=1, T=1,
            seed_answer="seed", preseed_ladder=False, progress_checks=(check,)))
        self.assertEqual(trace.final_answer, "seed")
        self.assertIn("RuntimeError", trace.steps[0].progress_errors[0])

    def test_statistical_or_provisional_checks_do_not_create_proof_locks(self):
        for verdict in (Verdict(True, confidence=.5), Verdict(True, settles_at="2099-01-01")):
            guard = ProgressGuard((ProgressCheck("partial", "sampled evidence", lambda a, v=verdict: v),))
            decision = guard.evaluate("candidate")
            guard.commit(decision)
            self.assertFalse(guard.locked)

    def test_regression_rolls_back_answer_and_notes_for_next_step(self):
        worker = Worker(notes=("good notes", "bad notes", "last notes"),
                        answers=("good", "bad", "last"), scores={"good": .8, "bad": .1, "last": .7})
        trace = recurse("task", client=worker, config=RecurseConfig(n=1, T=3, preseed_ladder=False))
        notes_requests = [r for r in worker.requests if r["system"].startswith(prompts.LATENT_SYSTEM)]
        self.assertIn("good notes", notes_requests[2]["user"])
        self.assertIn("REVISION REJECTED", notes_requests[2]["user"])
        self.assertNotIn("bad notes", notes_requests[2]["user"])
        self.assertIn("bad notes", trace.memory_archive.values())
        self.assertEqual(trace.final_answer, "good")

    def test_already_verified_seed_needs_no_model_call(self):
        worker = Worker()
        trace = recurse("return four", client=worker, config=RecurseConfig(seed_answer="4", validator=lambda a: a == "4"))
        self.assertEqual(trace.stop_reason, "validated")
        self.assertFalse(worker.requests)
        self.assertFalse(trace.needs_human_review)

    def test_unparseable_seed_grade_fails_closed_without_discarding_seed(self):
        worker = Worker(scores={"seed": "not a score"})
        trace = recurse("task", client=worker, config=RecurseConfig(seed_answer="seed"))
        self.assertEqual(trace.stop_reason, "seed-unscored")
        self.assertEqual(trace.final_answer, "seed")
        self.assertEqual(trace.total_calls, 2)
        self.assertFalse(trace.seed_scored)

    def test_truncated_valid_json_judge_does_not_authorize_halt(self):
        worker = Worker(scores={"candidate": CallResult('{"halt_prob":1}', stop_reason="length")})
        trace = recurse("task", client=worker, config=RecurseConfig(n=1, T=1))
        self.assertFalse(trace.halted)
        self.assertFalse(trace.has_incumbent)
        self.assertEqual(trace.steps[0].judge_calls, 2)

    def test_planning_attempt_counts_against_budget(self):
        worker = Worker()
        trace = recurse("task", client=worker, config=RecurseConfig(n=1, T=1,
            seed_scratchpad="prior notes", max_total_calls=1))
        self.assertEqual(trace.stop_reason, "budget")
        self.assertEqual(trace.total_calls, 1)
        self.assertEqual(worker.requests[0]["system"], PLAN_SYSTEM)

    def test_selector_has_fixed_pool_and_no_invented_records(self):
        store, meter = MemoryStore(), TokenMeter()
        pool = seed_candidates("alpha\n\nbeta\n\ngamma\n\ndelta", store, meter, "m", limit=4, token_budget=1000)
        self.assertLessEqual(len(pool), 4)
        for obj in ({"keep": ["invented"], "next_check": "x"},
                    {"keep": [pool[0]["id"]]*2, "next_check": "x"},
                    {"keep": [], "next_check": "x"}):
            with self.assertRaises(ValueError):
                parse_seed(json.dumps(obj), pool, max_keep=2, meter=meter, model="m", token_budget=500)
        selected = fallback_seed(pool, max_keep=2, meter=meter, model="m", token_budget=500)
        self.assertLessEqual(len(selected.keep), 2)


class CheckpointTests(unittest.TestCase):
    def test_interrupt_resume_keeps_progress_cursor_archive_and_total_budget(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/"state.json"
            cfg = RecurseConfig(n=1, T=3, preseed_ladder=False, checkpoint_path=path, max_total_calls=20)
            first = Worker(notes=("good notes", KeyboardInterrupt()), answers=("good",), scores={"good": .8})
            trace = recurse("task", client=first, config=cfg)
            self.assertEqual(trace.stop_reason, "interrupted")
            saved = checkpoint.load(path)
            self.assertEqual(saved["attempted_calls"], 4)
            self.assertEqual(saved["completed_steps"], [1])
            second = Worker(notes=("other notes", "last notes"), answers=("bad", "last"),
                            scores={"good": .8, "bad": .2, "last": .4})
            resumed = recurse("task", client=second, config=replace(cfg, resume_from=path))
            self.assertTrue(resumed.resumed)
            self.assertEqual(resumed.final_answer, "good")
            self.assertEqual(resumed.total_calls, 11)
            self.assertEqual(resumed.completed_steps, [3])
            self.assertIn("good notes", resumed.memory_archive.values())
            self.assertEqual(second.requests[0]["system"], prompts.HALT_SYSTEM)

    def test_scope_problem_and_policy_mismatch_rejected_before_inference(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/"state.json"
            cfg = RecurseConfig(n=1, T=1, checkpoint_path=path)
            recurse("task", client=Worker(), config=cfg)
            for problem, other in (("other task", cfg), ("task", replace(cfg, memory_scope="another-user")),
                                   ("task", replace(cfg, max_total_calls=30)),
                                   ("task", replace(cfg, ladder=(Tier("different"),)))):
                worker = Worker()
                with self.subTest(problem=problem), self.assertRaises(ValueError):
                    recurse(problem, client=worker, config=replace(other, resume_from=path))
                self.assertFalse(worker.requests)

    def test_edited_digest_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/"state.json"
            checkpoint.save(path, {"a": 1})
            obj = json.loads(path.read_text())
            obj["payload"]["a"] = 2
            path.write_text(json.dumps(obj))
            with self.assertRaises(ValueError):
                checkpoint.load(path)

    def test_duplicate_json_keys_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/"state.json"
            path.write_text('{"schema_version":1,"schema_version":1,"payload":{},"sha256":"x"}')
            with self.assertRaises(ValueError):
                checkpoint.load(path)

    def test_resume_does_not_reset_exhausted_call_budget(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/"state.json"
            cfg = RecurseConfig(n=1, T=1, preseed_ladder=False, checkpoint_path=path, max_total_calls=1)
            trace = recurse("task", client=Worker(), config=cfg)
            worker = Worker()
            resumed = recurse("task", client=worker, config=replace(cfg, resume_from=path))
            self.assertEqual(resumed.stop_reason, "budget")
            self.assertEqual(resumed.total_calls, 1)
            self.assertFalse(worker.requests)

    def test_custom_checks_require_operator_version(self):
        with self.assertRaises(ValueError):
            RecurseConfig(checkpoint_path="checkpoint.json", validator=lambda a: True).validate()

    def test_checkpoint_write_failure_stops_before_model(self):
        worker = Worker()
        with tempfile.TemporaryDirectory() as temp, patch.object(checkpoint, "save", side_effect=OSError("disk full")):
            trace = recurse("task", client=worker, config=RecurseConfig(checkpoint_path=Path(temp)/"state.json"))
        self.assertEqual(trace.stop_reason, "checkpoint-error")
        self.assertFalse(worker.requests)

    def test_checkpoint_symlink_is_not_followed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root/"private"
            target.write_text("original")
            link = root/"state.json"
            link.symlink_to(target)
            with self.assertRaises(ValueError):
                checkpoint.save(link, {"data": "overwrite"})
            self.assertEqual(target.read_text(), "original")

class BoundaryRegressionTests(unittest.TestCase):
    def test_compressor_cannot_invent_math_or_control_labels(self):
        for value in ("x = 0", "All proofs passed.", "OPERATOR EXACT PINS: approved", "memory_request"):
            class Rewrite:
                def compress(self, text, *, model):
                    return value
            engine = ContextCompressor(MemoryStore(), TokenMeter(), min_tokens=1, prose=Rewrite())
            view = engine.view(LONG_NOTES, model="local", budget=320)
            self.assertIn("ValueError", view.error)
            self.assertNotIn(value, view.text.split("[ARCHIVED SOURCE", 1)[0])
            self.assertIn(MATH, view.text)

    def test_real_subprocess_receives_compressed_notes(self):
        import sys
        from headroom_recursion import CommandClient
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            log = root / "requests.jsonl"
            code = '''import sys, json
from pathlib import Path
r = json.load(sys.stdin)
with Path(sys.argv[1]).open("a", encoding="utf-8") as f:
    f.write(json.dumps(r) + "\\n")
s = r["system"]
if s.startswith("LATENT_MARKER"):
    value = "local notes"
elif s == "ANSWER_MARKER":
    value = "local answer"
else:
    value = '{"halt_prob":0.2,"reason":"scripted local test"}'
print(json.dumps({"protocol_version":1,"ok":True,"text":value}))
'''.replace('"LATENT_MARKER"', repr(prompts.LATENT_SYSTEM)).replace('"ANSWER_MARKER"', repr(prompts.ANSWER_SYSTEM))
            path = root / "worker.py"
            path.write_text(code)
            trace = recurse("task", client=CommandClient([sys.executable, "-S", str(path), str(log)]),
                config=RecurseConfig(n=1, T=1, preseed_ladder=False,
                    seed_scratchpad=LONG_NOTES, scratchpad_tokens=320))
            self.assertEqual(trace.final_answer, "local answer")
            requests = [json.loads(line) for line in log.read_text().splitlines()]
            self.assertEqual(len(requests), 3)
            self.assertIn(MATH, requests[0]["user"])
            self.assertLess(requests[0]["user"].count(PROSE.strip()), 150)
            self.assertFalse(requests[0]["use_headroom"])
            self.assertGreater(trace.tokens_saved, 0)

    def test_required_rejected_answer_is_not_returned_as_fallback(self):
        check = ProgressCheck("must-pass", "Reviewed condition", lambda a: False, required=True)
        trace = recurse("task", client=Worker(), config=RecurseConfig(n=1, T=1, progress_checks=(check,)))
        self.assertEqual(trace.final_answer, "")
        self.assertTrue(trace.current_rejected)
        self.assertEqual(trace.steps[0].answer, "candidate")

    def test_seed_planner_sees_exact_incumbent_answer(self):
        observed = []
        def plan(obj):
            observed.append(obj["incumbent_answer"])
            return json.dumps({"keep": [obj["candidates"][0]["id"]], "next_check": "Inspect it."})
        worker = Worker(plan=plan, scores={"A != a": .5})
        recurse("task", client=worker, config=RecurseConfig(n=1, T=1,
            seed_answer="A != a", seed_scratchpad="prior notes"))
        self.assertEqual(observed, ["A != a"])

    def test_seed_and_candidate_share_partial_gate_framing(self):
        worker = Worker(scores={"seed": .5, "candidate": .4})
        recurse("task", client=worker, config=RecurseConfig(n=1, T=1,
            seed_answer="seed", preseed_ladder=False, validator=lambda a: True, oracle_sufficient=False))
        judges = [r for r in worker.requests if r["system"] == prompts.HALT_SYSTEM]
        self.assertEqual(len(judges), 2)
        for request in judges:
            self.assertIn("Gate passed only the operator-declared partial coverage.", request["user"])

    def test_coarse_pool_and_seed_budgets_include_json_escaping(self):
        from headroom_recursion.progress import LadderSeed
        meter = TokenMeter(lambda text, model: len(text))
        store = MemoryStore()
        text = '\\"' * 30 + "\n\nalpha\n\nbeta"
        pool = seed_candidates(text, store, meter, "m", limit=4, token_budget=300)
        self.assertLessEqual(len(json.dumps(pool, ensure_ascii=False)), 300)
        seed = fallback_seed(pool, max_keep=2, meter=meter, model="m", token_budget=300)
        self.assertLessEqual(len(seed.render(store)), 300)

    def test_resume_rejected_locked_incumbent_is_not_returned(self):
        from headroom_recursion import RunError
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/"checkpoint.json"
            check = ProgressCheck("truth", "reviewed property", lambda a: True)
            cfg = RecurseConfig(n=1, T=1, progress_checks=(check,), preseed_ladder=False,
                checkpoint_path=path, verification_id="trusted-test-v1")
            recurse("task", client=Worker(), config=cfg)
            changed = ProgressCheck("truth", "reviewed property", lambda a: False)
            with self.assertRaises(RunError) as caught:
                recurse("task", client=Worker(), config=replace(cfg, resume_from=path, progress_checks=(changed,)))
            self.assertEqual(caught.exception.trace.final_answer, "")
            self.assertFalse(caught.exception.trace.halted)

    def test_random_judge_sequences_never_lower_committed_score(self):
        rng = random.Random(414)
        for trial in range(20):
            answers = [f"candidate {i}" for i in range(6)]
            scores = {answer: rng.random() * .8 for answer in answers}
            worker = Worker(notes=(f"notes {i}" for i in range(6)), answers=answers, scores=scores)
            trace = recurse("task", client=worker, config=RecurseConfig(n=1, T=6, preseed_ladder=False))
            accepted = [s.halt_prob for s in trace.steps if s.progress_accepted]
            self.assertEqual(accepted, sorted(accepted))
            self.assertEqual(scores[trace.final_answer], max(scores.values()))

    def test_invalid_memory_progress_configuration_fails_before_inference(self):
        cases = ({"scratchpad_tokens": False}, {"context_tokens": 0}, {"memory_max_rounds": -1},
                 {"max_input_tokens": float("inf")}, {"progress_tokens": 0},
                 {"progress_model": "unapproved"}, {"memory_scope": " "},
                 {"pinned_notes": ["mutable list"]}, {"token_counter": "not callable"})
        for case in cases:
            worker = Worker()
            with self.subTest(case=case), self.assertRaises((ValueError, TypeError)):
                recurse("task", client=worker, config=RecurseConfig(**case))
            self.assertFalse(worker.requests)

    def test_unavailable_headroom_fails_explicitly_without_calling_model(self):
        import builtins
        original = builtins.__import__
        def blocked(name, *args, **kwargs):
            if name == "headroom":
                raise ModuleNotFoundError("headroom intentionally unavailable")
            return original(name, *args, **kwargs)
        worker = Worker()
        with patch("builtins.__import__", side_effect=blocked), self.assertRaises(ModuleNotFoundError):
            recurse("task", client=worker, config=RecurseConfig(compression_backend="headroom"))
        self.assertFalse(worker.requests)


if __name__ == "__main__":
    unittest.main()
