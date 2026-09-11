---
name: recursive-reiteration-engine
description: Refine candidates through bounded working context, progress-preserving iteration, and externally verified experiments. Use for local model-neutral research, checked revisions, and evidence-gated promotion without a hosted inference service.
---

# Recursive Reiteration Engine

Use this protocol when a task benefits from iterative correction rather than a
single attempt. It can run inside the current host conversation or through the
local Python controller. It does not need a hosted inference service.

First identify the requested result, constraints, and the available check. Keep
three explicit pieces of task state: the problem, the candidate answer, and short
visible working notes describing evidence, unresolved issues, and the next useful
correction. Do not request or expose hidden reasoning.

For each improvement step, update the visible notes n times, then revise the
candidate once. Defaults are n=6 and T=3 steps for an operator-selected tier.
Test the exact candidate against a sufficient trusted check when available.
Otherwise use the strict judge JSON contract documented in README.md; label the
score heuristic. Multiple votes use a median, not an independence claim.

A repeated candidate indicates a stalled tier, not correctness. Carry the strongest
eligible candidate and its paired notes to the next tier only when a tier exists
and budget remains. Do not assume a model's name encodes price or capability.

Keep empty, truncated, or errored outputs out of accepted state. Preserve math
symbols and case. Never promote a necessary-constraint gate into a proof. Mark
judge-only, statistical, provisional, and unverified partial outcomes for review.

Prefer explicit local checks, an already-loaded local model, or manual exchange.
Do not infer credentials, activate remote services, install dependencies, or execute
a newly generated checker without explicit operator review. The lean/ directory
is an optional preserved project; its toolchain is not bundled.

The skill and distribution are named `recursive-reiteration-engine`. The Python
namespace `headroom_recursion` is retained for existing integrations.
For runnable examples and tested interfaces, read README.md and TESTING.md.

## Progress-preserving continuation

Before entering a tier with prior progress, score/check the supplied incumbent and
prepare a bounded checkpoint from existing source records. Treat a suggested next
check as advisory. The controller, not the model, owns completion status, locked
obligations, the model schedule and all budgets.

Compress the visible scratchpad and retrieved prose before their next use, keeping
exact originals separate. Put critical statements in explicit verbatim blocks or
operator pins. Retrieve an offered archive range when missing detail is needed.
Do not change candidate answers or mathematical evidence to meet a token target.

Use the runnable controller for enforcement. Following this skill as prose alone
does not implement rollback, mechanical checks, exact accounting or resumable state.


## Bounded-workspace sessions (v0.3)

When the input packet declares `workspace-v1`, use exact offered excerpts as
reference data. Do not pretend to have reviewed omitted history. Request missing
source ranges when necessary. For an answer update, return a `workspace_patch`
with the packet's scope, ticket and base and sorted non-overlapping offset edits.
Never replace the complete incumbent with a shorter summary. The controller
reconstructs the proposal and applies all progress checks; a model cannot mark
its own change verified. Full-judge prompts are not workspace summaries.
See `references/workspace.md` for the complete protocol.

## Optional folding workflow

Use the local `headroom_recursion.folding` layer when proposals must survive an
external experiment ladder. Review `references/folding.md` before wiring a worker.
The worker proposes; the trusted evaluator checks; only the controller promotes.
Keep a frozen champion, one declared mechanism, exact artifacts and resource
limits. Do not reuse consumed confirmation material or regenerate proposals after
confirmation starts. Keep failures scoped to the tested implementation, retaining
passed components in bounded advisory summaries.

For research, use `ResearchBridge` and distinguish finite computations from formal
proofs. A scored prose answer, compressed note or empirical improvement must never
be promoted into a general theorem. This optional workflow does not require a
hosted API, a particular model provider, or an external corpus.
