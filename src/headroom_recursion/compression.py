"""Local, reversible prompt views. Raw notes are evidence; compressed views are not.

The default compressor is extractive and uses no model or network. It retains
whole protected blocks, selects other blocks, and archives the exact source.
The optional Headroom adapter touches only *unprotected prose*. Neither path
claims semantic equivalence for text that was omitted or rewritten.
"""
from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from typing import Callable, Protocol


class MemoryLimitError(RuntimeError):
    """Refuse to silently evict evidence when the local archive is full."""


class ContextLimitError(RuntimeError):
    """Protected input cannot fit the operator's configured prompt limit."""


class TokenMeter:
    """Count visible input text, not a provider's hidden chat-template overhead.

    Supply a local ``counter(text, model) -> int`` for tokenizer-backed counts.
    The fallback is a labelled UTF-8-bytes/4 estimate, never a billing count.
    """
    def __init__(self, counter: Callable[[str, str], int] | None = None,
                 label: str | None = None):
        if counter is not None and not callable(counter):
            raise TypeError("counter must be callable")
        self.counter = counter
        self.label = label or ("local-tokenizer/text-only" if counter else "estimated-utf8-bytes/4")

    def count(self, text: str, model: str) -> int:
        if not isinstance(text, str):
            raise TypeError("token input must be text")
        value = self.counter(text, model) if self.counter else (len(text.encode("utf-8")) + 3) // 4
        if type(value) is not int or value < 0 or (text and value == 0):
            raise ValueError("token counter must return a nonnegative integer, positive for nonempty text")
        return value

    def prompt(self, system: str, user: str, model: str) -> int:
        return self.count(system, model) + self.count(user, model)


class MemoryStore:
    """Run-scoped content-addressed originals. Digests detect corruption, not authorship.

    This store is not a cross-user database. A new run gets a new instance; resume
    explicitly imports the archive only after problem/scope/policy checks.
    """
    def __init__(self, max_bytes: int = 16_000_000):
        if type(max_bytes) is not int or max_bytes < 1:
            raise ValueError("max_bytes must be positive")
        self.max_bytes = max_bytes
        self.records: dict[str, str] = {}
        self.bytes_used = 0

    @staticmethod
    def key(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def put(self, text: str) -> str:
        if not isinstance(text, str):
            raise TypeError("memory must be text")
        key = self.key(text)
        if key not in self.records:
            size = len(text.encode("utf-8"))
            if self.bytes_used + size > self.max_bytes:
                raise MemoryLimitError("archive capacity reached; no original was evicted")
            self.records[key] = text
            self.bytes_used += size
        return key

    def read(self, key: str, start: int = 0, end: int | None = None,
             *, max_chars: int = 12000) -> str:
        if not isinstance(key, str) or key not in self.records:
            raise ValueError("memory reference is not in this run")
        text = self.records[key]
        end = len(text) if end is None else end
        if (type(start) is not int or type(end) is not int or
                not 0 <= start < end <= len(text) or end - start > max_chars):
            raise ValueError("invalid or oversized memory range")
        return text[start:end]

    def restore(self, records: dict[str, str]) -> None:
        if not isinstance(records, dict):
            raise TypeError("archive must be an object")
        # Validate transactionally before replacing anything.
        temp = MemoryStore(self.max_bytes)
        for key, text in records.items():
            if not isinstance(text, str) or self.key(text) != key:
                raise ValueError("archive digest mismatch")
            temp.put(text)
        self.records, self.bytes_used = temp.records, temp.bytes_used


@dataclass(frozen=True)
class Block:
    text: str
    protected: bool


# Conservative syntax recognition is a convenience, NOT semantic verification.
# Explicit <verbatim> blocks and operator pins are the dependable boundary.
_MATH = re.compile(r"[0-9=<>^_$\\{}+*/|~\-]|[\u2200-\u22ffΑ-ωℂℕℚℝℤ]|\b(?:theorems?|lemmas?|proofs?|assum(?:e|ption)|constraint|"
                   r"invariant|counterexample|failed|frontier|not|never|unless|must|without|cannot|only|iff|forall|exists|let|suppose|definition|define|conjecture)\b", re.I)


def blocks(text: str) -> list[Block]:
    """Split on blank lines outside fences; preserve each block's bytes exactly."""
    output: list[Block] = []
    pending: list[str] = []
    fence: str | None = None
    verbatim = False
    protect_group = False
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        match = re.match(r"^\s*(`{3,}|~{3,})", line)
        if match:
            marker = match.group(1)
            protect_group = True
            if fence is None:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence):
                fence = None
        if "<verbatim>" in line:
            verbatim = True
            protect_group = True
        pending.append(line)
        if "</verbatim>" in line:
            verbatim = False
        if not stripped and fence is None and not verbatim:
            value = "".join(pending)
            output.append(Block(value, protect_group or bool(_MATH.search(value))))
            pending, protect_group = [], False
    if pending:
        value = "".join(pending)
        output.append(Block(value, protect_group or fence is not None or verbatim or bool(_MATH.search(value))))
    # Long ordinary prose can be selected at sentence/line boundaries. Never
    # split a protected paragraph (including a negation or mathematical syntax).
    fine = []
    for block in output:
        if not block.protected and len(block.text) > 512:
            pieces = re.split(r"(?<=[.!?])(?=\s+\S)|(?<=\n)(?=\S)", block.text)
            fine.extend(Block(piece, False) for piece in pieces if piece)
        else:
            fine.append(block)
    return fine


class ProseCompressor(Protocol):
    def compress(self, text: str, *, model: str) -> str: ...


class HeadroomCompressor:
    """Explicit adapter to an already-installed Headroom Python library.

    No proxy/server, model key, inference SDK, installation or download is started
    here. ML compression is disabled in its configuration. Third-party execution
    still belongs in an operator-controlled offline environment; this class is
    not an OS sandbox. Missing/incompatible installations fail explicitly;
    malformed results fall back visibly inside ContextCompressor.
    """
    def __init__(self, *, compress_fn=None, config_factory=None):
        if compress_fn is None:
            from headroom import compress as compress_fn, CompressConfig as config_factory
        if not callable(compress_fn) or not callable(config_factory):
            raise TypeError("Headroom adapter needs compress and CompressConfig")
        self._compress = compress_fn
        # Do not silently remove unsupported configuration flags: fail explicitly.
        self._config = config_factory(compress_user_messages=True,
                                      compress_system_messages=False,
                                      protect_recent=0,
                                      protect_analysis_context=True,
                                      kompress_model="disabled",
                                      min_tokens_to_compress=1,
                                      target_ratio=0.5)

    def compress(self, text: str, *, model: str) -> str:
        result = self._compress([{"role": "user", "content": text}],
                                model=model, config=self._config)
        # Deliberately synchronous. No abandoned threads or nested event loops.
        import inspect
        if inspect.isawaitable(result):
            if inspect.iscoroutine(result):
                result.close()
            raise TypeError("an asynchronous compressor needs an explicit synchronous local adapter")
        messages = getattr(result, "messages", result)
        if (not isinstance(messages, list) or len(messages) != 1 or
                not isinstance(messages[0], dict) or messages[0].get("role") != "user" or
                not isinstance(messages[0].get("content"), str) or not messages[0]["content"].strip()):
            raise ValueError("Headroom returned an invalid message shape")
        content = messages[0]["content"]
        # Its private CCR store is not our completion protocol. Fall back rather
        # than advertise an unavailable tool or a reference the model cannot redeem.
        if re.search(r"headroom_retrieve|<<ccr:|\[CCR|retrieve:\s*[a-f0-9]{6}", content, re.I):
            raise ValueError("Headroom output contains an unsupported external retrieval reference")
        return content


@dataclass(frozen=True)
class CompressedView:
    text: str
    original_ref: str
    tokens_before: int
    tokens_after: int
    method: str
    omitted: bool = False
    overflow: bool = False
    error: str = ""


class ContextCompressor:
    """Keep protected blocks exact; compress/retrieve other prose under a budget.

    Budgets are soft for protected material: overflow is reported, never resolved
    by deleting mathematical evidence. ``max_input_tokens`` in the controller is
    the separate hard ceiling and stops the run when protected input cannot fit.
    """
    def __init__(self, store: MemoryStore, meter: TokenMeter, *, min_tokens: int = 256,
                 prose: ProseCompressor | None = None):
        self.store, self.meter, self.min_tokens, self.prose = store, meter, min_tokens, prose
        self._cache: dict[tuple, CompressedView] = {}

    def view(self, text: str, *, model: str, budget: int, query: str = "") -> CompressedView:
        ref = self.store.put(text)
        before = self.meter.count(text, model)
        cache_key = (ref, model, budget, query)
        if cache_key in self._cache:
            return self._cache[cache_key]
        if before < self.min_tokens or before <= budget:
            return CompressedView(text, ref, before, before, "identity")
        source = blocks(text)
        # Exact duplicates may be removed only from ordinary prose. Repetition
        # inside proofs, constraints and code remains byte-for-byte intact.
        seen: set[str] = set()
        unique: list[tuple[int, Block]] = []
        for index, block in enumerate(source):
            if block.protected or block.text not in seen:
                unique.append((index, block))
                seen.add(block.text)
        marker = (f"\n[ARCHIVED SOURCE {ref}; {len(text)} characters. "
                  "Omitted prose is retrievable by memory_request with start/end offsets.]\n")
        selected = {index for index, block in unique if block.protected}
        words = set(re.findall(r"\w+", query.casefold()))
        prose = [(i, b) for i, b in unique if not b.protected]
        ranked = sorted(prose, key=lambda pair: (
            -len(words & set(re.findall(r"\w+", pair[1].text.casefold()))), -pair[0]))
        replacements: dict[int, str] = {}
        error = ""
        if self.prose is not None:
            # The external compressor sees NO protected block, problem, answer,
            # instruction, or checker record. It cannot rewrite those bytes.
            for i, block in prose:
                try:
                    candidate = self.prose.compress(block.text, model=model)
                    if not isinstance(candidate, str) or not candidate.strip():
                        raise ValueError("empty compressed prose")
                    # Unprotected input cannot contain these constructs. Do not
                    # let a prose rewrite manufacture a mathematical statement,
                    # authority label, or retrieval capability absent from it.
                    if (_MATH.search(candidate) or re.search(
                            r"ARCHIVED SOURCE|OPERATOR EXACT PINS|OPERATOR PROGRESS|"
                            r"CHECKER FEEDBACK|memory_request|headroom_retrieve", candidate, re.I)):
                        raise ValueError("compressed prose introduced protected syntax or control markers")
                    if self.meter.count(candidate, model) < self.meter.count(block.text, model):
                        replacements[i] = candidate + ("\n\n" if not candidate.endswith("\n\n") else "")
                except Exception as exc:
                    error = f"prose compressor fallback: {type(exc).__name__}"
        def render(indices: set[int]) -> str:
            return "".join(replacements.get(i, b.text) for i, b in unique if i in indices) + marker
        for index, block in ranked:
            candidate = selected | {index}
            if self.meter.count(render(candidate), model) <= budget:
                selected = candidate
        result = render(selected)
        after = self.meter.count(result, model)
        if not selected or after >= before:
            # An opaque archive pointer alone is not useful context. Never count
            # an inflated or empty rewrite as a token-saving success.
            view = CompressedView(text, ref, before, before, "identity", overflow=before > budget, error=error)
        else:
            method = "headroom+extractive" if any(i in replacements for i in selected) else "extractive"
            view = CompressedView(result, ref, before, after, method,
                                  omitted=True, overflow=after > budget, error=error)
        # Bounded cache; the originals are independent and remain retrievable.
        if len(self._cache) >= 256:
            self._cache.pop(next(iter(self._cache)))
        self._cache[cache_key] = view
        return view
