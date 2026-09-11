# Worker actions

`RecurseConfig.simple(...)` or `--simple` selects one proposal per step, with
zero preliminary note calls by default. It uses the existing workspace, archive,
progress checks and completion budget. No extra inference model or service is added.
Legacy workspace formats remain available. Rejection bounds apply to all profiles.

The worker returns one strict JSON object. Its current role determines the allowed
terminal action; reads/searches are explicit bounded exchanges, never notes.

```json
{"action":"propose","block":"offered block handle","value":{"selected":["A"]}}
```

Other forms are `{"action":"note","text":"..."}` in a note role,
`{"action":"read","source":"s0","page":0}`, and
`{"action":"find","source":"s0","text":"literal","start":0}`.
Unknown fields, combined actions, duplicate keys, wrong types, unsupported roles,
Markdown-wrapped replies and incomplete JSON are rejected, not guessed or repaired.

Python maps an offered block to its exact source span and original request ticket.
The worker does not calculate edit offsets. A JSON value may replace only a fully
visible candidate; partial source edits require text and leave unedited bytes exact.
Archive pages/searches retain existing source authorization and dependency closure.
A block from another request is not a current edit capability.

`validator`, `ProgressCheck`, and `feedback` remain reviewed host callbacks.
They calculate arithmetic, enforce constraints and report evidence. A model's
claimed total is not authoritative. `examples/project_selection.py` demonstrates
this on a fixed 12-project task; its finite exhaustive oracle is host-only.

Checker feedback is a separate host-owned field, survives tier handoff, and is
not mixed into model-authored notes or success claims. Command-like note envelopes
are rejected even when malformed; ordinary mathematical prose remains unchanged.
Checker exceptions are unavailable evidence, never a reason to substitute model
approval for the missing check.

`max_repeated_rejections=2` stops after the same rejected candidate recurs twice
without a changed accepted candidate. Comparison ignores framing whitespace, not
mathematical differences or domain-specific list order. Protocol failures are
counted by error category so fresh request handles cannot hide repeated invalid
formatting. The last 64 distinct failure identities are retained. All calls still
consume the ordinary hard limits; this is not an unbounded semantic-cycle detector.
A changed accepted candidate clears the failure window. Rejection state is saved
in checkpoints. Resuming an exhausted rejection allowance performs no new call.
Older checkpoint policies are rejected rather than silently migrated; external
verification/authority stores and earlier checkpoint files are not rewritten.

A repeated invalid answer is not convergence or success. The best accepted answer
and its paired notes survive failure. Without an incumbent, a rejected proposal
cannot become the reported final answer. Full judges and final verifiers retain
exact evidence and their original scope; an advisory map never proves a claim.

This interface fixes control failures, not a small model's knowledge or arithmetic
ability. The recorded Gemma retry produced two malformed action replies, then
stopped with empty working notes and no accepted solution. No quality improvement
or successful-task token-saving percentage is inferred from that failed trial.
