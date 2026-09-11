"""Offline governance demonstration; an exact arithmetic task, not neural inference.

The deliberately limited baseline declines odd inputs. The child computes all
integer squares. A separately defined checker verifies both answers and UNKNOWN.
Metrics are constructed demonstration data, not a real deployment benchmark.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from headroom_recursion.folding import (
    Evaluator, Folding, Policy, Proposal, Store, canonical, decode,
    generation_packet, sha,
)


def evaluate(artifact: bytes, case: dict) -> dict:
    mode = decode(artifact)["mode"]
    x = case["integer"]
    answer = None if mode == "even-only" and x % 2 else x * x
    return {"loss": float(answer is None), "cost": 1,
            "output": {"status": "UNKNOWN" if answer is None else "OK", "answer": answer}}


def verify(case: dict, output: dict) -> bool:
    if output == {"status": "UNKNOWN", "answer": None}:
        return True
    return (set(output) == {"status", "answer"} and output["status"] == "OK"
            and type(output["answer"]) is int and output["answer"] == case["integer"] ** 2)


def main() -> None:
    evaluator = Evaluator(sha(Path(__file__).read_bytes()), evaluate, verify)
    policy = Policy(
        scope="arithmetic-fold-demo", objective="More exactly checked answers",
        metric="Decline rate; lower is better", population="Constructed odd integers only",
        evaluator_hash=evaluator.code_hash, min_effect=0.05, max_candidates=1,
        premise_units=3, screen_units=20, validation_units=40, holdout_units=40,
    )
    units = {phase: [{"integer": 2*(start+i)+1} for i in range(n)]
             for phase, start, n in [("screen", 0, 20), ("validation", 100, 40), ("holdout", 200, 40)]}
    with tempfile.TemporaryDirectory(prefix="fold-demo-") as directory:
        store = Store(directory)
        try:
            fold = Folding.create(store, policy, canonical({"mode": "even-only"}), units, evaluator)
            proposal = Proposal(
                "allow-odd-integers", fold.state["champion"], store.put_json({"mode": "all-integers"}),
                "Remove the baseline's even-input-only restriction.",
                "More checked answers on the declared odd-integer test family.",
                "Any incorrect square, resource failure, or failed confirmation margin.",
                "Deterministic exact arithmetic with explicit decline.",
            )
            candidate = fold.freeze(proposal)
            packet = generation_packet(fold, candidate, max_chars=4096)
            records = [fold.evaluate(candidate, phase) for phase in ("premise", "screen", "validation", "holdout")]
            admission = fold.promote(candidate)
            print(json.dumps({
                "packet_characters": len(packet.text),
                "phases": [{"phase": r["phase"], "passed": r["passed"], "summary": r["summary"]} for r in records],
                "admission": fold.admission(admission), "integrity": store.audit(),
                "scope": "Constructed offline workflow test; not independent statistical population evidence.",
            }, indent=2))
        finally:
            store.close()


if __name__ == "__main__":
    main()
