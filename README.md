# Recursive Reiteration Engine

**Refine an answer without discarding the work that got it there.**

A local, model-neutral controller for recursive refinement. It updates visible
working notes, revises a candidate, checks the result, and hands committed progress
to the next operator-selected model. The 0.4 series adds a separate, transactional
folding governance layer: frozen proposals, trusted paired evaluations, one-use
confirmation, and explicitly scoped evidence admissions. Version 0.3 introduced the bounded
archive workspace and read-authorized candidate patches. The full evidence
remains available to validators and judges instead of being repeated in every
worker prompt. Existing compression, progress checks and checkpoints remain.

The default runtime uses only Python's standard library. It requires **no hosted
inference service, credentials, proxy, or model download**. Connect an already
loaded model through a Python function, an explicit local worker, or manual prompt
exchange. Model identifiers and their order belong to the operator.

This is a fresh-history derivative of `gmrmk/headroom-recursion`, prepared for
`eidolonofficial`, not an independently authored clean-room reproduction.
[Provenance](PROVENANCE.md) identifies the source and scope. The skill and Python
distribution are named `recursive-reiteration-engine`; the established
`headroom_recursion` import namespace and `recurse` command remain compatible.

## Use as an agent skill

Keep this repository in a directory named `recursive-reiteration-engine` inside
your agent's supported skill location, or point the agent directly to `SKILL.md`.
The front matter declares the exact skill name. Follow `AGENTS.md` for development.
The prose skill supplies a workflow; use the Python controller for mechanical
checks, budget enforcement, rollback, and persistent evidence.

The release excludes research corpora, raw experimental transcripts, private
runtime databases, model weights, and credentials. They are not needed to run the
included deterministic examples.

## Bounded working context, exact archived evidence

Enable `RecurseConfig(workspace=WorkspacePolicy(budget=4096))` or
`--workspace-tokens 4096` with a workspace-aware worker. Candidate, scratchpad,
reference and obligation views share one full-prompt budget. Workers propose
small patches; the controller reconstructs and checks the full candidate. Whole
judges remain exact. This is context selection, not a lossless proof summary.

The paired 100-stage recorded-response test reduced input characters by **68.55%**,
including 182 additional archive-read exchanges. It is not a neural-quality or
upstream Headroom performance test. See [the protocol and limits](references/workspace.md).

## Folding without model-controlled promotion

`headroom_recursion.folding` separates proposal generation from trusted evaluation
and promotion. It keeps an immutable champion, strict schemas, exact artifacts and
unit registries, paired measurements, a consumed-on-reservation holdout, and
source-bound development summaries. Generation closes before confirmation so
held-out feedback cannot produce new mutations in that family.

Use `ResearchBridge` to admit only exact externally issued records to a bounded
Headroom workspace. The complete incumbent remains available to progress checks
and judges. Empirical promotion, checked finite results, and formal claims have
separate types. The bridge disables model-judge success halts: a high score or
finite benchmark cannot settle a mathematical research target.

```sh
PYTHONPATH=src python -B -S examples/folding_demo.py
```

This is a trusted local API, **not an OS sandbox or a shipped proof kernel**.
Statistical bounds require justified independent sampling; distinct hashes alone
do not establish it. The arithmetic example is a constructed workflow check.
Read [the authority, holdout and memory contracts](references/folding.md).

## Run the checked examples

From the source directory with Python 3.10 or newer:

```sh
PYTHONPATH=src python -S examples/workspace_demo.py
PYTHONPATH=src python -S examples/progress_memory.py
PYTHONPATH=src python -S examples/rational_refinement.py
PYTHONPATH=src python -S -m unittest discover -s tests -v
```

The workspace example sends bounded archive views and exact patches through a
local deterministic worker. The progress example prepares checkpoints and rejects
a revision that loses a checked condition. The rational example runs an exact
Newton iteration through a real subprocess. **Neither is a neural-model benchmark.**

An optional offline installation provides `reiterate` and
`recursive-reiteration-engine` (plus the compatible `recurse` command); setuptools must already be
available as build tooling:

```sh
python -m pip install --no-index --no-deps --no-build-isolation -e .
reiterate --dry-run --ladder small-local,large-local --max-calls 32
```

## Legacy field compression (`workspace=None`)

Compression happens in the controller before a completion, not behind a flag that
an inference backend may ignore. `use_headroom=True` is now active by default.

The default **local extractive compressor** removes duplicate ordinary prose and
selects whole prose blocks under separate scratchpad and reference-context budgets.
It archives exact original text by digest and puts a redeemable source reference
in the prompt. Newly generated scratchpads are compressed before their next use,
including between the `n` note updates of one step.

Problem statements, candidate answers, system instructions, operator pins, and
check declarations bypass compression. Fenced code, `<verbatim>...</verbatim>`
blocks, and conservatively detected mathematical/constraint text are kept exact.
Syntax detection is not a semantic theorem prover: put critical assumptions in
`pinned_notes`, explicit `<verbatim>` blocks, or `ProgressCheck` declarations.

A protected block may exceed its soft component budget. It is not cut to fit.
A separately configured `max_input_tokens` ceiling stops the run before sending an
oversized prompt. Reserve model output and native chat-template overhead separately.

**Originals are recoverable; a shortened view is not semantically lossless.**
Working-note calls can request a bounded exact source range using the documented
`memory_request` protocol. Those additional completions consume the same call
budget. Replay text is not recompressed. Unknown or unoffered references fail
closed. Nothing can read another run's archive implicitly.

### The optional upstream Headroom bridge

`compression_backend="headroom"` calls an already-installed `headroom.compress`
through its `CompressConfig` interface. It sees only unprotected prose. Its model
compressor is explicitly disabled (`kompress_model="disabled"`), so this adapter
does not request compression weights. No service/proxy is started.

This is a **guarded subset of Headroom**, not its complete proxy, cache, tool,
output-shaping, or ML-compression stack. Unsupported external retrieval markers
and malformed/expanding results fall back to local extraction. Missing or
incompatible installations fail explicitly rather than dropping safety flags.
The upstream package and any custom callback are trusted local code, not an OS
network sandbox. The release's upstream bridge tests use injected contract fixtures;
a real installation could not be obtained in the build environment. The default
local compressor is fully exercised. See [TESTING.md](TESTING.md).

## Progress is proposed by a model, committed by the controller

Before the first tier with supplied progress, and at subsequent handoffs, a model
selects source records for a bounded checkpoint and suggests a next check. It
cannot rewrite those records, invent record ids, declare them proved, reorder the
ladder, change a model, or expand a budget. Invalid proposals use a deterministic
fallback. All tiers receive the incumbent answer and its paired notes.

With the default `enforce_progress=True`:

* Supplied seed answers are checked/scored **before** refinement, not assigned
  their self-reported score. An already sufficient validated seed halts directly.
* A common judge, explicitly chosen by `judge_model` or otherwise the final
  operator-selected tier, scores all candidates. A lower score cannot replace the
  incumbent. Malformed/truncated votes cannot authorize a commit.
* Operator-supplied progress predicates become locked when a committed answer
  satisfies them. Every later candidate must retain them. Missing/erroring locked
  checks reject a revision before judging; a flattering score cannot override them.

The model may still explore a bad revision. It remains in the private trace, but
both answer and notes roll back before the next step when that revision is rejected.
A known mechanically rejected candidate is never returned as the chosen fallback.

A judge score is an **uncalibrated heuristic**, not proof of quality or truth.
A locked predicate proves only what the supplied check actually tests. Statistical
and provisional checks do not create proof locks. Full validation still requires
an explicitly trusted *sufficient* validator. A necessary-constraint gate alone
cannot produce a validated halt. See [verification](references/verification.md).

## Connect a local model

```python
from headroom_recursion import CallableClient, ProgressCheck, RecurseConfig, Tier, recurse

# Adapt this to your already-loaded model's native inference method.
def generate_locally(*, model, system, user, max_tokens, temperature, use_headroom):
    return loaded_models[model].generate(
        system=system, prompt=user, max_tokens=max_tokens, temperature=temperature
    )

config = RecurseConfig(
    ladder=(Tier("small-local"), Tier("large-local")),
    seed_answer=prior_answer,
    seed_scratchpad=prior_visible_notes,
    scratchpad_tokens=1536,
    context_tokens=2048,
    max_total_calls=48,
    pinned_notes=("Exact operator-supplied task constraint",),
)
trace = recurse(task, client=CallableClient(generate_locally), config=config)
print(trace.summary())
```

The sketch requires your `loaded_models`, task, and prior-state values. No universal
model loader or chat template is assumed. To enforce a real mathematical milestone,
supply a reviewed predicate rather than trusting a string label in model output:

```python
from fractions import Fraction
from headroom_recursion import ProgressCheck

def positive_rational(answer):
    try:
        return Fraction(answer.strip()) > 0
    except (ValueError, ZeroDivisionError):
        return False

config.progress_checks = (
    ProgressCheck("positive-q", "q > 0", positive_rational, required=True),
)
```

This check establishes positivity only, not a residual tolerance or a complete
solution. Add an actual sufficient check for the full requested result.

## Command line and continuation

A worker consumes one strict JSON request on stdin and returns one strict JSON
response. See [local_worker.py](examples/local_worker.py). Execution uses literal
argv and `shell=False`; prompts never become command-line fragments.

```sh
recurse --command-json '["python", "my_local_worker.py"]' \
  --ladder small-local,large-local --n 2 --steps 3 --max-calls 48 \
  --seed-answer-file answer.txt --seed-notes-file notes.txt \
  --scratchpad-tokens 1536 --context-tokens 2048 \
  --scope my-task --checkpoint checkpoints/task.checkpoint.json \
  --problem-file task.txt
```

Resume with the **same task and execution policy**, omitting explicit seed files:

```sh
recurse --command-json '["python", "my_local_worker.py"]' \
  --ladder small-local,large-local --n 2 --steps 3 --max-calls 48 \
  --scratchpad-tokens 1536 --context-tokens 2048 \
  --scope my-task --checkpoint checkpoints/task.checkpoint.json \
  --resume checkpoints/task.checkpoint.json --problem-file task.txt
```

Resume restores exact originals, the committed answer/notes pair, locked checks,
tier/step cursors, and cumulative attempted-call and elapsed-time budgets. Saved
scores are not trusted: checks run again and the seed is scored again. Exhausted
budgets do not reset. Scope/task/policy mismatches fail before inference.
Custom checks, tokenizers, compressors, and corpus hooks require an explicit
`verification_id` when checkpointing; update it when their semantics change.
Checkpoint hashes detect corruption, not a malicious writer able to recompute
hashes. Use trusted private storage and one writer per checkpoint.

Manual exchange is also supported:

```sh
recurse --manual --n 1 --steps 2 'Your task'
```

Useful controls: `--no-compression`, `--compression-backend headroom`,
`--compress-judge-notes` (the answer stays exact), `--max-input-tokens`,
`--pin-file`, `--no-preseed`, and the explicit legacy `--no-progress-guard` opt-out.

## Accounting and limits

Every attempted completion consumes the call budget, including seed planning,
seed grading, failed calls, parse retries and archive replays. The elapsed-time
limit is cooperative: in-process code cannot be forcibly preempted. Bound trusted
workers separately; the provided subprocess timeout stops the direct child, not
necessarily its descendants.

Before/after input counts are taken from the prompts actually constructed at the
controller boundary. Supply `token_counter(text, model)` for local tokenizer-backed
text counts. Otherwise they are **labelled UTF-8-bytes/4 estimates**, not billing
counts. Auxiliary input/output overhead is reported separately; gross prompt
compression is not a claim of end-to-end cost savings or better answer quality.

Traces/checkpoints contain full visible notes and task data. They are private
runtime artifacts and excluded by the release allowlist. The archive has a byte
cap and stops rather than silently evicting evidence when full.

## Mathematics, attribution, and publication

The recurrence remains `z <- F(x,y,z)` repeated `n` times, followed by
`y <- G(x,y,z)`, with defaults `n=6`, `T=3`. Compression changes the *view* of `z`
that enters a model, not the archived source. [Mathematics](references/mathematics.md)
and [memory/progress design](references/memory-and-progress.md) specify the limits.

The four original Lean/Mathlib project artifacts remain byte-identical. The
optional Python adapters require reviewed, explicitly trusted execution; tests
use a mocked compiler, not an actual Lean build. No neural performance result
from either cited research paper is inherited by this implementation.

[Testing](TESTING.md) records executed checks. [Publishing](PUBLISHING.md) describes
the create-only helper targeting `eidolonofficial/recursion-reiteration-engine` with private
visibility by default. MIT, retaining original source attribution.
