"""Strict, provider-neutral contracts. A proposal contains no evidence authority."""
from __future__ import annotations
import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass, fields
from typing import Any

class FoldError(ValueError):
    """A contract failed; no promotion should occur."""


def canonical(value: Any) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                          allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, OverflowError, UnicodeError, RecursionError) as exc:
        raise FoldError("not finite JSON data") from exc


def decode(raw: bytes | str) -> Any:
    def pairs(items):
        d = {}
        for k, v in items:
            if k in d:
                raise FoldError("duplicate JSON field")
            d[k] = v
        return d
    def constant(_):
        raise FoldError("nonfinite JSON number")
    try:
        obj = json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
        canonical(obj)  # also rejects e.g. 1e999
        return obj
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise FoldError("invalid strict JSON") from exc


def sha(raw: bytes) -> str:
    if not isinstance(raw, bytes):
        raise FoldError("hash inputs must be bytes")
    return hashlib.sha256(raw).hexdigest()


def identity(value: Any) -> str:
    return sha(canonical(value))


def text(name: str, value: Any, limit: int = 2000) -> None:
    if type(value) is not str or not value.strip() or len(value) > limit:
        raise FoldError(f"{name}: nonempty string of at most {limit} characters required")


def digest(name: str, value: Any) -> None:
    if type(value) is not str or not re.fullmatch(r"[a-f0-9]{64}", value):
        raise FoldError(f"{name}: SHA-256 digest required")


def integer(name: str, value: Any, low: int = 1, high: int = 10**9) -> None:
    if type(value) is not int or not low <= value <= high:
        raise FoldError(f"{name}: integer in [{low}, {high}] required")


def number(name: str, value: Any, low: float, high: float) -> None:
    if type(value) not in (float, int) or not low <= value <= high or not math.isfinite(value):
        raise FoldError(f"{name}: finite number in [{low}, {high}] required")


def exact_fields(obj: Any, expected: set[str]) -> None:
    if type(obj) is not dict or set(obj) != expected:
        raise FoldError("missing or unsupported fields")


@dataclass(frozen=True)
class Policy:
    scope: str
    objective: str
    metric: str
    population: str
    evaluator_hash: str
    min_effect: float = 0.01
    alpha: float = 0.05
    max_candidates: int = 8
    premise_units: int = 3
    screen_units: int = 20
    validation_units: int = 40
    holdout_units: int = 40
    max_cost: float = 1_000_000
    max_seconds: float = 30.0
    schema_version: int = 1

    def __post_init__(self):
        for k in ("scope", "objective", "metric", "population"):
            text(k, getattr(self, k), 1000)
        digest("evaluator_hash", self.evaluator_hash)
        number("min_effect", self.min_effect, 0, 1)
        number("alpha", self.alpha, 1e-12, .5)
        for k in ("max_candidates", "premise_units", "screen_units", "validation_units", "holdout_units"):
            integer(k, getattr(self, k))
        if self.premise_units > self.screen_units:
            raise FoldError("premise units must be a subset of development units")
        number("max_cost", self.max_cost, 1e-12, 1e18)
        number("max_seconds", self.max_seconds, 1e-6, 86400)
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise FoldError("unsupported policy version")

    @classmethod
    def parse(cls, obj):
        exact_fields(obj, {f.name for f in fields(cls)})
        return cls(**obj)


@dataclass(frozen=True)
class Proposal:
    """All fields freeze before evaluations. No score/status/result fields exist."""
    name: str
    base: str
    artifact: str
    mechanism: str
    prediction: str
    falsifier: str
    bias_class: str
    components: tuple[str, ...] = ()
    schema_version: int = 1

    def __post_init__(self):
        text("name", self.name, 100)
        for k in ("mechanism", "prediction", "falsifier", "bias_class"):
            text(k, getattr(self, k))
        digest("base", self.base)
        digest("artifact", self.artifact)
        if type(self.components) is not tuple or len(self.components) not in (0, 2):
            raise FoldError("a combination requires exactly two components")
        if any(type(ref) is not str for ref in self.components):
            raise FoldError("component IDs must be strings")
        if len(set(self.components)) != len(self.components):
            raise FoldError("duplicate components")
        for ref in self.components:
            digest("component", ref)
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise FoldError("unsupported proposal version")

    @classmethod
    def parse(cls, obj):
        exact_fields(obj, {f.name for f in fields(cls)})
        if type(obj["components"]) is not list:
            raise FoldError("components must be a JSON list")
        return cls(**{**obj, "components": tuple(obj["components"])})


def bounded_difference_summary(rows: list[dict], policy: Policy) -> dict:
    """One-sided Hoeffding bound for independent paired unit differences in [-1,1].

    The fixed family contains at most max_candidates hypotheses and two confirmatory
    gates per hypothesis. Independence / population sampling are operator obligations,
    not facts inferable from different case hashes. Screening is exploratory.
    """
    if not rows:
        raise FoldError("empty matched evidence")
    deltas = []
    failures = 0
    for row in rows:
        exact_fields(row, {"unit", "base", "child"})
        digest("unit", row["unit"])
        for side in ("base", "child"):
            m = row[side]
            exact_fields(m, {"loss", "cost", "seconds", "correct", "failed", "evidence"})
            for k in ("correct", "failed"):
                if type(m[k]) is not bool:
                    raise FoldError("measurement flags must be booleans")
            number("loss", m["loss"], 0, 1)
            number("cost", m["cost"], 0, 1e18)
            number("seconds", m["seconds"], 0, 86400*365)
            digest("evidence", m["evidence"])
            failures += int(m["failed"] or not m["correct"] or
                            m["cost"] > policy.max_cost or m["seconds"] > policy.max_seconds)
        deltas.append(row["child"]["loss"]-row["base"]["loss"])
    if len({r["unit"] for r in rows}) != len(rows):
        raise FoldError("duplicate evaluation units")
    mean = math.fsum(deltas)/len(deltas)
    alpha = policy.alpha/(2*policy.max_candidates)
    radius = math.sqrt(2*math.log(1/alpha)/len(deltas))
    return {"units": len(deltas), "mean_delta": mean, "upper_bound": min(1.0, mean+radius),
            "alpha_per_gate": alpha, "failures": failures,
            "method": "one-sided-Hoeffding-paired-difference-range-2",
            "scope": "declared population/metric only; not a mathematical theorem"}


def data(obj):
    return decode(canonical(asdict(obj)))


def interaction_summary(rows: list[dict], policy: Policy) -> dict:
    """Recompute all four arms, not merely the base-versus-combination contrast."""
    if type(rows) is not list or not rows:
        raise FoldError("empty factorial evidence")
    for row in rows:
        exact_fields(row, {"unit", "arms"})
        if type(row["arms"]) is not list or len(row["arms"]) != 4:
            raise FoldError("factorial interaction requires four complete arms")
    base_child = [{"unit": r["unit"], "base": r["arms"][0], "child": r["arms"][3]} for r in rows]
    components = [{"unit": r["unit"], "base": r["arms"][1], "child": r["arms"][2]} for r in rows]
    summary = bounded_difference_summary(base_child, policy)
    middle = bounded_difference_summary(components, policy)
    summary["factorial_interaction_mean"] = math.fsum(
        r["arms"][3]["loss"]-r["arms"][1]["loss"]-r["arms"][2]["loss"]+r["arms"][0]["loss"]
        for r in rows)/len(rows)
    summary["all_arm_failures"] = summary["failures"]+middle["failures"]
    summary["interaction_scope"] = "development diagnostic; not a synergy theorem"
    return summary
