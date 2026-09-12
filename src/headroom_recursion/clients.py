"""Local completion transports. No SDK, key, HTTP endpoint, or model download.

A local program or callback is trusted code, not a network sandbox. Its own
behavior is outside this library's control. No backend is selected implicitly.
"""
from __future__ import annotations

import json
import math
import subprocess
import sys
from dataclasses import dataclass
from typing import Callable, Protocol, TextIO, runtime_checkable


@dataclass(frozen=True)
class CallResult:
    text: str
    tokens_before: int = 0
    tokens_after: int = 0
    stop_reason: str = ""
    cost_usd: float = 0.0
    usage: dict[str, int] | None = None  # native token counts; None means unknown

    def __post_init__(self) -> None:
        if self.usage is not None and (type(self.usage) is not dict or any(type(k) is not str or type(v) is not int or v < 0 for k,v in self.usage.items())):
            raise ValueError("usage must contain nonnegative native token counts")
        if not isinstance(self.text, str) or not isinstance(self.stop_reason, str):
            raise TypeError("text and stop_reason must be strings")
        for name in ("tokens_before", "tokens_after"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be a nonnegative integer")
        if type(self.cost_usd) not in (int, float) or not math.isfinite(self.cost_usd) or self.cost_usd < 0:
            raise ValueError("cost_usd must be finite and nonnegative")


@runtime_checkable
class CompletionClient(Protocol):
    def complete(self, *, model: str, system: str, user: str,
                 max_tokens: int = 2048, temperature: float = 0.7,
                 use_headroom: bool = False, response_schema: dict | None = None) -> CallResult: ...


class TransportError(RuntimeError):
    """A local worker failed; error output must never become a candidate answer."""


class CallableClient:
    """Wrap a trusted in-process generator that returns str or CallResult.

    The callback receives the complete keyword request, including the opaque model
    identifier. Load weights yourself and handle the model's native template there.
    No universal tokenizer or capability ordering is assumed.
    """
    def __init__(self, complete: Callable[..., str | CallResult]):
        if not callable(complete):
            raise TypeError("complete must be callable")
        self._complete = complete

    def complete(self, *, model: str, system: str, user: str,
                 max_tokens: int = 2048, temperature: float = 0.7,
                 use_headroom: bool = False) -> CallResult:
        result = self._complete(model=model, system=system, user=user,
                                max_tokens=max_tokens, temperature=temperature,
                                use_headroom=use_headroom)
        if isinstance(result, str):
            return CallResult(result)
        if not isinstance(result, CallResult):
            raise TypeError("local callback must return str or CallResult")
        return result


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def strict_json(text: str):
    def invalid(value):
        raise ValueError(f"non-finite JSON constant: {value}")
    return json.loads(text, object_pairs_hook=_object, parse_constant=invalid)


class CommandClient:
    """One explicit local argv, one JSON request on stdin, one JSON response.

    The executable and arguments are operator-controlled and never interpolated
    from prompts. shell=False is mandatory. A timeout kills the direct child;
    it is not a sandbox or a guarantee that descendant processes are stopped.
    Output is captured before a size check; use only trusted local workers.
    """
    def __init__(self, argv: list[str] | tuple[str, ...], *, timeout_s: float = 120,
                 max_output_bytes: int = 1_000_000):
        if not isinstance(argv, (list, tuple)) or not argv or any(not isinstance(a, str) or not a or "\0" in a for a in argv):
            raise ValueError("argv must be a nonempty list of literal strings")
        if type(timeout_s) not in (float, int) or not math.isfinite(timeout_s) or timeout_s <= 0:
            raise ValueError("timeout_s must be finite and positive")
        if type(max_output_bytes) is not int or max_output_bytes < 1:
            raise ValueError("max_output_bytes must be a positive integer")
        self.argv = tuple(argv)
        self.timeout_s = timeout_s
        self.max_output_bytes = max_output_bytes

    def complete(self, *, model: str, system: str, user: str,
                 max_tokens: int = 2048, temperature: float = 0.7,
                 use_headroom: bool = False) -> CallResult:
        request = dict(protocol_version=1, model=model, system=system, user=user,
                       max_tokens=max_tokens, temperature=temperature,
                       use_headroom=use_headroom)
        try:
            out = subprocess.run(self.argv, input=json.dumps(request, allow_nan=False),
                                 capture_output=True, text=True, encoding="utf-8",
                                 errors="strict", timeout=self.timeout_s, check=False,
                                 shell=False)
        except (OSError, UnicodeError, subprocess.TimeoutExpired) as exc:
            raise TransportError(f"local worker did not complete: {type(exc).__name__}") from exc
        if out.returncode:
            # Do not include arbitrary stderr, which may contain local secrets.
            raise TransportError(f"local worker exited with status {out.returncode}")
        if len(out.stdout.encode("utf-8")) > self.max_output_bytes:
            raise TransportError("local worker response exceeded the output limit")
        try:
            value = strict_json(out.stdout)
        except (ValueError, TypeError) as exc:
            raise TransportError("local worker must return one strict JSON object") from exc
        if not isinstance(value, dict) or value.get("protocol_version") != 1 or type(value.get("protocol_version")) is not int:
            raise TransportError("unsupported or absent worker protocol_version")
        if value.get("ok") is not True:
            raise TransportError("local worker reported an error or refusal")
        if "text" not in value:
            raise TransportError("worker response has no text")
        try:
            return CallResult(text=value["text"], tokens_before=value.get("tokens_before", 0),
                              tokens_after=value.get("tokens_after", 0),
                              stop_reason=value.get("stop_reason", ""))
        except (ValueError, TypeError) as exc:
            raise TransportError("worker response has invalid fields") from exc


class ManualClient:
    """Use any model application by manually exchanging prompts and completions.

    Prompts go to stderr by default, leaving stdout clean for the final result.
    This mode has no automated inference and does not ask for hidden reasoning:
    supply the model's ordinary visible working notes, answer, or judge response.
    """
    def __init__(self, *, reader: TextIO | None = None, writer: TextIO | None = None):
        self.reader = reader or sys.stdin
        self.writer = writer or sys.stderr

    def complete(self, *, model: str, system: str, user: str,
                 max_tokens: int = 2048, temperature: float = 0.7,
                 use_headroom: bool = False) -> CallResult:
        print(f"\nMODEL: {model}\nSYSTEM:\n{system}\n\nINPUT:\n{user}\n\n"
              "Paste the visible response. Finish with a line containing only END.",
              file=self.writer, flush=True)
        lines = []
        while True:
            line = self.reader.readline()
            if line == "":
                raise EOFError("manual completion ended before END")
            if line.rstrip("\r\n") == "END":
                break
            lines.append(line)
        # Manual use cannot enforce token or temperature settings.
        return CallResult("".join(lines).rstrip("\r\n"))
