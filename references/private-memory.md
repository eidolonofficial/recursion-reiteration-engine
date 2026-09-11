# Private memory contract: v0.6.0

## Scope and defaults

This implementation covers private versioned delta memory, bounded exact archive
search, observation masking, role separation, explicit private consolidation and
dependency-scoped verification. It does not implement trained LightMem models,
vector retrieval, shared graph consolidation, automatic compression-policy
learning, recursive child agents, or a persistent KV cache. A `MemoryModels`
identifier is an opaque operator choice, not an installed model.

`MemoryPolicy` defaults: K=5, at most 2K coarse candidate slots, 800-character
whole summaries, an 8,000-character role packet, four queries/writes, 10,000 active
records, 100,000 historical versions, and a 64 MB per-principal source archive.
No default local fallback invokes a language model. Retrieval uses exact lexical
word overlap; it can miss relevant paraphrases. History and sources are preserved
when active entries are pruned. Capacity overflow rejects writes rather than
erasing evidence. Limits count Unicode characters or explicitly labelled bytes;
they are not claims about a model tokenizer or the total SQLite file size.

## Roles and actor boundary

The host creates `MemoryStore(path)`, `Principal(user, project)` and
`MemorySession(store, principal, models=MemoryModels(...))`. Never hand a worker
these objects, Python callbacks, the database handle or its filesystem path.
Only bounded role-specific JSON crosses the metered `send` callback. Ordinary
engine calls, retrieval exchanges and all optional memory roles consume the same
attempt/deadline budget. `LocalRoleRunner` provides a separately bounded callback
for explicitly scheduled offline work. Cooperative deadlines cannot interrupt an
arbitrary stuck callback; the operator's transport must enforce its own timeout.

A controller proposes private queries. A selector returns only offered IDs and
cannot rewrite records. A writer proposes typed keys and summaries; the host binds
exact sources and optimistic heads captured before inference. Unoffered existing
keys and concurrent edits are rejected. Host pins cannot be weakened by a writer.
A model may still propose semantically wrong advice; schema validation is not a
truth detector. Use source review and independent checks for important decisions.

Raw conversations are not automatically ingested. `write_turn` is an explicit
host operation on an accepted interaction/delta. `accepted_revision` archives the
full old and new candidates, then offers their bounded exact delta. An oversized
delta is archived without an automatically truncated summary. The fallback stores
a complete exact delta or declines to write. A 'fact' kind is still advisory.

## Versions, dependencies and recovery

Every immutable version has a stable content ID, topic key, source refs, creation
time, predecessor, principal, kind, tags and advisory authority. Writes require
an exact expected head. Dependencies are explicit version IDs, not relationships
inferred from prose. Updating or retiring a prerequisite invalidates transitive
dependents. Host retirement requires an exact resolution source and is recorded.
Pinned records cannot be silently pruned or superseded. A missing pin budget stops
the request instead of dropping the constraint.

Historical retrieval is explicit and labelled with `historical_query`; current
and superseded versions must not be confused. Invalidated dependencies remain
conservatively excluded even in historical views. Database identity, principal,
policy and role models are bound into checkpoint configuration. Resume does not
freeze the private database: fresh memory is retrieved, and the incumbent is
rechecked. A database copy retains its identity; it is not a signed authorization.

SQLite hashes detect accidental corruption. Logical principal isolation is not
an OS sandbox or protection from an attacker with the host's Python/filesystem
access. Unix mode bits do not configure Windows ACLs. The operator remains
responsible for a private directory, disk encryption, backups and retention.
Sources, histories and audit metadata are retained, not securely erased by pruning.
No cross-user publication API exists. Never put a runtime DB in a release.

## Search and observations

Search requires compact workspace plus `enable_search=True`. Requests contain
only currently offered aliases and literal Unicode text. Cursors cover bounded
scan windows, including overlapping matches at window boundaries. Exact returned
ranges authorize edits; a match identity alone does not authorize unseen edits.
Search and read batches share the same retrieval-round and character budgets.
The host preserves whole original candidates and still validates full proposals.

`ObservationLedger.record` accepts a host label, exact output, status, source
revision, optional exit code, failed-test count, actionable outcome and critical
flag. A success contradicting a failure count or nonzero exit code is rejected.
Full unresolved failure/unknown/critical output is mandatory. Oversized mandatory
output stops with `ContextLimitError`. Older routine successful output may be
masked with exact source links. Omitted observation counts remain visible.
A missing comparison revision produces unknown staleness, not a current verdict.
Only a host operation with a same-scope source resolves an observation.

## Event-driven private consolidation

`consolidation_due` is a signal, not a hidden background task. The host may call
`session.consolidate(send=...)` at an accepted milestone or after the signal
indicates accumulated deltas. It reserves a bounded current-record batch and
stages typed proposals. No model sees full historical transcripts or private
principal metadata, though summaries can themselves contain private data.

To apply a reviewed proposal, call `store.apply_consolidation(principal, job,
draft_hash, approve=trusted_review, approval_id=versioned_review_identity)`.
The trusted callback must return the boolean `True` for the exact draft. Apply
rechecks every offered head and commits the resulting versions and approval
atomically. Changed prerequisites invalidate derived records. No callback result
upgrades advisory authority. Failed jobs retain originals and are visible in the
host-owned job table; they are not silently retried or automatically published.

## Verification and measurement

`ReviewGraph` is a host-owned registry of exact `ReviewRecord` objects and reviewed
checker callbacks. Receipts bind the exact dependency closure, scope, checker
identity and in-process checker generation. Changed records/checkers invalidate
transitive receipts. Returned receipts are copied; tampering and stale generations
fail verification. Receipt coverage is only the declared exact records and their
dependencies, never an automatically inferred whole-proof certificate. Pure,
versioned checkers are required; changes to external checker inputs require host
invalidation or registration of a new checker. No registry object goes to a model.

`ResearchBridge.admit_checked` admits exact externally issued records while
preserving all historical text. It labels whole-proof review as false and performs
zero model calls. It is an admission operation, not a substitute for a full judge.
Binding the bridge disables automatic memory writes so confirmation-bearing
admissions do not become future generation memory.

`quality_eval.evaluate` executes both supplied context arms using fresh callback
calls and an independent host answer checker. It includes failures and supplied
preparation units, counterbalances order, and reports zero-success arms without
a fabricated cost-per-success. The caller must account for any nested inference,
retrieval, retries, compression and verifier work inside their own backend; this
interface cannot inspect hidden work. Counter labels, neural-backend attestation
and held-out representativeness remain explicit. A deterministic test is not a
neural quality study. Cached/prefill tokens, context occupancy and latency must be
reported separately. No v0.6 neural savings percentage is asserted.

## Whole-record packet pressure and quality gates

Controller history and writer heads are selected as complete records within the
role packet budget. The exact accepted interaction is never shortened to make a
writer call fit: oversized input is archived without a model write. A writer may
update only heads actually offered before inference. Consolidation selects whole
current entries before reservation; unselected entries remain queued. Stale queue
pointers may be removed, never their original sources or historical versions.
An impossible consolidation packet does not consume its pending batch.

Fresh-response evaluation reports per-case regressions separately from gains.
Equal aggregate success is not non-regression. The finite regression gate requires
all reduced-arm tasks to succeed and no incomplete attempts; it is not statistical
promotion. Timed-out output is unobserved, not a measured zero-token completion.
Use the accounting completeness flag before interpreting cost-per-success.
