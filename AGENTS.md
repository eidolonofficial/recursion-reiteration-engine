# Recursive Reiteration Engine: instructions for coding agents

This project is model-neutral. Use the execution environment supplied by the
operator; do not infer a provider, select a remote service, or download a model.
This file is applicable to any coding agent and does not supersede its own rules.

## Core invariants

Keep the recurrence explicit: n visible-note updates, one answer update, then
verification. Model identifiers are opaque. A tier order is the operator's choice.
Never equate a judge score with mathematical proof or a calibrated probability.
Only an explicitly trusted sufficient check can emit a validated halt. A gate
pass is insufficient. Statistical/provisional results require human review.

Do not strip case, multiplication, subscripts, or meaningful whitespace from
mathematical candidates. Empty/truncated updates must not destroy prior state.
Every attempted completion, including failures and judge retries, consumes the
call budget. Carry the chosen candidate with the notes and model that produced it.

Subprocess prompts must remain data on stdin; use literal argv and shell=False.
Local callbacks, workers, and proof compilers are trusted code, not sandboxes.
Do not silently enable automatic execution of generated checkers or proof text.
Do not add an inference networking dependency or implicit model download.

## Verification

Run `PYTHONPATH=src python -S -m unittest discover -s tests -v`.
Run `PYTHONPATH=src python -S examples/rational_refinement.py`.
Use visible, concise working notes; never require private hidden reasoning.
Record which tests actually ran. Do not describe mocked Lean tests as real proofs
or deterministic arithmetic examples as neural model evaluations.

Keep source attribution and mathematical references. Exclude local data, weights,
credentials, runtime traces, and inherited source history from releases. After any
intentional export-file edit, regenerate EXPORT_MANIFEST.json using the documented
command; the publish helper must fail closed on a digest mismatch.

## Compression and progress contracts

Keep original evidence separate from compressed views. Compression belongs at the
controller boundary, not in an ignored backend flag. Preserve exact task/answer
bytes, explicit pins, and protected mathematical blocks. Never claim a lossy view
is a semantic equivalent because a source hash exists. Count markers and replay
costs; expose overflow and fallback. Test actual worker input.

Models select source ids for checkpoints; they cannot set verification state,
change the ladder, or expand budgets. Locked check regressions and checker errors
fail closed. Roll back both answer and notes on a rejected revision. Regrade
resumed incumbents; never trust serialized model scores. Keep cumulative budgets
and scope/policy bindings. Do not turn a prose instruction into a claimed guarantee.

Also run `PYTHONPATH=src python -S examples/progress_memory.py`. Upstream Headroom
fixtures do not constitute a live third-party integration test. Do not import or
redistribute the supplied research PDF or private runtime archives in the export.

## Folding governance (v0.4)

Never expose a Folding/Store handle or unrestricted private artifact lookup to a
worker. Freeze artifact and policy identities before tests. Confirmation outcomes
close the proposal family; crashes consume holdout access, and rollback cannot
restore it. A model cannot supply its own promotion receipt or proof verifier.

Maintain separate empirical, finite and formal evidence classes. Formal verifier
registrations are trusted operator code; no proof kernel ships here. The research
bridge disallows model-judge halts, even on score 1. Preserve exact historical
bytes without claiming they are formally proved. Compare math outcomes and
resource accounting independently of prompt size; no replay is a neural benchmark.
Run the folding example and all folding adversarial tests after authority edits.

## Release identity

Keep `recursive-reiteration-engine` as the skill and distribution name. The
repository is `eidolonofficial/recursion-reiteration-engine`. Preserve the
`headroom_recursion` Python namespace and `recurse` entry point
for compatibility; `reiterate` is the preferred command. Do not rename an upstream
repository or import its history when preparing the standalone release.
