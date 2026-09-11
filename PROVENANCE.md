# Provenance and migration scope

## Source

The inspected source is `gmrmk/headroom-recursion` at commit
`23e6758e3b95510736711c9eb09d68fbf91063be` on its `main` branch:
https://github.com/gmrmk/headroom-recursion/tree/23e6758e3b95510736711c9eb09d68fbf91063be

The source README declares MIT. This package retains that license and credits
headroom-recursion contributors. Original ownership is not transferred.

This is a sanitized, refactored derivative made after reading the source, not a
claim of legally independent clean-room authorship. The new Git root has no
parents from the original repository. No original branch, tag, run output, or Git
object history is imported. The old repository is left unchanged.

## Preserved mathematical and controller concepts

The text-state recurrence, n=6/T=3 default shape, tier handoff, median voting,
threshold stopping, cycle detection, best-candidate selection, oracle feedback,
gate/sufficient distinction, provisional/statistical qualification, local citation
triage, and Lean pinned-statement/axiom-check design have corresponding local
implementations. The relationship to the cited neural recursion paper is stated
as inspiration, not a reproduction or inherited performance result.

The inspected Python modules were rewritten or refactored, not claimed to be
byte-identical. Compatibility with every old import, CLI flag, and test is not
promised. In particular, generation transport is now an explicit operator-selected
local function, subprocess protocol, or manual exchange.

## Byte-preserved source artifacts

These Git blob hashes were checked against the source-file metadata:

| File | Source Git blob SHA-1 |
| --- | --- |
| lean/lakefile.toml | ae2da41cc1136e9a70d6c4c4114c877bbd4a91e9 |
| lean/lean-toolchain | 18640c8b066b182147f324d3aefd8ee48ee45238 |
| lean/LeanOracle/Smoke.lean | e23a583e7aa84022766ee3cfd9c9d0a3780eaaef |
| lean/lake-manifest.json | 6bb05201603cf949b3fee45dd6322dde23c4e4f2 |

The package also adds `lean/LeanOracle.lean` as the root import module. This addition
has not been tested by a real Lean build in this environment.

## Intentional omissions and changes

Hosted model SDK clients, provider-specific model ladders and command wrappers,
cloud retrieval setup, automatic dependency installation, historical run outputs,
and old multi-run campaign/heartbeat/ledger automation are not ported. The previous
ledger interface is not reproduced.

The first clean export (0.1) omitted the external context-compression integration.
Version 0.2 corrects that omission with an active dependency-free local compressor
and an explicit optional Headroom library adapter. It adds source-archived
scratchpad views, model-selected tier seeds, checked progress obligations and
scoped checkpoint/resume state. This is a guarded subset of the external library,
not its entire proxy/tool/model-compression stack. See
[the contract and research mapping](references/memory-and-progress.md).

Automatic execution of generated Python verifier programs is disabled rather than
presented as safely sandboxed. Lean execution is opt-in and explicitly trusted.
The original Lean adapter's artifact-directory interface is not retained; callers
must save reviewed proof sources and compiler evidence through their own workflow.

The original main-branch module tree contains the recursion and verification
harness, not a separately named estimator implementation. No unseen local files,
other-branch implementation, private material, or mathematical estimator formulas
have been inferred or imported. Historical output documents are not reclassified
as established mathematical results or silently carried into this export.

## Correctness changes

Judge parsing rejects non-finite, out-of-range, Boolean, duplicate-key, and
non-JSON values instead of clamping or finding arbitrary numbers in prose.
Mathematical comparison preserves case and operators. Call budgets count attempts
at the actual transport boundary, including failures and parse retries. Truncated
updates are rejected, full visible states are traced, and the selected result's
model identifier stays paired with that result.

These are tested implementation changes, not a claim that every possible defect
has been removed or that any particular model's reasoning quality has improved.

Version 0.2 keeps source archives separate from lossy prompt views, rejects
truncated judge votes, grades supplied seeds before refinement, uses a common
judge for cross-tier comparisons, and prevents lower-scored or mechanically
regressed candidates from replacing the incumbent. Model plans can select existing
records but cannot manufacture verification or alter the approved schedule.
Checkpoint resume rechecks the seed instead of trusting a serialized score.


## v0.3 bounded-workspace revision

This revision starts from the delivered v0.2 source snapshot. It adds an opt-in
archive/delta protocol and leaves provider transports, math/checker code and the
Lean project intact except for the controller integration documented in the diff.
It does not import the separately reviewed estimator-folding research corpus or
its competition records. Replaying recorded research documents is a transport
check, not new mathematical evidence. No GitHub repository was modified by this
release preparation.

## v0.4 folding revision

The revision starts from the delivered v0.3.0 commit `0d5607d`. It implements the
separation of frozen proposals, experiments and evidence-based promotion described
in the reviewed `gmrmk/recursive-estimator-folding` snapshot `102bd7c`. It does not
copy that repository's permissive auditor or its packet builder, and imports none
of its estimator corpus, outcomes, competition parameters or holdout split numbers.

New standard-library code supplies strict contracts, transactional local storage,
source-bound memory, bounded proposer capabilities, one-use holdout reservation,
paired evidence gates, scoped claim checker registration, explicit rollback and
the ResearchBridge. The legacy recurrence is unchanged except for a configurable
judge-halt permission frozen into checkpoint policy. Folding disables that
permission and keeps finite/statistical admissions insufficient to settle a target.
The four original Lean project files remain byte-identical.

The separate validation package recomputes prior P-versus-NP finite evidence and
runs actual pinned solver code. It is not part of this clean source export. Its
population is constructed and narrow; its manually authored controller responses
are not autonomous model inference, and no general complexity result is claimed.

## v0.4.1 standalone release identity

The user selected **Recursive Reiteration Engine** with skill slug and distribution
name `recursive-reiteration-engine`, targeting a new repository under
`eidolonofficial`. The verified input is the delivered `headroom-recursion` v0.4.0
source ZIP, SHA-256:

    d16a233d5e39bc416647d191dde6512d8bcd616b3dc193cc8840cca5f04a3d74

This revision changes the release identity, documentation, console entry points,
and create-only publication target. It retains `headroom_recursion` imports, the
`recurse` command, all existing runtime modules and the original license. The
`reiterate` and `recursive-reiteration-engine` commands resolve to the same CLI.
The new repository starts from one fresh root commit; neither upstream repository
is renamed, forked, transferred, or overwritten. Research archives and the supplied
PDF are not included.

This is a renamed derivative, not a claim of independently reproduced authorship,
a new mathematical discovery, or a new model-performance benchmark.

## v0.5 efficient transport

This revision retains the license and the full earlier source record. Background
credits are not repeated in the skill or coding instructions. It adds an explicit
compact workspace-v2, bounded batched reads, local progress carry-forward, and
run-local exact single-judgment reuse. Earlier wire behavior is still available.
See references/efficiency.md for the trust and measurement boundaries. No claims
of exclusive authorship, formal proof, model-quality parity, or universal optimal
token savings are made.


## v0.6.0 private-memory integration

Integrated from verified repository commit
`690fcbe535a8c02850992e5ba8bd66e84a7a02d3`. The previous transfer was incomplete;
complete draft source patches were recovered, inspected, and revised rather than
assumed to be a verified release. The private lexical implementation replaces the
draft's vector/shared-graph paths. Sources and tests contain no user research
transcripts or runtime databases. Existing attribution and license are retained.
The architecture uses bounded role separation and incremental private records;
no trained model, paper benchmark replication or universal proof is claimed.

## Completion audit

The unpublished v0.6.0 draft `8f98660` was recovered from the operator's worktree,
not replaced from memory. A separate checkout preserved that work and hardened
whole-record role packet selection, current-entry consolidation reservations and
paired quality regression reporting. The observed local-model regression and
timeout remain documented in TESTING.md. No failed experiment was relabelled as
quality-preserving compression. Existing license bytes and Git history remain.

The recovered draft was published as v0.6.0 while this hardening was being
qualified. The finishing changes are v0.6.1, a normal descendant that preserves
that release and its assets rather than moving the existing tag.

## Worker boundary completion

v0.7.0 preserves the previously tested symbolic work and adds a strict one-action
worker interface, host-owned checker feedback, durable bounded rejection tracking,
and a finite Python arithmetic example. No new model weights or learned compressor
are introduced. The existing license notices remain outside runtime prompts.
The failed local-model trial and its bounded termination are documented in TESTING.md.
