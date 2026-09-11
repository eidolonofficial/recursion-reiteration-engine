# Folding governance: proposal, experiment, admission

Version 0.4.0 adds an optional **trusted-host governance layer**, not a replacement
for the mathematical solver, a trained memory model, or a universal proof checker.
Import it from `headroom_recursion.folding`. It uses only the standard library.

## Roles and authority

A worker receives a bounded `generation_packet`, offered public source ranges,
and the existing Headroom workspace. Its output is a proposal, not an evaluation.
Only the trusted host owns `Store`, registered `Evaluator` and `Checker` callables,
and the `Folding` object. Do not expose those objects or their database to model
tools. Model labels, JSON `status`, self-scores, and imported receipt dictionaries
cannot grant promotion authority.

The local API is not an operating-system isolation boundary. A process running
as the same user can often read that user's files, including the vault. Deploy
untrusted workers under separate accounts/containers with read access only to
explicit public inputs. The supplied subprocess demonstration is killable but is
not an OS sandbox, and no inference network or model weights are required.

## Immutable identities and a closed evaluation family

`Policy` freezes an objective, loss definition, declared population, evaluator
install hash, minimum effect, family budget, split sizes, and resource ceilings.
`Proposal` freezes exact parent/child artifact hashes, a single declared mechanism,
prediction, falsifier and bias/correctness class. A declaration does not automatically
prove that arbitrary code implements exactly one causal intervention.

`Folding.create` registers actual JSON evaluation units, not unverified split
labels. Identical unit content cannot cross split boundaries. Within the same
store, material registered for one campaign's validation/holdout cannot become
another campaign's fresh confirmation input. Development-to-development reuse is
allowed. This detects **identical content**, not semantic duplication, correlated
instances, renamed copies, or data an operator has seen outside the system.

A family follows this sequence:

1. Freeze proposals against the exact champion. Combinations name two separately
   screened components and require a four-arm interaction test first.
2. Run a cheap premise on a prefix of development units, then the full screen.
   These are exploratory gates, not confirmatory significance tests.
3. Starting validation closes generation and generation-facing memory writes for
   the entire family. Already-frozen survivors may still be evaluated. No new
   hypothesis, retuning, or proposer packet is issued after that point.
4. Select one validated candidate. Reserve the single holdout use **transactionally
   before computing any outcome**. A crash or interruption consumes the reservation.
5. Recompute gates from paired measurements and verify every artifact, evaluator,
   split and receipt identity before an atomic champion replacement.

An unsuccessful confirmation does not reopen generation on the same split. Begin
another campaign with fresh confirmation units. This conservative implementation
also keeps a successful family closed; it does not automate an endless stream of
promotions that reuses one holdout. Archived old champions and receipts remain.
`rollback(reason)` restores the previous champion without erasing history, reopening
generation, or resetting the consumed holdout.

SQLite `BEGIN IMMEDIATE` serializes state transitions, and a content-hashed event
chain records revisions. Hashes detect mismatched contents; they are **not digital
signatures or authentication against an owner who can rewrite the database**.
Copying or deleting the entire store can defeat local reuse history. Retain one
trusted durable store or an externally authenticated registry across processes.
The store records immutable full state snapshots; its storage is not bounded by
the prompt budget and can grow substantially during long campaigns.

## Measurements and statistical scope

A trusted evaluator returns `{loss, cost, output}`; a separately installed checker
checks the original instance and the output. Loss lies in `[0,1]`, lower is better.
The evaluator is responsible for a faithful metric, all relevant compute costs,
randomization and reproducibility. Its code hash must cover the exact approved
install (including transitive execution dependencies); a matching arbitrary label
is not automatic code attestation. The example integration rehashes its worker
and pinned mathematical sources before each subprocess call.

Promotion does not trust a candidate-supplied mean, interval or unit count. It
recomputes paired differences `D_i = loss_child - loss_base` in `[-1,1]`. With
`a = policy.alpha / (2 * policy.max_candidates)`, the confirmatory upper bound is

    mean(D) + sqrt(2 * log(1/a) / n).

The upper bound, capped at one, must be strictly below `-min_effect`; all outputs
must pass their checker, and both arms must have zero resource failures. The two
confirmatory gates and the fixed maximum family size receive a conservative
union-bound allocation. No repeated peeking, extension after inspecting outcomes,
or adaptive new proposals on validation data are supported.

This is the one-sided bounded-difference Hoeffding calculation. Its inferential
interpretation requires a defensible sampling design with independent paired units
(or a separately justified sampling concentration result), a fixed metric, and a
predeclared target population. Unique hashes **do not establish independence**.
For a fixed structured/deduplicated test bank, passing the numeric gate is an
operational selection on that bank, not an established confidence statement about
arbitrary real-world inputs. Numeric bounds use ordinary Python floating-point
arithmetic, not interval arithmetic or a formal statistical proof checker.

Premise and screen gates use only zero-failure and declared mean-effect conditions.
Combinations require all four arms: parent, A, B, and AB. The implementation records
`mean(AB-A-B+parent)`, checks every arm, and reruns ordinary screen/confirmation on
AB. The interaction is a development diagnostic, not a proof of beneficial synergy.

Resource ceilings are checked after calls. Host callbacks are cooperative and can
hang; use an externally killable worker for hard deadlines. The P-versus-NP test
uses 10-second subprocess limits. Node counts are not equivalent to equal wall
time or equal arithmetic cost. Certificate checking is included in measured time.
An UNKNOWN result can be a valid correctly reported nondecision; the registered
loss must penalize it appropriately instead of relabeling it UNSAT.

## Three evidence classes, no automatic upgrades

- **Empirical promotion** binds a selected artifact to the declared measurements
  and policy. It never establishes a universal mathematical statement.
- **Checked finite claim** binds an exact statement, domain and evidence to an
  installed finite checker. Exhaustive small instances are still finite evidence.
- **Checked formal claim** requires a trusted formal verifier that actually checks
  the exact statement and all hypotheses. None is shipped in this release. A toy
  callback in unit tests exercises registration only; it is not a proof kernel.

`admit_claim` does not execute a model-written checker. Coverage must match the
trusted registration, returns must be literal `True`, and verifier errors fail
closed. Dependencies reference prior **claim receipt** hashes (available via
`fold.admission(id)['claim_ref']`), not arbitrary citation strings. A formal claim
cannot take a finite result as a general premise. Registrations remain part of the
trusted computing base: a deliberately dishonest operator callback defeats any
application-level schema guarantee.

`ResearchBridge` accepts only exact externally issued admission records and keeps
the imported historical document byte-for-byte. Historical prose is preserved,
not retroactively proved. Each new record earns a Headroom `ProgressCheck` lock.
A lost or forged record is rejected before judging; answer and notes roll back
 together. The bridge disables model-judge halts and sufficient-validator halts:
a score of one or a finite receipt cannot declare the overall research target solved.
A future general proof must be handled as a separate explicit verification task.

The bridge's initial release adds admitted records. It deliberately does not allow
arbitrary rewriting of the historical research document or automatically convert
an unverified proposal into evidence. Work in progress can remain in visible notes;
claim admission requires the externally checked result.

## Bounded memory and source access

The trusted writer records a concise development-derived summary, preserved
component, and next falsifier, bound to an actual premise/screen receipt. It cannot
create generation-facing entries from validation or holdout results. Advisory prose
is not proof authority; an operator must review any summarizer supplying it.

The selector sees a pool of at most `2K` records and can return only existing IDs,
up to `K`. Selected entries are retained whole under the rendered packet budget;
mandatory proposal/policy content that cannot fit causes failure, not truncation.
There is no API to read unoffered private receipt hashes from a proposer packet.
Public artifact reads are bounded exact UTF-8 byte ranges. Headroom workspace
patches separately use character offsets. Do not mix the two protocols.

The implementation uses deterministic lexical ranking, not trained SLMs, vector
retrieval or automatic graph consolidation. It follows the uploaded LightMem
paper's separation of selection (Appendix 10.2) and compact memory writing
(Appendix 10.3), without replicating its models or performance claims.

## Minimal local use

Run the complete arithmetic example:

    PYTHONPATH=src python -B -S examples/folding_demo.py

For a research loop, obtain scoped admission IDs using a trusted evaluation/check
workflow, then bind them to the existing controller:

    bridge = ResearchBridge(fold, exact_history, tuple(admission_ids))
    cfg = bridge.bind(RecurseConfig(n=1, T=1, ladder=(Tier("local"),)))
    trace = recurse(task, client=your_workspace_aware_client, config=cfg)

This uses `WorkspacePolicy` for bounded working context. Full reconstructed
candidates still reach required progress checks and full-candidate judges.

## Compatibility and provenance

The default non-folding controller keeps its previous judge-halt behavior.
`judge_can_halt=False` is new and is frozen into checkpoint policy. Old checkpoints
missing that policy field can fail closed rather than being silently reinterpreted;
start an explicit newly budgeted continuation from its checked candidate and notes.
A folding family and an exhausted Headroom call budget are different lifecycles;
restarting the text controller does not reset spent experimental units.

This is a new implementation of the reviewed governance concepts, not a copy of
the estimator research corpus, the permissive auditor, or its packet builder. No
challenge-specific objectives, private outcomes or evaluator split numbers are
included in this clean repository. The P-versus-NP validation lives in a separate
research package. Neither upstream repository was changed or published.

## Primary-source context

Hoeffding, W. (1963). Probability inequalities for sums of bounded random variables.
Journal of the American Statistical Association 58(301), 13–30.
DOI: 10.1080/01621459.1963.10500830.

SQLite documentation: transaction behavior, especially BEGIN IMMEDIATE.
https://www.sqlite.org/lang_transaction.html

Zhang et al. (2026), Lightweight LLM Agent Memory with Small Language Models,
arXiv:2604.07798v3. Used as supplied architectural context, not as benchmark evidence.
