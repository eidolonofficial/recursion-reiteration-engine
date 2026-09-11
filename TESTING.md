# Verification: v0.5.0

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
