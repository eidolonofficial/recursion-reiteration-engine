# Recursion Reiteration Engine

## v0.8.1: audited boundary and evaluation repairs

**Status: engineering repair release.** Regression tests cover the identified
boundary defects; improved model task completion and successful-task token
savings have not yet been established by a fresh post-repair comparison.

Payload-only requests include their exact candidate after serialization; retries
carry fresh feedback. Observations are transmitted once without dropping judge
evidence. Private memory writes have durable pending/committed receipts and
explicit current-head retries. Empty-store and explicit lookups need no query model.
The repaired paired pilot distinguishes test output, regression specificity,
accepted-milestone recovery, memory recall and arithmetic application.
See `references/audit-repairs.md` for interfaces, compatibility and evaluation scope.
This release does not claim a trained LightMem reproduction or universal savings.

## v0.8.0: schema-constrained output

`RecurseConfig.structured(schema, ...)` adds a payload-only response contract at
actual inference time. The optional `LMStudioClient` uses an already-loaded local
GGUF model; no SDK, hosted provider or runtime package dependency is added.
Unsupported clients fail before inference. Python retains source bindings, full
checks, feasible incumbents and repeat accounting. Existing memory and compression
algorithms are unchanged. See [the contract](references/structured-output.md) and
[executed qualification](TESTING.md). `examples/structured_selection.py` separates
model proposals from an explicit exact-solver mode.

## v0.7.0: one checked worker action

Use `RecurseConfig.simple(...)` or `--simple` for one typed proposal per step.
Python resolves offered blocks, checks results and carries exact feedback.
Malformed commands never become notes; repeated failures stop after two attempts
by default, including across resume. No runtime dependencies or models were added.
The previously tested symbolic view is retained. See `references/worker-actions.md`
and `TESTING.md` for the exact interface and the failed-but-bounded Gemma trial.

## v0.6.1: private memory integration

Continues verified base `690fcbe535a8c02850992e5ba8bd66e84a7a02d3` without
rewriting history. Private user/project records retain exact sources, versions,
negations, declared dependencies and host pins. Controller, selector and writer
roles are separate; optional models use the same metered completion boundary.
The built-in ranker is lexical, not neural or vector retrieval.

Enable the compact searchable transport with `--archive-search`. Persistent
memory additionally requires `--memory-db PATH --memory-user USER
--memory-project PROJECT --verification-id REVIEWED-VERSION`. A dry run does not
create the database. `--profile coding` and `--profile research` choose explicit
bounded schedules, not models; `--rungs 100` repeats only the one supplied model.

The Python API exposes `MemorySession`, `ObservationLedger`, private staged
consolidation and exact dependency-scoped `ReviewGraph` receipts. Full-candidate
judging remains the default. Host admissions and finite receipts do not settle
universal claims. No weights, shared graph, automatic backend activation, hidden
child agents or runtime KV cache are included. Existing optional compressor
hooks remain explicit host integrations, not newly benchmarked features.

See [the private-memory contract](references/private-memory.md), run
`PYTHONPATH=src python -B -S examples/private_memory_demo.py`, and read
[the current testing scope](TESTING.md). Historical v0.5 token comparisons below
are not measurements of v0.6 neural task quality or automatic host-transcript savings.


A local, model-neutral controller for iterative refinement. It keeps exact evidence
outside the working prompt, carries checked progress between tiers, and admits
experimental improvements through an external evaluation workflow.

**Runtime dependencies: none.** Supply a reviewed Python callable, local subprocess,
or manual responses. No provider, inference service, credentials, or weights are
selected or downloaded automatically.

## Start

```bash
python -m pip install .
reiterate --efficient --manual --n 2 --steps 3 --max-calls 50 "Your task"
```

For an explicit worker:

```bash
reiterate --efficient --command-json '["python", "worker.py"]' \
  --workspace-tokens 4096 --max-calls 100 --max-seconds 600 "Your task"
```

The worker reads one request JSON object from stdin and returns a completion JSON
object on stdout. See `examples/local_worker.py` for the transport and
`examples/efficiency_demo.py` for compact responses. The transport flags do not
make an existing worker understand a new workspace schema.

## Efficient mode

`--efficient` or `RecurseConfig.efficient()` enables:

* Compact workspace-v2: short per-call source aliases, smaller instructions,
  offset/text excerpts, and delta answers rather than full-document rewrites.
* Bounded optional context selection and batched exact archive reads.
* Local carry-forward of existing model-written progress, avoiding a separate
  model-selection call at every tier. Checks and the incumbent remain enforced.
* Run-local reuse of **identical** valid single-judge inputs. Changed candidates,
  notes, pins, models, checks, or verification identity invalidate reuse. Multi-vote
  judgments and failed/truncated replies are not cached.

The recurrence's note count and step count are unchanged. Choose them explicitly;
more calls are not automatically better. Reuse is a heuristic snapshot, not a
fresh independent opinion. It is never persisted across runs or resume.

```python
from headroom_recursion import RecurseConfig, Tier, recurse
from headroom_recursion.clients import CallableClient

# generate(**request) is a reviewed local function returning response text.
cfg = RecurseConfig.efficient(
    n=2, T=3, ladder=(Tier("worker-small"), Tier("worker-large")),
    max_total_calls=100, judge_can_halt=False,
)
# trace = recurse("Your task", client=CallableClient(generate), config=cfg)
```

Identifiers and tier order are operator choices, not inferred capability rankings.
Default `RecurseConfig()` and `--workspace-tokens` without `--efficient` preserve
the earlier protocol. Override `progress_seed_mode="model"` to keep a fresh
model-selection call. Set `reuse_exact_judgments=False` for fresh judgments.

## Exact evidence, small workspace

The model sees the current task, operator pins, exact selected excerpts, check
counts, and source lengths. It does not automatically receive the whole archive.
Required passages and their operator-declared dependencies remain intact; a budget
that cannot fit them stops the call instead of cutting evidence.

A compact answer is a patch against the request ticket:

```json
{"patch":{"ticket":"copy the offered ticket","edits":[[120,140,"replacement"]]}}
```

Offsets address the **original candidate**, in Unicode characters, with the end
exclusive. Replace only shown/retrieved ranges. Insert at a visible boundary or
EOF. Empty edits keep the candidate. Unmentioned text is preserved exactly.

Fetch several needed ranges in one response:

```json
{"read":[["s0",100,200],["s1",0,80]]}
```

Aliases are scoped to the current request. Full source hashes, scope, and edit
permissions stay on the host. Retrieval consumes the same call budget; its total
range size and exact resulting prompt are bounded. It never grants access to an
unoffered source. Full validators receive the reconstructed candidate.

**Whole-candidate judges retain the full candidate, raw notes, pins, and check
statements.** Summaries, record hashes, and compact packets do not verify a proof.

## Count the right thing

Without an explicit tokenizer, counts are labelled UTF-8-bytes/4 estimates, not
measured tokens. Supply a trusted local `counter(text, model) -> int` using your
worker's already-installed tokenizer and set `token_counter_label` accordingly.
Reserve model-specific chat-template and output space separately from visible
system/user text. No universal token saving or minimum prompt size is promised.

The benchmark compares actual serialized calls and answers, checks exact final
state and judge inputs, and separately records avoided planning/cached calls.
Prerecorded-response replay tests transport and control logic; it cannot establish
unchanged reasoning quality for a model receiving reduced context. Static source
notices do not consume runtime tokens unless explicitly loaded into a prompt.

## Verification and progress

Strict judge parsing rejects prose numbers, NaN, booleans, malformed JSON, and
truncated replies. Scores are uncalibrated heuristics. Only a reviewed sufficient
validator can give a validated halt; necessary-condition gates cannot.

Register `ProgressCheck` predicates for required and earned milestones. Rejecting
a revision restores both incumbent answer and paired notes. These predicates cover
only what they actually test. Checkpoint/resume preserves resource consumption,
checks task/scope/policy identity, then rechecks and regrades the incumbent.

The optional `folding` package separates frozen proposals, trusted experiments,
and qualified promotion. It uses typed policies, exact artifact identities,
transactional exposure tracking, bounded development memory, and separate finite,
empirical, and formal evidence classes. `ResearchBridge` prevents favorable judge
scores from declaring research solved. Read `references/folding.md` before exposing
any tools; its authority database is not an OS sandbox.

## Test

```bash
PYTHONPATH=src python -B -S -m unittest discover -s tests -v
PYTHONPATH=src python -B -S examples/efficiency_demo.py
PYTHONPATH=src python -B -S examples/workspace_demo.py
PYTHONPATH=src python -B -S examples/folding_demo.py
```

Python 3.10+ is required. Lean/Mathlib is optional and not bundled. Historical tests
are recorded in `TESTING.md`; the current efficiency methodology is in
`references/efficiency.md`. Legacy `recurse` and `headroom_recursion` imports remain.

The create-only publishing helper targets the private repository
`eidolonofficial/recursion-reiteration-engine`; it does not update an existing repo.
See `PUBLISHING.md`. License and source history remain in `LICENSE` and
`PROVENANCE.md`; neither is injected into normal runtime requests.
