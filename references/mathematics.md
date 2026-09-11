# Mathematical structure and limits

## State and recurrence

Let x denote the fixed problem, y_t a candidate answer, and z_t concise, visible
working notes. For tier j, the operator supplies local functions F_j and G_j through
a completion adapter. For one improvement step:

\[
z_{t,0} = z_t,\qquad
z_{t,i+1} = F_j(x,y_t,z_{t,i}),\quad 0\leq i<n,
\]
\[
y_{t+1} = G_j(x,y_t,z_{t,n}),\qquad z_{t+1}=z_{t,n}.
\]

An empty or explicitly truncated output is not installed. A completion error leaves
previous accepted state recoverable. The default is n=6 and at most T=3 improvement
steps per tier. Nothing requires F and G to be neural networks: the included exact
arithmetic example is a deterministic construction.

The retained structure is inspired by Alexia Jolicoeur-Martineau, *Less is More:
Recursive Reasoning with Tiny Networks* (2025), arXiv:2510.04871:
https://arxiv.org/abs/2510.04871

This package does not implement the paper's learned latent space, training loss,
backpropagation scheme, or parameterization. Its text-state correspondence is an
engineering analogy, not a transfer of the paper's empirical findings.

## Heuristic judgment

For m judge outputs with accepted finite scores h_1,...,h_m in [0,1], use

\[
h_t=\operatorname{median}(h_1,\ldots,h_m).
\]

With an even number of votes the median is the average of the middle two. Each
malformed vote receives at most one retry; a still-invalid vote contributes zero.
The parse contract is a complete JSON object, not a number extracted from prose.

A judge-only halt occurs when h_t >= tau, where 0 < tau <= 1. Scores are heuristics:
repeated calls can be correlated, confident judgments can be wrong, and median
aggregation does not make them statistically independent or formally sound.

## Trusted checks and constraint gates

A sufficient, operator-reviewed check V(y)=true may stop as `validated` only to the
extent its declared contract establishes the requested result. A check with a
statistical confidence field or future settlement date still needs human review.
Supplying a check and setting confidence to one does not make it correct by fiat.

A gate encodes necessary conditions. Its rejection excludes the candidate from
best-answer selection and skips the judge for that step. Its pass is not sufficient
for correctness and therefore delegates to the judge. A checker exception records
that no check occurred; it is not silently interpreted as a pass or a disproof.

In sufficient-check mode, a false result does not itself forbid judge-only stopping.
It is inconclusive under this controller's contract. A caller requiring a hard
necessary constraint must use gate mode. Judge-only stopping remains distinct from
`validated` and is always flagged for review.

## Stopping, handoff, and budgets

A repeated eligible answer is a cycle signal and can end a tier without asserting
correctness. Normalization changes line endings and exterior whitespace only;
case, operators, subscripts, and internal whitespace are retained.

Eligible scored candidates are ranked by h_t; ties prefer the latest candidate.
This preserves the strongest *scored* answer, not a theorem that the answer is
objectively strongest. Tier handoff keeps its paired visible notes. If no scored
candidate exists, partial state is available but unverified.

For tiers with T_j steps and m judge votes, the nominal call schedule is

\[
C_{\mathrm{nominal}}=\sum_j T_j(n+1+m).
\]

Allowing one parse retry for every judge vote gives the upper schedule bound

\[
C_{\mathrm{retry}}=\sum_j T_j(n+1+2m).
\]

These bounds concern controller completion calls. Early halting and sufficient
checks can reduce usage. Every attempted completion counts against an explicit cap,
including a failure. Calls made internally by user hooks or worker processes are
outside this counter. A wall-clock deadline is cooperative, not a preemptive CPU
or operating-system resource limit.

## Exact rational example

Starting at q_0=1, the demo performs

\[
q_{k+1}=\frac{q_k+2/q_k}{2}
\]

using Python's exact `Fraction` arithmetic. For positive q_k, define e_k=q_k^2-2.
Direct algebra gives

\[
e_{k+1}=\frac{e_k^2}{4q_k^2}.
\]

This explains how the squared residual decreases in the example; the actual halt
is authorized by checking q>0 and |q^2-2|<10^{-12} as exact rational inequalities.
This is not the assertion q=sqrt(2), and it does not demonstrate that an arbitrary
language model can discover or verify the recurrence.

Python's standard-library Fraction documentation:
https://docs.python.org/3/library/fractions.html

## Compression and committed progress (0.2)

The model consumes a view `z_hat = C(z)` where protected spans remain exact and
other prose may be selected or shortened. The raw `z` is archived independently;
`C` is not asserted to preserve semantic equivalence. Compression does not modify
the exact problem or candidate. The recurrence is now evaluated on these bounded
views, so neural performance cannot be inferred from the uncompressed recurrence.

For an incumbent `(y_star, z_star, q_star)` and locked predicates `L`, a revision
is committed only when all locked/required predicates still pass and its valid
common-judge score `q >= q_star`, or an adequate sufficient validator succeeds.
A lock is evidence only for the supplied predicate. This state-machine invariant
is enforceable; improvement in unverified semantic quality is not guaranteed.
