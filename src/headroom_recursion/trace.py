"""Full candidate states and completion accounting for local recursive runs."""
from __future__ import annotations

import json
import os
import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class StepTrace:
    tier_model: str
    step_index: int
    latent_calls: int
    answer_preview: str
    halt_prob: float
    halted: bool
    converged: bool
    reason: str = ""
    answer: str = ""
    scratchpad: str = ""
    retrieved_snippets: int = 0
    retrieval_error: str = ""
    unsourced_claims: int = 0
    flagged_new_claims: int = 0
    gate_rejected: bool = False
    rejected_updates: int = 0
    truncated: bool = False
    validator_error: str = ""
    judge_calls: int = 0
    tokens_before: int = 0
    tokens_after: int = 0
    progress_accepted: bool = True
    progress_missing: list[str] = field(default_factory=list)
    progress_errors: list[str] = field(default_factory=list)

    @property
    def tokens_saved(self) -> int:
        return max(0, self.tokens_before - self.tokens_after)


@dataclass
class RunTrace:
    problem: str
    final_answer: str = ""
    halted: bool = False
    stop_reason: str = ""
    final_model: str = ""
    best_answer: str = ""
    best_scratchpad: str = ""
    best_halt_prob: float = -1.0
    best_step_index: int = -1
    best_model: str = ""
    current_answer: str = ""
    current_scratchpad: str = ""
    current_model: str = ""
    current_rejected: bool = False
    tier_stops: list[str] = field(default_factory=list)
    error: str = ""
    wall_seconds: float = 0.0
    oracle_rung: int = 0
    oracle_residuals: list[str] = field(default_factory=list)
    oracle_calls: int = 0
    oracle_gate_only: bool = False
    validated_confidence: float = 1.0
    needs_human_review: bool = True
    settles_at: str = ""
    steps: list[StepTrace] = field(default_factory=list)
    attempted_calls: int = 0
    successful_calls: int = 0
    reported_tokens_before: int = 0
    reported_tokens_after: int = 0
    has_incumbent: bool = False
    seed_scored: bool = False
    token_count_kind: str = "estimated-utf8-bytes/4"
    auxiliary_tokens: int = 0
    compression_events: list[dict] = field(default_factory=list)
    workspace_events: list[dict] = field(default_factory=list)
    progress_events: list[dict] = field(default_factory=list)
    call_events: list[dict] = field(default_factory=list)
    memory_archive: dict[str, str] = field(default_factory=dict)
    locked_checks: list[str] = field(default_factory=list)
    completed_steps: list[int] = field(default_factory=list)
    next_tier: int = 0
    resumed: bool = False
    rejection_counts: dict[str, int] = field(default_factory=dict)
    feedback: str = ""
    best_objective: float | None = None

    def add(self, step: StepTrace) -> None:
        self.steps.append(step)

    def note_candidate(self, *, answer: str, halt_prob: float, model: str,
                       scratchpad: str = "", eligible: bool = True) -> None:
        # Rejected, incomplete, or mechanically disproved candidates cannot win.
        if eligible and answer.strip() and halt_prob >= self.best_halt_prob:
            self.has_incumbent = True
            self.best_answer = answer
            self.best_scratchpad = scratchpad
            self.best_halt_prob = halt_prob
            self.best_step_index = len(self.steps)
            self.best_model = model

    @property
    def total_calls(self) -> int:
        return self.attempted_calls

    @property
    def tokens_before(self) -> int:
        return self.reported_tokens_before

    @property
    def tokens_after(self) -> int:
        return self.reported_tokens_after

    @property
    def tokens_saved(self) -> int:
        return max(0, self.tokens_before - self.tokens_after)

    @property
    def savings_pct(self) -> float:
        return 100 * self.tokens_saved / self.tokens_before if self.tokens_before else 0.0

    def trajectory(self) -> str:
        # Opaque identifiers are preserved; hyphens do not imply a provider schema.
        groups = []
        for step in self.steps:
            if groups and groups[-1][0] == step.tier_model:
                groups[-1][1].append(f"{step.halt_prob:.2f}")
            else:
                groups.append((step.tier_model, [f"{step.halt_prob:.2f}"]))
        return " | ".join(f"{model}: {' '.join(scores)}" for model, scores in groups)

    def to_dict(self) -> dict:
        result = asdict(self)
        result.update(schema_version=2, total_calls=self.total_calls,
                      tokens_before=self.tokens_before, tokens_after=self.tokens_after,
                      tokens_saved=self.tokens_saved, savings_pct=self.savings_pct,
                      compression_net_of_auxiliary_tokens=self.tokens_saved - self.auxiliary_tokens)
        return result

    def persist(self, directory: str | Path, stem: str | None = None) -> str:
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        stem = stem or f"run-{uuid.uuid4().hex}"
        if (not isinstance(stem, str) or not stem or stem in (".", "..")
                or Path(stem).name != stem or any(c in stem for c in ("/", "\\", "\0"))):
            raise ValueError("stem must be a plain filename without a path")
        path = directory / f"{stem}.json"
        # O_EXCL avoids accidentally replacing prior evidence or following a symlink.
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            json.dump(self.to_dict(), file, indent=2, ensure_ascii=False, allow_nan=False)
            file.write("\n")
        return str(path)

    def summary(self) -> str:
        return "\n".join([
            f"stop_reason : {self.stop_reason} (halted={self.halted})",
            f"final_model : {self.final_model or '(none)'}",
            f"tier path   : {' -> '.join(self.tier_stops) or '(none)'}",
            f"steps       : {len(self.steps)}",
            f"model calls : {self.total_calls} attempted; {self.successful_calls} returned",
            f"trajectory  : {self.trajectory() or '(none)'}",
            f"input units : {self.tokens_before} -> {self.tokens_after} ({self.token_count_kind})",
            f"gross saved : {self.tokens_saved}; auxiliary input+output: {self.auxiliary_tokens}",
            f"locked checks: {', '.join(self.locked_checks) or '(none; scores are heuristic)'}",
            "review      : " + ("NEEDS HUMAN REVIEW" if self.needs_human_review
                               else "passed the operator-supplied sufficient check"),
            f"settlement  : {self.settles_at or '(not provisional)'}",
            "", "ANSWER:", self.final_answer,
        ])
