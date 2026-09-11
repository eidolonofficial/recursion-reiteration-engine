# Verification: v0.6.0

## Current qualification

Executed on Windows Python 3.14.4: **398 tests passed without skips**. All six
examples passed: private memory, efficiency, workspace, progress memory, rational
refinement and folding. The private-memory example retained its exact 27,000-
character successful tool log while rendering a 595-character observation view.
That is a constructed observation-view measurement, not a total-token or neural
quality claim. The controller made four completion calls to its deterministic
worker; no memory model was configured.

Run the complete unittest suite and `examples/private_memory_demo.py` from the
reviewed tree. The private-memory tests cover scope isolation, source durability,
version conflicts, atomic rollback, pinned constraints, dependency invalidation,
role-output forgery, concurrent writer updates, bounded exact deltas, private
consolidation approval and Windows database cleanup. Context-mechanism tests cover
literal search pagination and edit authorization, immutable scoped receipts,
checker mutation, whole-candidate judging, private-store checkpoint binding,
shared call budgets, exact tool schemas and failure-inclusive paired evaluation.
A constructed 100-record admission test checks preservation and finite coverage;
it does not rerun the external P-versus-NP experiments or establish a new proof.

The release receipt records the executed test count and environment, example
runs, fresh-checkout qualification, manifest checks and private publication state.
Tests use deterministic workers. No fresh neural-model comparison, trained memory
model, learned-compressor trial, hidden subagent benchmark, KV-cache performance
study or Lean/Mathlib rebuild is claimed for this release. Test callbacks are not
representative held-out task evaluation. Every reported character count is labelled
as such; historical tokenizer savings below belong to v0.5, not v0.6.

```sh
PYTHONPATH=src python -B -S -m unittest discover -s tests -v
PYTHONPATH=src python -B -S examples/private_memory_demo.py
python -B -S scripts/publish.py
```

A manifest mismatch after an intentional code edit is expected until the reviewed
allowlist is regenerated. Unknown mismatches must be investigated, not suppressed.
The publisher's create-only mode is not used to update the existing private repo.

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
