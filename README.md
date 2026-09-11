# Recursion Reiteration Engine

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
