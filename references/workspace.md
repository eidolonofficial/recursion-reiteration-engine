# Bounded archive workspaces — v0.3.0

## What changed

The v0.2 compressor could only shorten the scratchpad and retrieved context.
It still sent the entire cumulative candidate and all progress descriptions on
every call. The new, opt-in workspace protocol targets those larger fields.

`WorkspacePolicy` bounds the **complete visible system-plus-user input** for note,
answer and tier-planning calls. Its unit is the configured `TokenMeter` unit.
With no local tokenizer, the default remains an explicitly labelled UTF-8/4
estimate, not a model-token or billing measurement. Chat wrappers and generated
output require separate capacity reservations.

Full source strings remain in the run-scoped content-addressed archive, which is
included in the trace and, when configured, persisted in checkpoints. Workers get
exact offset-labelled excerpts, source lengths, hashes, current task and operator
pins. The full progress registry stays in the controller; a bounded view is sent
instead of repeating every obligation description. Required passages and declared
dependencies must fit intact or the call stops before invoking a backend.

Selection is deterministic recency/lexical selection, not learned semantic
retrieval. A worker's public note update acts as its ordinary working summary;
that new summary is not a replacement for the archived original. This release
adds no separate summarizer inference calls, vector database, trained memory
models, or offline knowledge-graph consolidation.

## Enable explicitly

```python
from headroom_recursion import RecurseConfig, Tier, WorkspacePolicy

config = RecurseConfig(
    ladder=(Tier("local-small"), Tier("local-large")),
    workspace=WorkspacePolicy(budget=4096),
    memory_scope="my-project/revision-1",
    max_total_calls=80,
)
```

For a manually driven session:

```sh
PYTHONPATH=src python -S -m headroom_recursion --manual \
  --workspace-tokens 4096 --max-calls 40 \
  --seed-answer-file incumbent.txt --scope project/revision-1 \
  "Review the next change while preserving established evidence."
```

A callable or command worker must understand `workspace-v1`. `workspace=None`
keeps the old wire protocol and existing workers. The old arithmetic `--demo`
worker does not speak this protocol and is rejected with an explicit message when
combined with `--workspace-tokens`; use `examples/workspace_demo.py` instead.
The archive/delta path is selected by `workspace`, independently of the optional
upstream Headroom bridge. Do not call this an upstream Headroom benchmark.

## Wire contract

A packet names the current source `base`, run `scope`, and a request-specific
`ticket`, plus exact excerpts of candidate, scratchpad, context, obligations,
and advisory checkpoint data. Full future ladder metadata is archived instead
of repeated; the planner still sees its entering tier and its bounded choice pool.

Note calls return ordinary visible notes. Planners select offered record IDs.
Answer calls return only a patch:

```json
{"workspace_patch":{"version":1,"scope":"packet scope","ticket":"packet ticket","base":"packet base","edits":[{"start":0,"end":5,"text":"new text"}]}}
```

Offsets are Unicode character offsets into the ORIGINAL candidate, end exclusive.
Edits must be ordered and disjoint. Replacements/deletions can touch only text
shown or retrieved during this call. Insertions must be on a shown boundary or
at EOF. Empty edits preserve the candidate. Unknown fields, duplicate JSON keys,
stale bases/tickets, cross-scope patches, oversized or truncated patches, and
edits to unseen content are refused. A plain replacement answer is not silently
interpreted as a patch. Unchanged text retains its exact bytes, including outer
whitespace. No implicit pretty-printing or mathematical normalization occurs in
this protocol.

Before editing omitted text, the worker may request an exact bounded range:

```json
{"memory_request":{"id":"an offered source id","start":5000,"end":5200}}
```

Only offered sources are readable. The archive entry is rehashed before reading.
Retrieved material becomes mandatory in the next packet, with optional excerpts
removed as necessary. Required material and already requested spans are never
silently truncated; a request that still cannot fit produces a context limit.
Every extra exchange counts toward the same completion cap and elapsed-time
budget. Retrieval is available to all three workspace roles, not just note calls.

## Explicit dependencies, not guessed dependencies

An operator may supply exact text in `required_passages`. Each must occur exactly
once. `dependencies=((dependent_text, prerequisite_text), ...)` adds exact
prerequisites whenever dependent text is selected, including transitive/cyclic
closure. A retained dependent cannot lose its registered prerequisite through a
patch. Missing or ambiguous required/dependency passages fail closed.

These declarations do not infer every necessary mathematical assumption. Automatic
selection can omit useful unregistered context. Mark essential statements and
assumptions, ask for exact references when needed, and retain reviewed full-state
checks. A digest proves content identity, not mathematical truth or authorship.

## Acceptance and verification

The controller reconstructs the full proposed candidate before the unchanged
validator, progress checks, best-incumbent selection and judge paths see it. All
registered checks execute, including ones whose descriptions were not selected
for the prompt. A patch grants no promotion authority. Rejected candidates retain
the prior answer/notes pair under the existing regression rules.

**Whole-candidate judges and seed judges remain full and exact**, including raw
notes, all obligations, and the existing verification framing. Workspace mode
rejects `compress_judge=True`. It does not pretend a small scoped review verifies
an entire proof. Large judges still require a backend with adequate capacity;
`max_input_tokens` also applies to those calls. No scoped-judge protocol is added.

Checkpoint policy fingerprints include workspace budgets, required passages,
dependencies and patch limits. Resume rechecks the incumbent and preserves consumed
budgets. Original v0.2 policy fingerprints remain unchanged when workspace is None.
Archive integrity is not authentication: a trusted local operator or compromised
process can rewrite data and recompute unkeyed hashes. There is no OS sandbox for
custom workers or an exhaustive security guarantee.

## Measured result and limits

A paired replay of the supplied 100-tier campaign produced identical full final
text, 100 accepted steps and 123 retained record checks in both arms. Full judge
request bytes matched exactly. The result is a **recorded-response transport test**:
the same old authored responses were used in each arm, not freshly generated by a
model given less context. Original mathematical experiments were not rerun.

| Measurement (Unicode characters) | Full-context arm | Workspace arm |
|---|---:|---:|
| All actual input, including retrieval/planning/judges | 46,897,048 | 14,750,161 |
| All actual output | 7,706,485 | 275,617 |
| Whole-candidate judge input (unchanged) | 9,323,435 | 9,323,435 |
| Completion exchanges | 501 | 683 |
| Extra archive exchanges | 0 | 182 |

Input decreased **68.5478%**. Input plus output decreased **72.4820%**, including
the extra retrieval traffic. Every workspace request fit the configured 10,000
character limit. That limit does not apply to full judges. CPU time in this replay
increased (roughly 1.9s versus 10.4s in the initial successful pass); this is not
an inference latency benchmark and the extra model calls could be costly.

The paired fixture explicitly canonicalizes the INITIAL JSON seed's key ordering
and whitespace in BOTH arms, checks that all parsed values are unchanged, and
records both original and canonical seed hashes. Later full answers match the
original recorded final answer byte-for-byte. This one-time fixture preparation
is not a workspace feature. This paired baseline differs slightly from the prior
46,324,941-character historical run because policy wording and seed formatting
are controlled anew. Compare the two arms above, not one arm to an older run.

An initial fixture adapter used character-level diffs that fragmented one update
into 37 needless edits and exhausted its retrieval cap. The controller refused
that update. The adapter was corrected to align exact JSON string tokens; the
successful paired run was repeated from the initial seed without relaxing the
20-read or 10,000-character caps. The engine still accepts generic text patches.

No trained-model quality, calibrated token savings, billing savings, mathematical
progress, upstream Headroom performance, or LightMem benchmark result is claimed.
Raw archive storage and complete judges still grow with accumulated evidence.
Small prompts may cost more with the protocol overhead; the mode is opt-in.
