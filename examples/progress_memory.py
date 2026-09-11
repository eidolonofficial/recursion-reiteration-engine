"""Offline integration demonstration, NOT a neural-model benchmark.

Shows actual compression, model-protocol seed selection, and a mechanically
blocked regression. The worker is deterministic so this example is reproducible.
"""
from __future__ import annotations

import json
from headroom_recursion import CallableClient, ProgressCheck, RecurseConfig, Tier, recurse
from headroom_recursion import prompts
from headroom_recursion.progress import PLAN_SYSTEM

EXACT = "<verbatim>\nThe target requires q > 0 and |q*q - 2| < 1/10^12.\n</verbatim>\n\n"
NOTES = EXACT + ("A routine branch was inspected and its bookkeeping recorded.\n\n" * 180)
PROBLEM = "Develop a positive rational approximation; retain the established positivity condition."


def worker(**request):
    system, user = request["system"], request["user"]
    if system == PLAN_SYSTEM:
        data = json.loads(user.split("(data):\n", 1)[1].split("\nOPERATOR PROGRESS", 1)[0])
        return json.dumps({"keep": [row["id"] for row in data["candidates"][:data["max_keep"]]],
                           "next_check": "Refine the residual without losing positivity."})
    if system.startswith(prompts.LATENT_SYSTEM):
        assert EXACT in user
        assert user.count("routine branch") < 180, "the worker must receive the compressed scratchpad"
        return NOTES
    if system == prompts.ANSWER_SYSTEM:
        # Deliberately wrong revision: the controller must refuse it even if an
        # imagined judge would assign a flattering score.
        return "-1"
    if system == prompts.HALT_SYSTEM:
        return '{"halt_prob":0.5,"reason":"demonstration score, not proof"}'
    raise ValueError("unknown operation")


def positive(answer):
    from fractions import Fraction
    try:
        return Fraction(answer) > 0
    except (ValueError, ZeroDivisionError):
        return False


def run():
    cfg = RecurseConfig(n=1, T=1, ladder=(Tier("small-local"), Tier("large-local")),
                        seed_answer="1", seed_scratchpad=NOTES,
                        scratchpad_tokens=320, progress_tokens=512,
                        progress_checks=(ProgressCheck("positive-q", "q > 0", positive),),
                        max_total_calls=16)
    trace = recurse(PROBLEM, client=CallableClient(worker), config=cfg)
    assert trace.final_answer == "1"
    assert trace.locked_checks == ["positive-q"]
    assert trace.tokens_saved > 0
    assert all(not step.progress_accepted for step in trace.steps)
    return trace


if __name__ == "__main__":
    trace = run()
    print(json.dumps({"stop_reason": trace.stop_reason, "final_answer": trace.final_answer,
                      "calls": trace.total_calls, "input_before": trace.tokens_before,
                      "input_after": trace.tokens_after, "gross_saved": trace.tokens_saved,
                      "auxiliary_input_output": trace.auxiliary_tokens,
                      "counter": trace.token_count_kind, "locked_checks": trace.locked_checks,
                      "compression_events": trace.compression_events}, indent=2))
