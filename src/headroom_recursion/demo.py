"""A deterministic arithmetic worker, not a neural model or performance result."""
from fractions import Fraction
import re
from . import prompts
from .config import Verdict

PROBLEM = "Find a positive rational q with |q*q - 2| < 1/10^12. Return only q."
TOLERANCE = Fraction(1, 10**12)


def _latest(text: str) -> Fraction:
    matches = re.findall(r"estimate=([0-9]+(?:/[0-9]+)?)", text)
    return Fraction(matches[-1]) if matches else Fraction(1)


def complete(**request) -> str:
    """Newton's rational iteration q <- (q + 2/q)/2 inside the note updates."""
    system, user = request["system"], request["user"]
    if system == prompts.LATENT_SYSTEM:
        q = _latest(user)
        q = (q + 2 / q) / 2
        return f"estimate={q}\nCheck the squared residual with exact rational arithmetic."
    if system == prompts.ANSWER_SYSTEM:
        return str(_latest(user))
    if system == prompts.HALT_SYSTEM:
        # A demo judge never authorizes a halt. Only the exact tolerance check can.
        return '{"halt_prob": 0.0, "reason": "defer to the exact rational check"}'
    raise ValueError("unknown demo operation")


def validator(answer: str) -> Verdict:
    if len(answer) > 10000 or not re.fullmatch(r"[0-9]+(?:/[0-9]+)?", answer.strip()):
        return Verdict(False, note="expected a positive rational")
    try:
        q = Fraction(answer.strip())
    except (ValueError, ZeroDivisionError):
        return Verdict(False, note="invalid rational")
    return Verdict(q > 0 and abs(q*q - 2) < TOLERANCE,
                   note="exactly checks the stated squared-residual tolerance, not equality with an irrational number")
