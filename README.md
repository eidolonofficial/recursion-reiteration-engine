# Recursion Reiteration Engine

**Working memory and checked iteration for AI models.**

RRE is a lightweight Python controller for tasks that take more than one model call. It keeps the current answer, brings in relevant context, asks the model for a revision, and runs your checks before carrying progress into the next step.

Use it for coding, analysis, and research workflows where an agent needs to revise its work without repeatedly loading the whole history. You supply the model and the checks. RRE handles context, memory, feedback, checkpoints, and stopping rules.

## How it works

```text
Retrieve context -> Propose a change -> Check it -> Keep or roll back -> Repeat
```

The model proposes work; Python manages the state around it. RRE retains the best eligible answer and its paired notes, returns feedback on failed revisions, and stops when the task is validated, progress stalls, or a configured limit is reached.

## What it handles

- **Compact context.** Keep exact source material in an archive, send relevant excerpts, and apply targeted edits instead of rewriting the entire answer. Routine tool output can stay archived rather than following every prompt.
- **Checked progress.** Use your tests, validators, and milestone checks to decide which revisions to keep. Rejected changes roll back the answer and its notes together.
- **Persistent memory.** Store user- and project-scoped records in SQLite, with sources and version history. Track pending writes separately from committed records and retrieve earlier evidence when needed.
- **Structured output.** Request one typed action or a task-specific JSON result. With a compatible backend, the response schema is enforced during generation; Python checks the result afterward.
- **Bounded, resumable runs.** Set context, call, and time limits. Repeat one model or define a ladder of model tiers. Checkpoints retain accepted work and consumed budgets across restarts.
- **Symbolic solve maps.** View retrieved memory records, their prerequisites, and their sources as compact JSON or ASCII without creating a second memory store.

## Get started

Requires **Python 3.10+**. The core has **no runtime package dependencies**.

```sh
git clone https://github.com/eidolonofficial/recursion-reiteration-engine.git
cd recursion-reiteration-engine
python -m pip install .
python examples/workspace_demo.py
```

The demo uses a scripted worker to show the context-and-edit loop without loading a model.

### Try an installed local model

Load a model in LM Studio and start its local server, then run:

```sh
python examples/structured_selection.py --model YOUR_LOADED_MODEL_ID
```

Replace `YOUR_LOADED_MODEL_ID` with the exact identifier of the loaded model. This example asks it to choose projects under resource limits and prerequisites, checks its proposals in Python, and returns feedback for another attempt.

### Connect your own workflow

The Python entry point is `recurse(task, client=..., config=...)`. Use `RecurseConfig.simple(...)` for one proposal per step, or `RecurseConfig.structured(schema, ...)` for schema-bound results. Supply a `validator`, `feedback`, and optional `progress_checks` for your task.

Connect a Python callable, a subprocess worker, or manual responses. The included LM Studio adapter supports local models; other local or frontier models can use the same controller through a compatible adapter. Schema-constrained mode requires generation-time schema support.

Start with the [local worker example](examples/local_worker.py) or the [structured-output guide](references/structured-output.md). Agent instructions live in [SKILL.md](SKILL.md).

## Context and token use

RRE keeps the archive separate from the working prompt. Excerpts, delta edits, short source handles, local progress carry-forward, and reusable identical checks reduce repeated material. Calls, retries, and retrievals are recorded in the run trace. Supply your model's tokenizer for measured input budgets.

Memory is optional. The built-in search uses lexical matching; model-assisted query planning, selection, writing, and consolidation can be enabled separately. Use only the parts your task needs.

## Documentation

| Topic | Guide |
|---|---|
| Context budgets, excerpts, and edits | [Efficiency](references/efficiency.md) and [workspace](references/workspace.md) |
| Persistent memory and solve maps | [Private memory](references/private-memory.md) |
| Model connections and response formats | [Structured output](references/structured-output.md) and [worker actions](references/worker-actions.md) |
| Validators, milestones, and experiments | [Verification](references/verification.md) and [folding](references/folding.md) |
| Test results and benchmark scope | [TESTING.md](TESTING.md) |

After installation, run the suite with `python -m unittest discover -s tests -v`.

[MIT license](LICENSE) | [Project history](PROVENANCE.md) | [Releases](https://github.com/eidolonofficial/recursion-reiteration-engine/releases)
