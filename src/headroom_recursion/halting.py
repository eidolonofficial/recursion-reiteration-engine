"""Strict judge parsing and median voting; scores are not calibrated probabilities."""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from . import prompts
from .clients import strict_json
from .runtime import complete_prompt

_UNPARSEABLE = "unparseable judge reply"


@dataclass
class HaltVerdict:
    halt_prob: float
    reason: str
    tokens_before: int = 0
    tokens_after: int = 0
    calls: int = 1
    valid_votes: int = 0


def _parse(text: str) -> tuple[float, str]:
    """Only a complete strict JSON object can authorize a heuristic halt.

    No prose-number fallback, boolean-as-number, clamping, duplicate keys,
    non-finite floats, or scanning for a more favorable nested JSON object.
    """
    if not isinstance(text, str):
        return 0.0, _UNPARSEABLE
    try:
        obj = strict_json(text)
    except (ValueError, TypeError):
        return 0.0, _UNPARSEABLE
    if not isinstance(obj, dict):
        return 0.0, _UNPARSEABLE
    value = obj.get("halt_prob")
    reason = obj.get("reason", "")
    if (type(value) not in (float, int) or not math.isfinite(value)
            or not 0 <= value <= 1 or not isinstance(reason, str)):
        return 0.0, _UNPARSEABLE
    return float(value), reason[:1000]


def judge(client, *, model: str, problem: str, answer: str, scratchpad: str,
          max_tokens: int, use_headroom: bool, votes: int = 1, role: str = "judge") -> HaltVerdict:
    if type(votes) is not int or votes < 1:
        raise ValueError("votes must be a positive integer")
    results = []
    before = after = calls = 0
    for _ in range(votes):
        pair = (0.0, _UNPARSEABLE)
        for attempt in range(2):
            result = complete_prompt(client, role=role, model=model, system=prompts.HALT_SYSTEM,
                                     template=prompts.HALT_JUDGE,
                                     values=dict(problem=problem, answer=answer, scratchpad=scratchpad),
                                     max_tokens=max_tokens,
                                     temperature=0.0 if votes == 1 or attempt else 0.3,
                                     use_headroom=use_headroom)
            calls += 1
            before += result.tokens_before
            after += result.tokens_after
            pair = ((0.0, _UNPARSEABLE) if result.stop_reason in {"max_tokens", "length"} else _parse(result.text))
            if pair[1] != _UNPARSEABLE:
                break
        results.append(pair)
    median = float(statistics.median(score for score, _ in results))
    reason = min(results, key=lambda pair: abs(pair[0] - median))[1]
    return HaltVerdict(median, reason, before, after, calls, sum(reason != _UNPARSEABLE for _, reason in results))
