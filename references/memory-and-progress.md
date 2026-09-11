# Memory and progress: implemented contracts

## Sources and what was actually borrowed

The user supplied Jiaquan Zhang et al., *Lightweight LLM Agent Memory with Small
Language Models*, arXiv:2604.07798v3 (22 April 2026). Its Sections 3.3-3.6 and
Appendices 8.1 and 10 separate routing/selection, writing, and offline consolidation.
Section 3.4 gives a 2K coarse candidate budget and at most K selected records;
Section 10.2 explicitly makes the Selector selection-only, without rewriting.

This implementation borrows those **control boundaries**, not the paper's reported
accuracy, model deployments, latency, training, vector retrieval, or global graph.
Here the coarse pool is deterministic, recent, run-scoped evidence. A model selects
exact record ids; it does not manufacture a verified memory. There is no embedding
service, background consolidation daemon, cross-user LTM, or de-identification
claim. Heavy per-call model summaries were deliberately avoided: local extraction
runs on the hot path and model checkpoint selection runs only at tier boundaries.

The Headroom adapter follows the public Python `compress`/`CompressConfig` contract
in `headroomlabs-ai/headroom`, inspected on 10 September 2026. Relevant explicit
options are user-message compression, protected system messages, `protect_recent=0`,
and `kompress_model="disabled"`. It is optional and is not the default compressor.
Its supported output is a single textual user message. Unexpected output and
unwired external CCR references fall back instead of claiming reversibility that
the controller cannot provide. The full upstream distribution could not be fetched
in this build environment; injected interface tests are not a live library test.

## Three different states, never interchangeable

1. **Original evidence:** exact generated notes, candidates and selected source
   blocks are stored in a run-local, content-addressed archive. Hashes are integrity
   checks, not proof or an authenticity mechanism.
2. **Prompt view:** ordinary prose may be deduplicated or omitted, and an explicitly
   enabled local Headroom adapter may shorten unprotected prose. These operations
   are lossy in the visible prompt. The full original remains recoverable.
3. **Committed progress:** an incumbent answer/notes pair and the obligations
   actually passed by operator-supplied checks. A model's `[KNOWN]`, `[NEW]`, or
   “verified” label never grants this authority.

A new note update does not erase older originals. A rejected revision is saved but
cannot become the next committed state. Current speculative notes and paired
incumbent notes are distinct fields in the trace.

## Compression boundary

Only the `scratchpad` and `context` template components are eligible. Problem,
answer, system instructions, supplied pins and check declarations bypass the
compressor completely. Exact user-marked `<verbatim>` blocks and fenced code are
never submitted to an external compressor. Conservative syntax/keyword detection
protects additional mathematical and constraint blocks. External prose rewrites
that introduce protected syntax or controller labels are rejected. This does not replace
explicit pinning of critical text.

When protected material exceeds a component budget, it is retained and overflow
is recorded. The independent full-input limit can stop the run. No compressed
empty/longer-than-original prompt counts as a successful optimization. Prompt
accounting includes archive markers and retrieval instructions.

A note completion can request:

```json
{"memory_request":{"id":"an offered SHA-256 reference","start":0,"end":100}}
```

The request is accepted only for a reference offered in that note call, with
integer, end-exclusive Unicode character offsets within the source and read-size
cap. Unknown references, extra control fields, invalid offsets and excessive
rounds are errors. Only note operations use this reserved protocol; task answers
and judge outputs are never reinterpreted as retrieval commands. Retrieved bytes
are appended as untrusted reference text and are not recompressed.

## Progress enforcement

Let `L_t` be the set of locked check names and `S(y)` the exact, nonprovisional,
confidence-one checks passed by candidate `y`. A proposed candidate must satisfy:

`L_t union required_checks subset S(y)`.

A committed candidate also requires a valid common-judge score at least as high
as the incumbent's score, or a passing sufficient validator. On commitment:

`L_(t+1) = L_t union S(y)`.

Both answer and paired notes roll back on rejection. A check throwing an error
cannot satisfy a locked requirement. Statistical/provisional results do not enter
`S(y)`. A partial predicate does not imply correctness outside its declared scope.
The model cannot alter check definitions, the ladder, execution settings, or caps.

The common judge avoids comparing scores from changing model identities/settings.
It does **not** make subjective scores calibrated, independent, reproducible, or
monotonic in actual mathematical quality. For that, supply meaningful checked
obligations and an adequate sufficient verifier. More proof-like prose is not a
substitute for mechanical evidence.

## Checkpoint and failure behavior

Checkpoint files bind the exact task hash, logical scope and execution/verification
policy hash. They contain raw state and cumulative accounting, not a trusted saved
judge score. On resume, the incumbent is rechecked and rescored before refinement.
Callbacks are identified by the operator's explicit `verification_id`; the runtime
cannot prove two arbitrary Python functions have the same semantics.

Single-writer checkpoints use private temporary files, fsync and atomic replacement.
Attempts are reserved before external execution, favoring conservative overcounting
if a process crashes between reservation and launch. Completed-step cursors advance
only after evaluation and commitment/rejection. An interrupted step may be replayed
from its incumbent; its earlier attempts still count. A failed tier advances to the
next approved tier; resume does not silently revive an exhausted schedule.

Digests do not protect against an attacker with file-write access and the ability
to recompute them. Scope strings are not authentication. The Python process and
supplied callbacks, subprocesses, filesystem and optional third-party installation
remain trusted. There is no claim of multi-tenant isolation or an OS sandbox.

## Uncertainties resolved by implementation choices

| Question | Decision |
| --- | --- |
| Can a model pre-seed progress by claiming completion? | It may select source ids and suggest a check; it has no verification authority. |
| Does `use_headroom` merely reach a callback? | No. The controller constructs a compressed prompt before the worker call and disables downstream double compression. |
| Is the actual scratchpad shortened? | Yes, including fresh notes between latent updates. The exact original is separately archived. |
| What happens when a formula cannot fit? | Preserve it, record overflow, and stop at an explicit full-input ceiling rather than truncate it. |
| Can a new model erase prior progress? | Committed checks and the scored incumbent are enforced outside the model. Unchecked semantic quality remains uncertain. |
| Are compression calls free? | Local extraction makes no model calls. Planning, grading and replays count against the shared cap; auxiliary input/output is reported. |
| Can a resume manufacture a larger budget? | The saved policy must match; consumed attempts and elapsed time carry forward. |
| Does this implement all of LightMem or upstream Headroom? | No. It implements the stated bounded subset and documents the differences. |
