# Efficient transport, v0.5

## Boundary

Use `RecurseConfig.efficient()` or `--efficient` with a worker supporting
workspace-v2. The default constructor and explicit workspace-v1 remain compatible.
Efficient mode changes transport and progress selection, not the recurrence depth,
trusted validators, candidate mathematics, or authority needed to promote results.

The optimization target is transmitted model input plus output, measured with the
selected tokenizer. Archive file size and network compression are different
quantities. Tiny tasks can cost more with a patch protocol; ordinary mode remains
available. There is no universal minimum prompt or guaranteed savings percentage.

## Compact wire

The packet retains the exact task and operator pins, check counts, source lengths,
and bounded exact excerpts. Excerpts use `[start,text]`; their end is computed from
Unicode character length, not UTF-8 bytes or token offsets. Only protocol metadata
is abbreviated. Source content is never algebraically simplified or rewritten.

Full source hashes and scope remain in the host state. Per-request aliases `s0`,
`s1`, and so forth name only offered sources. The unchanged full SHA-256 request
ticket binds those sources, original candidate, scope, model and current call
position. The worker copies the ticket once in its patch, instead of also copying
scope and base hashes. A ticket is an integrity binding, not authentication or
permission for unoffered filesystem access.

An answer is `{"patch":{"ticket":"...","edits":[[start,end,text],...]}}`.
The existing exact-patch validator reconstructs the complete answer, checks read
authorization, sorted/disjoint edits, required passages, and declared dependency
closure. It rejects authority fields, stale tickets, and unseen replacement text.

A read is `{"read":[["s0",start,end],...]}`. At most eight distinct requested
ranges fit one round by default. Their **sum**, not merely each range, must fit
`memory_read_chars`. Adding all requested material is transactional: malformed,
unoffered, corrupt, or oversized requests do not partly change edit permissions.
Retrieved ranges stay exact and mandatory. Overflow is an explicit context error,
not silent clipping. Every actual retrieval exchange consumes the call budget.

The efficient profile selects at most six optional chunks of up to 768 characters,
within its 4096-unit complete system/user budget. This is a relevance/recency
heuristic, not a semantic sufficiency proof. Mandatory text is outside the chunk
count but inside the overall budget. Set `required_passages` and `dependencies`
for essential statements; exact omitted text remains retrievable.

## Progress without redundant selection calls

`progress_seed_mode="local"` uses the existing bounded source selection locally.
It still carries the model-written incumbent and notes and still enforces all
progress checks. It does not invent new notes or pretend a selection model ran.
The trace reports `local-carry-forward` with zero completion calls. Selecting
`"model"` restores the extra model selection step.

## Identical judgment reuse

`reuse_exact_judgments=True` retains successful, nontruncated **single-vote**
judgments within one live run. The key compares complete task, candidate, notes,
judge system/template, model, output allowance, pins, obligation status and
verification identity. A changed input forces a fresh judgment. Compressed judge
requests and multiple votes never use this cache. Invalid parse retries are not
replaced with cached outputs. At most 16 entries and one million key-text
characters are retained.

A hit is recorded separately as `exact-judge-reuse`, with its originating call.
It consumes no completion call and contributes zero new input/output units.
It is the original heuristic judgment, not a fresh opinion, proof, or independent
vote. Live budget/deadline checks still apply. Nothing is restored from a saved
cache: resume must recheck and regrade its incumbent.

The whole-candidate judge still receives full exact proof text, notes, pins and
check statements when called. This change does not replace full proof review with
an unverified delta reviewer. Validators and progress predicates run normally even
when a matching heuristic judgment is reused.

## Measurement

`benchmarks/efficiency_replay.py` compares workspace-v1, compact-v2 with model
selection, and compact-v2 with local carry-forward on an external 100-stage
recorded-delta fixture. A reproducible source-audit fixture can also be built
with `benchmarks/make_source_fixture.py`. It is not a neural research workload.
Each arm uses the same task, exact recorded candidate
changes, notes, judge replies, locks, and final-state checks. It batches only reads
that the fixture needs before applying those changes; it never authorizes editing
an unseen span. The script checks that all complete judge requests are identical.

Use `--encoding characters` for exact Unicode counts. The optional tokenizer modes
require an already-installed tokenizer and already-cached vocabularies; the script
refuses downloads. It counts visible system and user text separately, and actual
response text. It excludes chat framing, tool schemas, caching discounts and model
hidden reasoning. No hosted inference service is used. The core has no dependency
on that measurement package and accepts any trusted local tokenizer callback.

Recorded responses do not adapt to the smaller prompt. This measures transport
and controller preservation, **not** fresh-model accuracy, latency or billing.
Historical certificates are compared as exact fixtures, not newly established
mathematical results. The fixture data and transcripts are not part of this release. Measured results
and distinct fixture scopes are recorded in `TESTING.md`.

## Packaging and notices

The skill and coding instructions are shorter and task-focused. License notices
and detailed provenance remain separate from those working instructions. Runtime
prompts do not automatically load either notice file; their bytes are not counted
as runtime savings. Static documentation-token reductions must be reported
separately from actual controller-call reductions.

The SQLite store now closes its connection when initialization/audit fails. This
fixes the failed-constructor cleanup path observed on Windows without suppressing
any verification error or changing evidence authority.
