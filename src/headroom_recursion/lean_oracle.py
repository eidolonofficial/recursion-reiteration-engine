"""Opt-in Lean checks derived from the source's gate/pinned-statement design.

SECURITY BOUNDARY: Lean elaboration and imported tactics execute code. These
helpers are not an operating-system sandbox and stdout is not an authenticated
proof certificate. Use only reviewed proof text in a trusted, isolated toolchain.
No execution is enabled until the operator passes trusted_execution=True.
The pinned project is preserved separately; this module does not install it.
"""
from __future__ import annotations

import hashlib
import math
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from .config import Verdict

STANDARD_AXIOMS = frozenset({"propext", "Classical.choice", "Quot.sound"})
_BLOCK_RE = re.compile(r"```lean[^\S\n]*\n(.*?)```", re.DOTALL)
_TARGET_RE = re.compile(r"^--\s*LEAN-ORACLE-TARGET:\s*([A-Za-z_][A-Za-z0-9_.']*)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class Skeleton:
    text: str
    target: str
    sorry_index: int


@dataclass
class LeanOracle:
    validator: Callable[[str], bool | Verdict]
    feedback: Callable[[str], str]
    note: str
    sufficient: bool
    rung: int = 1


def extract_lean_blocks(answer: str) -> list[str]:
    return [match.group(1).strip() for match in _BLOCK_RE.finditer(answer)
            if match.group(1).strip()]


def load_skeleton(path: str | Path) -> Skeleton:
    text = Path(path).read_text(encoding="utf-8")
    positions = [i for i, line in enumerate(text.splitlines()) if line.strip() == "sorry"]
    targets = _TARGET_RE.findall(text)
    if len(positions) != 1 or len(targets) != 1:
        raise ValueError("skeleton needs exactly one sorry line and one LEAN-ORACLE-TARGET marker")
    return Skeleton(text, targets[0], positions[0])


def splice(skeleton: Skeleton, proof: str) -> str:
    import textwrap
    lines = skeleton.text.splitlines()
    holder = lines[skeleton.sorry_index]
    indent = holder[:len(holder) - len(holder.lstrip())]
    body = textwrap.dedent(proof).strip().splitlines()
    if not body:
        raise ValueError("proof must be nonempty")
    replacement = [indent + "("] + [indent + "  " + line for line in body] + [indent + ")"]
    lines[skeleton.sorry_index:skeleton.sorry_index + 1] = replacement
    return "\n".join(lines) + "\n"


def audit_axioms(output: str, target: str) -> tuple[bool, str]:
    """Reject missing, duplicate, conflicting, or non-allowlisted audit output.

    This parser does not authenticate where stdout came from. It is suitable only
    inside the trusted execution boundary stated above.
    """
    seen = []
    for line in output.splitlines():
        empty = re.fullmatch(r"'([^']+)' does not depend on any axioms", line.strip())
        listed = re.fullmatch(r"'([^']+)' depends on axioms: \[([^\]]*)\]", line.strip())
        if empty and empty.group(1) == target:
            seen.append(set())
        if listed and listed.group(1) == target:
            seen.append({name.strip() for name in listed.group(2).split(",") if name.strip()})
    if len(seen) != 1:
        return False, "expected exactly one audit record for the pinned declaration"
    unexpected = seen[0] - STANDARD_AXIOMS
    if unexpected:
        return False, "proof used axioms outside the configured allowlist"
    return True, "configured axiom audit passed in the trusted toolchain"


def _execute(code: str, project_dir: str | Path | None, timeout_s: float, runner) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory(prefix="local-lean-") as temp:
        path = Path(temp) / "Candidate.lean"
        path.write_text(code, encoding="utf-8")
        argv = ["lake", "env", "lean", str(path)] if project_dir else ["lean", str(path)]
        out = runner(argv, capture_output=True, text=True, encoding="utf-8",
                     timeout=timeout_s, cwd=str(project_dir) if project_dir else None,
                     shell=False, check=False)
        return out.returncode == 0, (out.stdout or "") + (out.stderr or "")


def _factory(*, skeleton: Skeleton | None, project_dir, timeout_s,
             trusted_execution: bool, runner) -> LeanOracle:
    if trusted_execution is not True:
        raise ValueError("review and isolate the Lean execution environment before enabling trusted_execution")
    if type(timeout_s) not in (int, float) or not math.isfinite(timeout_s) or timeout_s <= 0:
        raise ValueError("timeout_s must be finite and positive")
    runner = runner or subprocess.run
    memo = {}

    def check(answer: str):
        key = hashlib.sha256(answer.encode("utf-8")).hexdigest()
        if key in memo:
            return memo[key]
        blocks = extract_lean_blocks(answer)
        if not blocks:
            raise ValueError("no Lean block was supplied; nothing checked")
        if skeleton is not None and len(blocks) != 1:
            return Verdict(False), "provide exactly one proof block for the pinned statement"
        # This is a conservative error screen, not a security boundary.
        forbidden = r"\b(sorry|admit|sorryAx|axiom|unsafe|native_decide|implemented_by|extern|initialize)\b"
        if any(re.search(forbidden, block) for block in blocks):
            result = Verdict(False), "proof contains a disallowed trust construct"
        else:
            sources = ([splice(skeleton, blocks[0]) + f"\n#print axioms {skeleton.target}\n"]
                       if skeleton else blocks)
            result = Verdict(True, note="typecheck only; statement correspondence was not checked"), ""
            for source in sources:
                ok, output = _execute(source, project_dir, timeout_s, runner)
                if not ok or "sorry" in output:
                    result = Verdict(False), output[-4000:] or "Lean check failed"
                    break
                if skeleton is not None:
                    passed, note = audit_axioms(output, skeleton.target)
                    result = Verdict(passed, note=note), "" if passed else note
                    if not passed:
                        break
        if len(memo) >= 32:
            memo.pop(next(iter(memo)))
        memo[key] = result
        return result

    def feedback(answer: str) -> str:
        try:
            return check(answer)[1]
        except Exception as exc:
            return f"Lean unavailable: {type(exc).__name__}"

    return LeanOracle(lambda answer: check(answer)[0], feedback,
                      "Trusted pinned-statement check" if skeleton else "Lean typecheck gate; passing is not proof of the requested claim",
                      sufficient=skeleton is not None)


def make_gate_oracle(*, project_dir: str | Path | None = None,
                     timeout_s: float = 300, trusted_execution: bool = False, runner=None) -> LeanOracle:
    return _factory(skeleton=None, project_dir=project_dir, timeout_s=timeout_s,
                    trusted_execution=trusted_execution, runner=runner)


def make_decider_oracle(skeleton_path: str | Path, *, project_dir: str | Path | None = None,
                        timeout_s: float = 300, trusted_execution: bool = False, runner=None) -> LeanOracle:
    return _factory(skeleton=load_skeleton(skeleton_path), project_dir=project_dir,
                    timeout_s=timeout_s, trusted_execution=trusted_execution, runner=runner)
