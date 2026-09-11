# Verification: v0.7.0 worker actions

455 tests passed on Windows Python 3.14.4 after the worker change: the inherited
432 methods plus 19 worker-contract methods and four finite-selection methods.
The source remained dependency-free. Final checkout/build/publication checks are
recorded in the release receipt. No Linux or Lean/Mathlib run is claimed here.

The full-suite first pass exposed two intentionally changed expectations (zero
note calls are now supported; an unavailable checker does not fall back to model
approval), and four original Lean files converted by the new Windows checkout.
Those exact source files were restored, not edited. The previous published tree,
original symbolic worktree, and license text were preserved.

The same installed Gemma 3 4B Q4_K_M was rerun on the same twelve-project task,
with 8192 context tokens and one prediction slot. The new worker made two fresh
calls, reporting 1,977 total backend tokens. Both outputs were malformed typed
replies (Markdown fences, and incorrect candidate formatting); neither was repaired
or admitted. The controller stopped with `repeated-rejection`, zero note calls,
empty working notes and no accepted answer. No reference solution or target value
was supplied to the model. CLI ANSI and outer whitespace were removed only.

The old ladder used ten calls and 13,365 backend tokens, but both trials failed.
This comparison demonstrates the bounded failure path, NOT better solve quality,
successful-task token savings or a controlled latency benchmark. The fixed Python
checker separately enumerated all 4,096 selections, found 99 feasible cases, and
confirmed optimum 67. That optimum is host computation, not a model discovery.
The CLI uses its existing sampling defaults; per-request temperature and output
limits are not enforced by this particular local test adapter.

---

# Historical verification: v0.6.1

## Current qualification

During final publication, main advanced to the exact recovered parent `8f98660`.
Its v0.6.0 release is preserved; these additional fixes are released as v0.6.1.
No existing tag, release asset or Git history is replaced.

The implementation recovered at the start was `8f98660`, descended from the
published `690fcbe`. Its 398 tests passed again before changes. After packet,
consolidation-queue and quality-report hardening, **409 tests passed without skips**
on Windows Python 3.14.4. All six executable examples passed. An offline wheel
built without downloading runtime dependencies. Final fresh-clone, installation,
manifest and publication checks are recorded in the release verification receipt.

The 11 added regression methods cover whole-summary controller windows, bounded
writer head selection, oversized accepted interactions, non-consuming consolidation
overflow, stale queue pointers, current-head reservations, irrelevant tool discovery,
matched quality regressions, unknown timeout output and non-statistical gate scope.
The full suite covers principal isolation, durable versions/sources, dependency
invalidation, concurrent writes, model authority forgery, exact search authorization,
scoped receipt invalidation, controller budgets and paired answer/notes rollback.

The private-memory example retains an exact **27,000-character** successful tool
log while rendering a **595-character** observation view. This is a constructed
view-level measurement, not total model-token savings. Its controller used four
calls to a deterministic worker. The tiny efficiency example actually expands
input from 876 to 1,213 estimated units; compression is not universally beneficial.
The workspace example preserved its full history with 864,926 reference input
characters versus 330,485 transmitted characters. These examples are not neural
quality studies and their savings must not be added together.

A 100-record admission regression verifies unchanged history and finite coverage;
it does not rerun the external P-versus-NP experiments or prove a complexity claim.

## Fresh local neural smoke test: failed quality screen

Eight fresh generations ran through the already-installed local Ollama CLI using
`llama3.2:latest`, model ID `a80c4f17acd5` (3.2B Q4_K_M). Model identity was checked
before and after each completed call; no weights were downloaded. The local CLI
used its existing sampling defaults, not a claimed seeded or temperature-controlled
study. No hosted inference API was used.

Four constructed tasks asked about the saved P-versus-NP progress record:
NO_CERTIFICATE versus UNSAT, the codimension minimum for independent clauses,
the failed promotion gate, and the unresolved universal target. Full-context arms
included repetitive unrelated completed-task text; reduced arms retained the exact
relevant statement. The answer checker required exact typed JSON results.

Both arms scored 3/4, but this does **not** establish quality preservation. On the
codimension task, reduced context returned 2 instead of 3 while full context was
correct. On another task, the full arm timed out at 90 seconds. The paired screen
therefore fails: one regression and one incomplete attempt. No compression policy
or solver champion was promoted on these results. This is not a representative
held-out benchmark, a new SAT run, or a formal proof.

The accounting retains the timed-out attempt and marks its generated output and
native token usage unknown. Returned full-arm calls reported 1,963 prompt tokens
and 21 output tokens (three calls); reduced calls reported 366 and 26 (four calls).
Those are unequal observed subsets, **not** comparable complete cost totals. The
initial diagnostic receipt failed to align counts after the timeout; its retained
correction binds every returned output to its exact response hash. No percentage
of neural token/cost savings is claimed. `quality_eval.evaluate` now exposes matched
regressions, incomplete attempts, and accounting completeness explicitly.

Trained LightMem components, vector/shared-graph memory, learned-compressor quality,
recursive child-agent orchestration, KV-cache performance and Lean/Mathlib builds
were not reproduced. The pipeline separates private retrieval, selection, writing
and host-reviewed consolidation; its no-model fallback is deterministic lexical
retrieval and exact accepted deltas. License/provenance remain outside prompts.

```sh
PYTHONPATH=src python -B -S -m unittest discover -s tests -v
PYTHONPATH=src python -B -S examples/private_memory_demo.py
```

---

# Historical verification: v0.5.0

## Executed scope

The suite has 303 unittest methods: the 271 release methods plus 32 efficiency
methods. Linux Python 3.13.5 and Windows Python 3.14.4 passed without skips.
Checks cover compact serialization, exact Unicode ranges, transactional batched
retrieval, forged/stale tickets, unseen edits, mandatory dependencies, progress
rollback, actual subprocess execution, local carry-forward, and judgment-cache
invalidation. Multiple independent votes and parse retries are never cached.

Windows qualification found a default-codepage read in the source-inspection
transport test. It now explicitly reads UTF-8. The earlier failed-constructor
SQLite handle leak is fixed by closing the connection before re-raising, not by
suppressing cleanup or audit errors. The historical replay reader also uses UTF-8.
Manifest generation writes deterministic UTF-8/LF bytes on both platforms.

## Actual tokenizer comparison

A constructed 100-rung source-audit fixture is generated from commit
`8654c7a772c015a867b0804b352f4c09bf10fe3a`. It archives existing reference text
and adds one file/syntax identity per stage. It is not a fresh research run, a
neural-model test, or a SAT benchmark. Its 123 locks check identity preservation.

Fixture JSON SHA-256:
`1e4f384309ed709e5ece76fd14d8ebce64350e9eafd0290894148fd914b51d3e`.
All three arms reconstruct final SHA-256:
`b9e6bfb5b84d598e4d088335ff3b3df20413d6576351129bf07ba497ecb880e8`.

Measured with tiktoken 0.13.0 on Windows, using cached public vocabularies:

| Visible-text tokenizer | Workspace-v1 input | Compact-v2 input | Efficient-v2 input | Reduction from v1 |
|---|---:|---:|---:|---:|
| cl100k_base | 3,443,515 | 2,328,748 | 2,176,115 | 36.81% |
| o200k_base | 3,445,097 | 2,329,918 | 2,176,997 | 36.81% |

Efficient mode reduced non-judge input by 73.25% and 73.28%, respectively.
Calls were 549, 592 and 499. Fewer selected optional excerpts increased retrieval:
48 read exchanges in v1 versus 98 in efficient mode, which returned 118 ranges.
Removing 100 separate selection calls more than offset those extra reads here.
Compact serialization alone is not responsible for the entire reduction.

All 101 full judge requests were identical across arms. Their token totals were
1,713,320 and 1,714,666 respectively. No judgment-cache hits occurred because
candidates changed. The cache was validated separately, not credited for savings.

SKILL.md shrank from 870 to 514 cl100k tokens; AGENTS.md from 835 to 465;
README.md from 3,054 to 1,412. These static file reductions are not added to the
runtime totals; the controller does not automatically send these files.

These counts tokenize system and user text separately plus actual response text.
They exclude chat framing, tool schemas, hidden reasoning and provider discounts.
The supplied worker emits predetermined changes, not responses inferred from
reduced context. No quality equivalence, latency, billing, universal tokenizer
coverage, or optimal compression guarantee is established. A fresh-model study
is needed to assess reasoning quality and retrieval behavior.

## Separate historical character replay

The earlier P-versus-NP 100-tier response fixture was replayed locally with an
exact character counter. Workspace-v1, compact-v2 and efficient-v2 used
11,647,436, 11,184,712 and 10,814,035 input characters, respectively. Their call
counts were 703, 601 and 501. Final recorded research bytes and 123 identities
matched. These are different content and budget units from the tokenizer test;
their percentages must not be mixed. Mathematical experiments were not rerun.
The historical corpus is external and is not part of the release.

## Reproduction

```sh
PYTHONPATH=src python -B -S -m unittest discover -s tests -v
python -B -S examples/efficiency_demo.py
python -B -S benchmarks/make_source_fixture.py --out /tmp/source-fixture.json.gz
python -B benchmarks/efficiency_replay.py /tmp/source-fixture.json.gz \
  --encoding cl100k_base --out /tmp/cl100k-result.json
```

The fixture builder requires a Git checkout with the pinned base commit, or an
extracted base snapshot with `--source PATH --revision ''`. The optional tokenizer
must already be installed and its rank files cached; the benchmark refuses network
loads. The runtime has no tokenizer dependency and accepts a trusted local counter.
The release receipt records manifest checks, fresh-extraction tests and offline
wheel build/isolated installation. No Lean/Mathlib build or live upstream
compression-library benchmark was run. LICENSE is unchanged. Provenance remains
outside hot instructions and is not included in runtime savings.
