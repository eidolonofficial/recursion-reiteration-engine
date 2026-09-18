# v0.8.1: audited request, memory and evaluation repairs

Payload-only requests restore the exact full candidate in the final candidate
source, after typed rendering removes its block representation. Visibility and
budget are checked on that serialized request. Format retries refresh feedback
before another generation. Both attempts remain metered; malformed output is
never repaired, accepted or stored as a working note.

Exact observations have one canonical working-context representation. A duplicate
feedback body becomes a reference only when it uniquely identifies one observation.
Identical output from different revisions remains unbound rather than falsely
attributed. Full judge pins and the original archive remain exact and unchanged.

Memory query models are skipped for empty scoped stores. Hosts may explicitly use
`session.retrieve(query, plan_queries=False)` for a complete lookup. An empty
model-generated tag filter result may fall back without those generated tags,
never without its principal or date bounds. The ranker remains lexical.

## Acknowledged is not committed

`write_turn` retains its tuple-of-entry-IDs return contract. `session.last_write`
additionally reports a durable, source-bound receipt. Empty, rejected, interrupted
or oversized writer attempts stay `pending`; successful transactional writes are
`committed`. Committed means indexed, not proven true. Historical versions remain.
The store retains bounded pending receipts in the same private SQLite database;
capacity pressure raises an explicit error rather than evicting exact evidence.

`session.retry_write(receipt_id, send=...)` performs one host-requested attempt.
It offers bounded whole current heads before inference and retains compare-and-swap
version checks. There is no hidden retry loop, automatic authority promotion or
cross-user lookup. An identical committed write does not call the writer again.

A bounded pending-update view exposes matching exact user messages separately
from indexed summaries. Thus an older summary cannot masquerade as a reconciled
current policy merely because a writer failed. The view is advisory, not a new
source of proof. It observes the existing packet limit and retains source IDs.
This raw-evidence fallback extends this engine; it is not a reproduction of the
LightMem paper's trained writing model or graph/vector retrieval implementation.

The changed request contract and memory identity intentionally reject old-policy
checkpoints. Resume v0.8.0 checkpoints with v0.8.0, or start a newly reviewed run;
relabeling the old checkpoint would bypass its policy binding.

## Evaluation boundaries

`benchmarks/paired_pilot` separates bounded program stdout/stderr from grading
JSON. A useful regression must pass correct code and assert against the original
bug. Recovery requires an accepted milestone, two different processes, exact
restored state, consumed budgets and further correct work. The scripted preflight
exercises real process boundaries but is not a neural task result.

The pilot uses the same local model, tests, schema and 2,400-token candidate output
allowance for both arms. It explicitly dispatches the installed skill on the host,
without paying a model call to choose an already-requested tool. Coding uses no
query, selector or writer model; the memory task opts into a writer and at most one
explicit retry per interaction. Recall and arithmetic application are separate.
A token admission ceiling is not a guaranteed final consumption cap: an admitted
call can cross it. Unknown usage stops further calls and is never measured zero.

Start with `suite.py --repo REVIEWED_CLEAN_CHECKOUT --out NEW_DIRECTORY --rounds 1
--tasks coding`. The selected local model must already be loaded. The harness does
not start inference services, download weights or claim native skill discovery.
All exposed pilot fixtures are development examples, not pristine holdouts.
