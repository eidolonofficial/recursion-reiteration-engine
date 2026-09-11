"""Approved tier order, model-selected progress seeds, and enforced incumbent handoff."""
from __future__ import annotations

import json
import time
from dataclasses import replace
from . import checkpoint, halting, trm
from .config import RecurseConfig
from .compression import ContextLimitError, MemoryLimitError
from .progress import (PLAN_SYSTEM, LadderSeed, ProgressGuard, fallback_seed, parse_seed, seed_candidates)
from .runtime import BudgetExhausted, CheckpointWriteError, MeteredClient
from .trace import RunTrace

# Compatibility for callers that inspected the former internal budget wrapper.
_MeteredClient = MeteredClient


class RunError(RuntimeError):
    def __init__(self, cause: BaseException, trace: RunTrace):
        super().__init__(f"run failed: {type(cause).__name__}")
        self.trace = trace


def _prepare_seed(metered: MeteredClient, cfg: RecurseConfig, trace: RunTrace,
                  problem: str, answer: str, notes: str, index: int) -> None:
    metered.seed = LadderSeed()  # no stale advisory selection on a later empty pool
    if not cfg.preseed_ladder or not (answer or notes):
        return
    model = cfg.progress_model or cfg.ladder[-1].model
    pool = seed_candidates(notes or answer, metered.store, metered.meter, model,
                           limit=2 * cfg.progress_k, token_budget=2 * cfg.progress_tokens)
    if not pool:
        trace.progress_events.append({"event": "tier-seed", "tier": index,
                                      "status": "no bounded source blocks; exact incumbent retained"})
        return
    selected = fallback_seed(pool, max_keep=cfg.progress_k, meter=metered.meter,
                             model=model, token_budget=cfg.progress_tokens)
    try:
        result = metered.complete_prompt(
            role="progress_seed", model=model, system=PLAN_SYSTEM,
            template="PROBLEM:\n{problem}\n\nAPPROVED LADDER AND PRIOR PROGRESS (data):\n{records}",
            values={"problem": problem, "records": json.dumps({
                "approved_ladder": [t.model for t in cfg.ladder],
                "entering_tier": cfg.ladder[index].model,
                "incumbent_answer": answer, "candidates": pool,
                "max_keep": cfg.progress_k}, ensure_ascii=False)},
            max_tokens=min(1024, cfg.ladder[index].max_tokens), temperature=0.0)
        if result.stop_reason in {"length", "max_tokens"}:
            raise ValueError("truncated checkpoint proposal")
        selected = parse_seed(result.text, pool, max_keep=cfg.progress_k, meter=metered.meter,
                              model=model, token_budget=cfg.progress_tokens)
    except (BudgetExhausted, KeyboardInterrupt, ContextLimitError, MemoryLimitError, CheckpointWriteError):
        raise
    except Exception as exc:
        selected = replace(selected, status=f"fallback: {type(exc).__name__}")
    metered.seed = selected
    trace.progress_events.append({"event": "tier-seed", "tier": index,
                                  "model": model, "status": selected.status,
                                  "keep": list(selected.keep), "next_check": selected.next_check})
    metered.flush()


def _grade_seed(metered, cfg, trace, problem, answer, notes, model) -> str:
    """Install an actual baseline, never the seed's own claimed score."""
    decision = metered.guard.evaluate(answer)
    if not decision.accepted:
        trace.current_rejected = True
        if metered.guard.locked:
            trace.has_incumbent = False
            trace.best_answer = trace.best_scratchpad = trace.best_model = ""
            raise ValueError("resumed incumbent failed a previously locked check")
        trace.progress_events.append({"event": "seed-rejected", "missing": list(decision.missing)})
        return "rejected"
    passed, error, verdict = trm._safe_validate(cfg.validator, answer)
    if cfg.validator is not None and not cfg.oracle_sufficient and not passed and not error:
        trace.current_rejected = True
        if metered.guard.locked:
            trace.has_incumbent = False
            trace.best_answer = trace.best_scratchpad = trace.best_model = ""
            raise ValueError("resumed incumbent failed its required gate")
        return "rejected"
    sufficient = cfg.validator is not None and cfg.oracle_sufficient and passed and not error
    if sufficient:
        score = 1.0
    else:
        judge_problem, _, _ = trm.judgment_context(cfg, problem, answer,
                                                   passed=passed, validator_error=error)
        judgment = halting.judge(metered, model=cfg.judge_model or cfg.ladder[-1].model,
                                 problem=judge_problem, answer=answer, scratchpad=notes,
                                 max_tokens=min(256, cfg.ladder[-1].max_tokens),
                                 use_headroom=cfg.use_headroom and cfg.compress_judge,
                                 votes=cfg.judge_votes, role="seed_judge")
        if judgment.valid_votes <= cfg.judge_votes // 2:
            return "unscored"
        score = judgment.halt_prob
    trace.note_candidate(answer=answer, halt_prob=score, model=model or "seed", scratchpad=notes)
    trace.best_step_index = -1  # the seed is not a completed refinement step
    trace.seed_scored = True
    metered.guard.commit(decision)
    trace.progress_events.append({"event": "seed-graded", "score": score,
                                  "authority": "supplied sufficient check" if sufficient else "heuristic judge"})
    if sufficient and verdict:
        trace.validated_confidence = verdict.confidence
        trace.settles_at = verdict.settles_at or ""
    metered.flush()
    return "validated" if sufficient else "halt" if cfg.judge_can_halt and score >= cfg.halt_threshold else "scored"


def recurse(problem: str, *, client, config: RecurseConfig | None = None) -> RunTrace:
    # Snapshot the schedule and flags; never mutate the caller's config object.
    original = config or RecurseConfig()
    original.validate()
    cfg = replace(original, ladder=tuple(original.ladder))
    if not isinstance(problem, str) or not problem.strip():
        raise ValueError("problem must be a nonempty string")
    if not callable(getattr(client, "complete", None)):
        raise TypeError("client must expose complete")
    if cfg.resume_from and (cfg.seed_answer or cfg.seed_scratchpad):
        raise ValueError("use a checkpoint or explicit seed state, not both")
    restored = checkpoint.load(cfg.resume_from) if cfg.resume_from else None
    if restored:
        checkpoint.validate(restored, cfg, problem)
    trace = RunTrace(problem=problem, current_answer=cfg.seed_answer,
                     current_scratchpad=cfg.seed_scratchpad,
                     oracle_rung=cfg.oracle_rung, oracle_gate_only=not cfg.oracle_sufficient,
                     completed_steps=[0] * len(cfg.ladder))
    past_wall = 0.0
    answer, notes, seed_model = cfg.seed_answer, cfg.seed_scratchpad, "seed"
    if restored:
        trace.resumed = True
        trace.attempted_calls, trace.successful_calls = restored["attempted_calls"], restored["successful_calls"]
        trace.reported_tokens_before, trace.reported_tokens_after = restored["input_before"], restored["input_after"]
        trace.auxiliary_tokens = restored["auxiliary_tokens"]
        trace.next_tier, trace.completed_steps = restored["next_tier"], list(restored["completed_steps"])
        past_wall = restored["wall_seconds"]
        incumbent = restored["incumbent"]
        state = incumbent if incumbent["answer"] else restored["current"]
        answer, notes, seed_model = state["answer"], state["scratchpad"], state["model"] or "seed"
        trace.current_answer, trace.current_scratchpad, trace.current_model = answer, notes, seed_model
    start = time.monotonic()
    deadline = start + cfg.max_wall_seconds - past_wall if cfg.max_wall_seconds is not None else None
    metered = MeteredClient(client, cfg, trace, deadline)
    if restored:
        metered.store.restore(restored["archive"])
        metered.guard = ProgressGuard(cfg.progress_checks, tuple(restored["locked_checks"]))
    for text in (answer, notes, *cfg.pinned_notes):
        if text:
            metered.store.put(text)

    def persist_checkpoint():
        trace.wall_seconds = past_wall + time.monotonic() - start
        if not cfg.checkpoint_path:
            return
        incumbent = {"answer": trace.best_answer, "scratchpad": trace.best_scratchpad,
                     "model": trace.best_model} if trace.has_incumbent else {
                         "answer": "", "scratchpad": "", "model": ""}
        payload = {"scope": cfg.memory_scope, "problem_hash": checkpoint.digest(problem),
                   "policy_hash": checkpoint.digest(checkpoint.policy(cfg)),
                   "attempted_calls": trace.attempted_calls, "successful_calls": trace.successful_calls,
                   "wall_seconds": trace.wall_seconds, "next_tier": trace.next_tier,
                   "completed_steps": list(trace.completed_steps), "incumbent": incumbent,
                   "current": {"answer": trace.current_answer, "scratchpad": trace.current_scratchpad,
                               "model": trace.current_model},
                   "locked_checks": sorted(metered.guard.locked), "archive": dict(metered.store.records),
                   "input_before": trace.tokens_before, "input_after": trace.tokens_after,
                   "auxiliary_tokens": trace.auxiliary_tokens}
        try:
            checkpoint.save(cfg.checkpoint_path, payload)
        except Exception as exc:
            raise CheckpointWriteError("checkpoint could not be written; further model calls stopped") from exc

    metered.checkpoint = persist_checkpoint
    stop_reason = "exhausted"

    def finish(halted: bool, reason: str) -> RunTrace:
        trace.halted, trace.stop_reason = halted, reason
        if trace.has_incumbent:
            trace.final_answer, trace.final_model = trace.best_answer, trace.best_model
        else:
            trace.final_answer = "" if trace.current_rejected else trace.current_answer
            trace.final_model = "" if trace.current_rejected else trace.current_model
        trace.needs_human_review = (reason != "validated" or trace.validated_confidence < 1 or bool(trace.settles_at))
        return trace

    try:
        metered.flush()
        if answer and cfg.enforce_progress:
            # Keep the supplied incumbent available even if scoring is interrupted,
            # but never treat it as a scored/verified baseline without doing the work.
            trace.has_incumbent = True
            trace.best_answer, trace.best_scratchpad, trace.best_model = answer, notes, seed_model
            status = _grade_seed(metered, cfg, trace, problem, answer, notes, seed_model)
            if status == "rejected":
                trace.has_incumbent = False
                trace.best_answer = trace.best_scratchpad = trace.best_model = ""
            elif status in {"halt", "validated"}:
                return finish(True, status)
            elif status == "unscored":
                return finish(False, "seed-unscored")
        for index in range(trace.next_tier, len(cfg.ladder)):
            tier = cfg.ladder[index]
            trace.next_tier = index
            if trace.completed_steps[index] >= cfg.steps_for(tier):
                trace.next_tier = index + 1
                continue
            metered.check()
            _prepare_seed(metered, cfg, trace, problem, answer, notes, index)
            try:
                result = trm.run_tier(metered, cfg, tier, problem, answer, notes, trace, deadline, index)
            except (BudgetExhausted, KeyboardInterrupt, ContextLimitError, MemoryLimitError, CheckpointWriteError):
                raise
            except Exception as exc:
                trace.error = f"tier failed: {type(exc).__name__}"
                trace.tier_stops.append(f"{tier.model}: failed ({type(exc).__name__})")
                stop_reason = "failed"
                answer = trace.best_answer if trace.has_incumbent else trace.current_answer
                notes = trace.best_scratchpad if trace.has_incumbent else trace.current_scratchpad
                trace.next_tier = index + 1
                metered.flush()
                continue
            answer, notes = result.answer, result.scratchpad
            trace.tier_stops.append(f"{tier.model}: {result.stop_reason}")
            stop_reason = result.stop_reason
            if result.halted:
                return finish(True, stop_reason)
            # Only committed progress crosses a tier boundary when an incumbent
            # exists. Unscored exploration is retained in the trace/archive.
            if trace.has_incumbent:
                answer, notes = trace.best_answer, trace.best_scratchpad
            trace.next_tier = index + 1
            metered.flush()
        return finish(False, stop_reason)
    except BudgetExhausted:
        return finish(False, "budget")
    except (ContextLimitError, MemoryLimitError) as exc:
        trace.error = type(exc).__name__
        return finish(False, "context-budget" if isinstance(exc, ContextLimitError) else "memory-budget")
    except KeyboardInterrupt:
        trace.error = "KeyboardInterrupt"
        return finish(False, "interrupted")
    except CheckpointWriteError as exc:
        trace.error = type(exc).__name__
        return finish(False, "checkpoint-error")
    except Exception as exc:
        trace.error = f"run failed: {type(exc).__name__}"
        finish(False, "error")
        raise RunError(exc, trace) from exc
    finally:
        trace.wall_seconds = past_wall + time.monotonic() - start
        try:
            metered.flush()
        except CheckpointWriteError:
            trace.error = "CheckpointWriteError"
            trace.halted = False
            trace.stop_reason = "checkpoint-error"
            trace.needs_human_review = True


def plan_schedule(cfg: RecurseConfig | None = None) -> str:
    cfg = cfg or RecurseConfig()
    cfg.validate()
    lines = ["Recursion schedule; model identifiers and order are operator-selected."]
    nominal = worst = 0
    for index, tier in enumerate(cfg.ladder):
        steps = cfg.steps_for(tier)
        ordinary = steps * (cfg.n + 1 + cfg.judge_votes)
        retries = steps * (cfg.n + 1 + 2 * cfg.judge_votes)
        nominal += ordinary
        worst += retries
        lines.append(f"tier {index}: {tier.model}; {steps} x ({cfg.n} notes + 1 answer + "
                     f"{cfg.judge_votes} judge) = {ordinary}; up to {retries} with parse retries")
    lines.append(f"Nominal maximum: {nominal}; maximum including judge retries: {worst}.")
    # This base schedule is NOT the total once memory/control calls are enabled.
    extra = (len(cfg.ladder) if cfg.preseed_ladder else 0)
    if cfg.enforce_progress and (cfg.seed_answer or cfg.resume_from):
        extra += 2 * cfg.judge_votes
    retrieval_max = (sum(cfg.steps_for(t) * (cfg.n + 1) * cfg.memory_max_rounds for t in cfg.ladder)
                     + (len(cfg.ladder) * cfg.memory_max_rounds if cfg.preseed_ladder else 0)) if cfg.workspace is not None else (
                     sum(cfg.steps_for(t) * cfg.n * cfg.memory_max_rounds for t in cfg.ladder) if cfg.use_headroom else 0)
    lines.append(f"Additional ceilings: {extra} seed/planning calls; {retrieval_max} requested archive replay calls.")
    lines.append(f"Absolute scheduled ceiling (before hard caps): {worst + extra + retrieval_max}.")
    if cfg.workspace is not None:
        lines.append(f"Bounded archive workspace: {cfg.workspace.budget} visible input units; worker answers must use workspace_patch. Whole judges remain exact.")
    if cfg.enforce_progress:
        lines.append(f"Common judge: {cfg.judge_model or cfg.ladder[-1].model}; obligations + nondecreasing incumbent score enforced.")
    if cfg.max_total_calls is not None:
        lines.append(f"Attempted-completion cap: {cfg.max_total_calls}; checked before every call, including auxiliary work.")
    if cfg.max_wall_seconds is not None:
        lines.append(f"Cumulative cooperative deadline: {cfg.max_wall_seconds}s; backend must bound its own calls.")
    return "\n".join(lines)
