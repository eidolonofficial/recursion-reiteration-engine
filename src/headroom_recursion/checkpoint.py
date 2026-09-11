"""Strict, scoped checkpoint envelopes. Integrity is not authentication.

Resume re-runs supplied checks and re-scores the incumbent. A saved score, label,
or model claim never establishes truth. Load checkpoints only from trusted local
storage: someone who can rewrite a file can also recompute an ordinary digest.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from .clients import strict_json


def digest(value) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def policy(cfg) -> dict:
    from dataclasses import asdict
    return {
        **({"workspace": asdict(cfg.workspace)} if cfg.workspace is not None else {}),
        "n": cfg.n, "T": cfg.T,
        "ladder": [[t.model, t.max_steps, t.max_tokens, t.step_timeout_s] for t in cfg.ladder],
        "judge_model": cfg.judge_model or (cfg.ladder[-1].model if cfg.enforce_progress else None),
        "judge_votes": cfg.judge_votes, "halt_threshold": cfg.halt_threshold,
        "judge_can_halt": cfg.judge_can_halt,
        "max_total_calls": cfg.max_total_calls, "max_wall_seconds": cfg.max_wall_seconds,
        "max_input_tokens": cfg.max_input_tokens,
        "enforce_progress": cfg.enforce_progress, "preseed_ladder": cfg.preseed_ladder,
        "verification_id": cfg.verification_id,
        "checks": [[c.name, c.statement, c.required] for c in cfg.progress_checks],
        "validator_present": cfg.validator is not None, "oracle_sufficient": cfg.oracle_sufficient,
        "oracle_note": cfg.oracle_note, "oracle_rung": cfg.oracle_rung,
        "use_headroom": cfg.use_headroom, "compress_judge": cfg.compress_judge,
        "compression_backend": cfg.compression_backend,
        "scratchpad_tokens": cfg.scratchpad_tokens, "context_tokens": cfg.context_tokens,
        "memory_max_bytes": cfg.memory_max_bytes, "memory_max_rounds": cfg.memory_max_rounds,
        "memory_read_chars": cfg.memory_read_chars, "compression_min_tokens": cfg.compression_min_tokens,
        "progress_tokens": cfg.progress_tokens, "progress_k": cfg.progress_k,
        "temperature": cfg.temperature, "claim_audit": cfg.claim_audit,
        "progress_model": cfg.progress_model, "pinned_notes": list(cfg.pinned_notes),
        "token_counter_label": cfg.token_counter_label,
        "custom_compressor": cfg.prose_compressor is not None,
        "custom_counter": cfg.token_counter is not None,
        "retrieval_k": cfg.retrieval_k, "retrieval_query_chars": cfg.retrieval_query_chars,
        "retrieval_max_chars": cfg.retrieval_max_chars,
    }


def save(path: str | Path, payload: dict) -> None:
    path = Path(path)
    if path.is_symlink() or any(p.is_symlink() for p in path.parents):
        raise ValueError("checkpoint destination must not traverse symlinks")
    path.parent.mkdir(parents=True, exist_ok=True)
    envelope = {"schema_version": 1, "payload": payload, "sha256": digest(payload)}
    # Write privately, fsync and replace only the explicitly named checkpoint.
    # This is a single-writer protocol, not a concurrent database.
    fd, tmp = tempfile.mkstemp(prefix=".checkpoint-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(envelope, file, ensure_ascii=False, sort_keys=True, allow_nan=False)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def load(path: str | Path, *, max_bytes: int = 64_000_000) -> dict:
    with Path(path).open("rb") as file:
        data = file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError("checkpoint exceeds the load limit")
    obj = strict_json(data.decode("utf-8"))
    if (not isinstance(obj, dict) or set(obj) != {"schema_version", "payload", "sha256"} or
            type(obj["schema_version"]) is not int or obj["schema_version"] != 1 or
            not isinstance(obj["payload"], dict) or obj["sha256"] != digest(obj["payload"])):
        raise ValueError("invalid checkpoint envelope or digest")
    return obj["payload"]


def validate(payload: dict, cfg, problem: str) -> None:
    required = {"scope", "problem_hash", "policy_hash", "attempted_calls", "successful_calls",
                "wall_seconds", "next_tier", "completed_steps", "incumbent", "current",
                "locked_checks", "archive", "input_before", "input_after", "auxiliary_tokens"}
    if not isinstance(payload, dict) or set(payload) != required:
        raise ValueError("unexpected checkpoint fields")
    if payload["scope"] != cfg.memory_scope or payload["problem_hash"] != digest(problem):
        raise ValueError("checkpoint scope or problem mismatch")
    if payload["policy_hash"] != digest(policy(cfg)):
        raise ValueError("checkpoint execution/verification policy mismatch")
    for name in ("attempted_calls", "successful_calls", "next_tier", "input_before", "input_after", "auxiliary_tokens"):
        if type(payload[name]) is not int or payload[name] < 0:
            raise ValueError(f"invalid checkpoint counter: {name}")
    if payload["successful_calls"] > payload["attempted_calls"] or payload["next_tier"] > len(cfg.ladder):
        raise ValueError("inconsistent checkpoint counters")
    if cfg.max_total_calls is not None and payload["attempted_calls"] > cfg.max_total_calls:
        raise ValueError("checkpoint already exceeds its call cap")
    import math
    wall = payload["wall_seconds"]
    if type(wall) not in (int, float) or not math.isfinite(wall) or wall < 0:
        raise ValueError("invalid checkpoint elapsed time")
    steps = payload["completed_steps"]
    if (not isinstance(steps, list) or len(steps) != len(cfg.ladder) or
            any(type(n) is not int or n < 0 or n > cfg.steps_for(t) for n, t in zip(steps, cfg.ladder))):
        raise ValueError("invalid checkpoint tier cursor")
    for name in ("incumbent", "current"):
        state = payload[name]
        if (not isinstance(state, dict) or set(state) != {"answer", "scratchpad", "model"} or
                any(not isinstance(value, str) for value in state.values())):
            raise ValueError("invalid checkpoint answer/notes pair")
        if state["model"] and state["model"] not in {t.model for t in cfg.ladder} | {"seed"}:
            raise ValueError("checkpoint model is outside the approved ladder")
    locked = payload["locked_checks"]
    if (not isinstance(locked, list) or any(not isinstance(v, str) for v in locked) or
            len(locked) != len(set(locked)) or not set(locked) <= {c.name for c in cfg.progress_checks}):
        raise ValueError("invalid locked-check list")
    if not isinstance(payload["archive"], dict):
        raise ValueError("invalid checkpoint archive")
