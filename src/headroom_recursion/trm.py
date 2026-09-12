"""The source recurrence: n working-note updates, one answer update, then judge.

Text-state control is retained without binding F or G to a particular model.
The controller iterates text state; it does not train model weights.
"""
from __future__ import annotations

import time
import math
from dataclasses import dataclass
from . import claims as claims_mod
from . import halting, prompts
from .config import RecurseConfig, Tier, Verdict
from .trace import RunTrace, StepTrace
from .runtime import complete_prompt
from .clients import TransportError
from .worker_actions import checked_notes, record_rejection


@dataclass
class TierResult:
    answer: str
    scratchpad: str
    halted: bool
    stop_reason: str


def _norm(text: str) -> str:
    # Case and operators can carry mathematical meaning. Do not erase them.
    return text.replace("\r\n", "\n").strip()


def _preview(text: str, n: int = 160) -> str:
    text = text.strip().replace("\n", " ")
    return text if len(text) <= n else text[:n - 1] + "…"


def _bound_snippets(snippets: list[str], max_chars: int) -> list[str]:
    output = []
    for snippet in snippets:
        room = max_chars - sum(map(len, output))
        if room <= 0:
            break
        if isinstance(snippet, str) and snippet.strip():
            if len(snippet.strip()) <= room:
                output.append(snippet.strip())
    return output


def _retrieve(cfg: RecurseConfig, problem: str, scratchpad: str) -> tuple[list[str], str]:
    if cfg.retriever is None:
        return [], ""
    query = (problem + "\n\n" + scratchpad)[:cfg.retrieval_query_chars]
    try:
        results = cfg.retriever.retrieve(query, k=cfg.retrieval_k)
        if not isinstance(results, (list, tuple)):
            raise TypeError("retriever must return a list of strings")
        chosen = list(results)[:cfg.retrieval_k]
        bounded = _bound_snippets(chosen, cfg.retrieval_max_chars)
        note = "whole reference items omitted by raw character cap" if len(bounded) < len(chosen) else ""
        return bounded, note
    except Exception as exc:
        return [], f"retrieval failed: {type(exc).__name__}"


def _safe_validate(validator, answer: str) -> tuple[bool, str, Verdict | None]:
    if validator is None:
        return False, "", None
    if not answer.strip():
        return False, "empty candidate cannot be validated", None
    try:
        result = validator(answer)
        if isinstance(result, Verdict):
            return result.passed, "", result
        if type(result) is not bool:
            raise TypeError("validator must return bool or Verdict, not a truthy object")
        return result, "", None
    except Exception as exc:
        return False, f"validator failed: {type(exc).__name__}", None


def _objective(cfg, answer):
    if cfg.objective is None: return None, ""
    try:
        value=cfg.objective(answer)
        if type(value) not in (int,float) or not math.isfinite(value):
            raise ValueError("objective must be a finite number")
        return value, ""
    except Exception as exc:
        return None, "objective unavailable: "+type(exc).__name__


def _safe_feedback(feedback, answer: str) -> str:
    try:
        value = feedback(answer)
        if value is not None and not isinstance(value, str):
            raise TypeError("feedback must return a string")
        return (value or "").strip()[:4000]
    except Exception as exc:
        return f"feedback failed: {type(exc).__name__}"


def judgment_context(cfg: RecurseConfig, problem: str, answer: str,
                     *, passed: bool, validator_error: str) -> tuple[str, int, int]:
    """Use identical audit/partial-gate framing for seeds and later revisions.

    Tool outcomes are data under declared coverage, never new proof authority.
    Sharing this path avoids grading the incumbent with a different rubric.
    """
    context = problem + (f"\n\n[ORACLE STATUS] {cfg.oracle_note}" if cfg.oracle_note else "")
    claim_note = ""
    unsourced = flagged = 0
    audit_retriever = cfg.audit_retriever or cfg.retriever
    if cfg.claim_audit and audit_retriever is not None:
        try:
            audited = claims_mod.audit_claims(claims_mod.parse_claims(answer), audit_retriever)
            claim_note = claims_mod.judge_addendum(audited)
            unsourced = sum(c.label == "UNSOURCED" for c in audited)
            flagged = sum(c.label == "NEW" and bool(c.prior_art) for c in audited)
        except Exception as exc:
            claim_note = f"[CLAIM AUDIT] Unavailable ({type(exc).__name__}); nothing verified."
    gate_note = ""
    if cfg.validator is not None and not cfg.oracle_sufficient:
        gate_note = ("Gate unavailable; nothing checked." if validator_error else
                     "Gate passed only the operator-declared partial coverage." if passed else
                     "Gate rejected the candidate.")
    return context + "\n" + claim_note + "\n" + gate_note, unsourced, flagged


def run_tier(client, cfg: RecurseConfig, tier: Tier, problem: str,
             answer: str, scratchpad: str, trace: RunTrace,
             deadline: float | None = None, tier_index: int = 0) -> TierResult:
    seen = {_norm(answer)} if answer else set()
    trace.current_model = tier.model
    start_step = trace.completed_steps[tier_index] if trace.completed_steps else 0
    for _ in range(start_step, cfg.steps_for(tier)):
        client.check()
        step_start = time.monotonic()
        prior_answer, prior_notes = answer, scratchpad
        snippets, retrieval_error = _retrieve(cfg, problem, scratchpad)
        memory_context = ""
        if cfg.memory_session is not None:
            if not client.memory_ready:
                memory_context = client.memory_context(problem, scratchpad)
            client.memory_ready = False
        # Structure/provenance labels live in the template, not in the text being
        # compressed. Whole reference items retain their internal mathematics.
        context = "\n\n".join(snippets + ([memory_context] if memory_context else []))
        rejected = 0
        truncated = False
        before, after = trace.tokens_before, trace.tokens_after
        for _ in range(cfg.n):
            result = complete_prompt(client, role="notes", model=tier.model, system=prompts.LATENT_SYSTEM,
                                     template=prompts.LATENT_UPDATE,
                                     values=dict(problem=problem, context=context,
                                                 answer=answer or "(none yet)", scratchpad=scratchpad or "(empty)"),
                                     max_tokens=tier.max_tokens, temperature=cfg.temperature,
                                     use_headroom=cfg.use_headroom)
            client.store.put(result.text)
            text = result.text.strip()
            cut = result.stop_reason in {"max_tokens", "length"}
            if text and not cut:
                try:
                    checked_notes(text)
                except TransportError:
                    trace.feedback = "Return working notes, not a tool request."
                    rejected += 1
                    record_rejection(trace, "note", text, cfg.max_repeated_rejections)
                    client.flush()
                    continue
                scratchpad = text
                trace.current_scratchpad = scratchpad
            else:
                rejected += 1
            truncated |= cut
            client.flush()
        result = complete_prompt(client, role="answer", model=tier.model, system=prompts.ANSWER_SYSTEM,
                                 template=prompts.ANSWER_UPDATE,
                                 values=dict(problem=problem, context=context, scratchpad=scratchpad,
                                             answer=answer or "(none yet)"),
                                 max_tokens=tier.max_tokens, temperature=cfg.temperature,
                                 use_headroom=cfg.use_headroom)
        client.store.put(result.text)
        cut = result.stop_reason in {"max_tokens", "length"}
        # Workspace deltas preserve unedited bytes, including outer whitespace.
        new_answer = result.text if cfg.workspace is not None else result.text.strip()
        fresh_output = bool(new_answer.strip()) and not cut
        if fresh_output:
            answer = new_answer
            trace.current_answer = answer
            trace.current_rejected = False
        else:
            rejected += 1
        truncated |= cut
        client.flush()
        converged = bool(answer) and _norm(answer) in seen
        if answer:
            seen.add(_norm(answer))
        progress = client.guard.evaluate(answer)
        passed, validator_error, verdict_obj = _safe_validate(cfg.validator, answer)
        objective_value, objective_error = _objective(cfg,answer) if progress.accepted else (None, "")
        validator_error = validator_error or objective_error
        eligible_output = bool(answer) and not cut
        validated = bool(cfg.validator is not None and cfg.oracle_sufficient
                         and passed and not validator_error and eligible_output and progress.accepted)
        gate_rejected = bool(cfg.validator is not None and not cfg.oracle_sufficient
                             and not passed and not validator_error)
        trace.current_rejected = bool(validator_error or gate_rejected or not eligible_output or not progress.accepted)
        judge_context, unsourced, flagged = judgment_context(
            cfg, problem, answer, passed=passed, validator_error=validator_error)
        judge_calls = 0
        valid_score = True
        if validated:
            score, reason = 1.0, "operator-supplied sufficient validator passed"
        elif validator_error or gate_rejected or not eligible_output or not progress.accepted:
            score, reason = 0.0, "mechanically rejected, regressed, or incomplete candidate; judge skipped"
            valid_score = False
        elif cfg.objective is not None:
            score, reason = 0.0, "host-checked feasible candidate; optimality not established"
        else:
            # One operator-selected judge for all tiers makes the incumbent score
            # comparable under a fixed rubric. This does not calibrate that score.
            judge_model = cfg.judge_model or (cfg.ladder[-1].model if cfg.enforce_progress else tier.model)
            judgment = halting.judge(client, model=judge_model,
                                     problem=judge_context,
                                     answer=answer, scratchpad=scratchpad,
                                     max_tokens=min(256, cfg.ladder[-1].max_tokens if cfg.enforce_progress else tier.max_tokens),
                                     use_headroom=cfg.use_headroom and cfg.compress_judge,
                                     votes=cfg.judge_votes)
            score, reason, judge_calls = judgment.halt_prob, judgment.reason, judgment.calls
            valid_score = judgment.valid_votes > cfg.judge_votes // 2
        nonregression = (not cfg.enforce_progress or not trace.has_incumbent or
                         (trace.seed_scored and score >= trace.best_halt_prob) or validated)
        if cfg.objective is not None:
            nonregression = objective_value is not None and (trace.best_objective is None or objective_value >= trace.best_objective)
        accepted = bool(eligible_output and not validator_error and not gate_rejected and progress.accepted and valid_score and nonregression)
        converged = converged and accepted
        if accepted:
            if cfg.objective is not None: trace.best_objective = objective_value
            if answer != prior_answer:
                trace.rejection_counts.clear()
            trace.feedback = ""
            client.guard.commit(progress)
            trace.seed_scored = True
            trace.note_candidate(answer=answer, halt_prob=score, model=tier.model,
                                 scratchpad=scratchpad, eligible=True)
        halted = bool(accepted and (validated or (cfg.judge_can_halt and score >= cfg.halt_threshold)))
        if halted and validated and verdict_obj:
            trace.validated_confidence = verdict_obj.confidence
            trace.settles_at = verdict_obj.settles_at or ""
        reason_stop = "validated" if halted and validated else "halt" if halted else "converged" if converged else "exhausted"
        trace.add(StepTrace(
            tier_model=tier.model, step_index=len(trace.steps), latent_calls=cfg.n,
            answer_preview=_preview(answer), answer=answer, scratchpad=scratchpad,
            halt_prob=score, halted=halted, converged=converged, reason=reason,
            retrieved_snippets=len(snippets), retrieval_error=retrieval_error,
            unsourced_claims=unsourced, flagged_new_claims=flagged,
            gate_rejected=gate_rejected, rejected_updates=rejected,
            truncated=truncated, validator_error=validator_error, judge_calls=judge_calls,
            tokens_before=trace.tokens_before - before, tokens_after=trace.tokens_after - after,
            progress_accepted=accepted, progress_missing=list(progress.missing), progress_errors=list(progress.errors)))
        if trace.completed_steps:
            trace.completed_steps[tier_index] += 1
        trace.progress_events.append({"event": "candidate", "model": tier.model, "accepted": accepted,
                                      "score": score, "missing": list(progress.missing),
                                      "nonregression": nonregression, "fresh_output": fresh_output,
                                      "objective": objective_value})
        rejected_answer = answer
        if not accepted and cfg.enforce_progress and trace.has_incumbent:
            # Roll back BOTH components; do not pair old answers with unapproved
            # new notes. Feedback remains separate, labelled and recoverable.
            answer, scratchpad = trace.best_answer, trace.best_scratchpad
            trace.current_rejected = False
            scratchpad += ("\n\n[REVISION REJECTED] Preserve the incumbent. " +
                           ("Lost obligations: " + ", ".join(progress.missing) if progress.missing else
                            "The proposal did not meet the common judge/validity baseline."))
        if not accepted and cfg.enforce_progress and not trace.has_incumbent:
            answer, scratchpad = prior_answer, prior_notes
        if cfg.feedback is not None and not halted:
            trace.feedback = _safe_feedback(cfg.feedback, rejected_answer)
        trace.current_answer, trace.current_scratchpad = answer, scratchpad
        client.flush()
        if accepted and cfg.memory_session is not None:
            client.memory_accept(problem, prior_answer, answer, scratchpad)
        if not accepted:
            identity = rejected_answer
            if cfg.candidate_identity is not None:
                try:
                    identity = cfg.candidate_identity(rejected_answer)
                    if type(identity) is not str or len(identity)>32768: raise ValueError("invalid task identity")
                except Exception:
                    identity = rejected_answer
                    trace.progress_events.append({"event":"identity-fallback","kind":"exact-text"})
            record_rejection(trace, "candidate", identity, cfg.max_repeated_rejections)
        if halted:
            return TierResult(answer, scratchpad, True, reason_stop)
        if converged:
            return TierResult(answer, scratchpad, False, "converged")
        if tier.step_timeout_s is not None and time.monotonic() - step_start > tier.step_timeout_s:
            return TierResult(answer, scratchpad, False, "step-timeout")
    return TierResult(answer, scratchpad, False, "exhausted")
