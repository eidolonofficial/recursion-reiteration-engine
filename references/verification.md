# Verification and execution boundaries

## A check is only as strong as its contract

`RecurseConfig.validator` accepts a reviewed callable returning exactly a bool or
`Verdict`. A string, nonzero number, or arbitrary truthy object is not accepted.
`oracle_sufficient=True` means that a passing result is sufficient for this task;
it is an operator assertion about coverage, not a property inferred from code.
Use `oracle_sufficient=False` for a necessary-constraint gate.

The controller never claims a model's vote is a proof. All judge-only results,
statistical validations, provisional validations, and incomplete outcomes are
marked `needs_human_review`. A confidence field does not establish calibration.
A local corpus match supports reference lookup, not mathematical truth or novelty.

## Lean is optional trusted execution

The original project files pin Lean 4.31.0 and Mathlib's corresponding manifest.
Their contents are retained, not downloaded or built during normal execution.
An installed toolchain with cached dependencies is necessary for offline use.
Neither the Python harness nor its normal installation provisions it.

Once a reviewed toolchain is present, the preserved smoke theorem can be checked
from `lean/` using `lake env lean LeanOracle/Smoke.lean`. This command was not run
for this package. Toolchain installers and package acquisition are outside the
controller and may require separate network access during setup.

`make_gate_oracle` checks complete Lean blocks for compilation but does not confirm
that their statements correspond to the user's problem. A pass remains a gate pass.
`make_decider_oracle` uses a trusted skeleton with one `sorry` line and a target marker. A complete minimal
skeleton, without external imports, is:

```lean
-- LEAN-ORACLE-TARGET: local_demo
theorem local_demo : 2 + 2 = 4 :=
  sorry
```

Supply a single fenced proof expression such as `by decide`. The adapter inserts
that expression into the skeleton, compiles, and requests an axiom audit for the
pinned declaration. Its allowlist is `{propext, Classical.choice, Quot.sound}`.
Missing, duplicate, or non-allowlisted audit records fail the audit.

Both factories require `trusted_execution=True`. Keep the returned `sufficient`
flag when wiring an adapter; never turn a gate into a sufficient check:

```python
from headroom_recursion import RecurseConfig
from headroom_recursion.lean_oracle import make_decider_oracle

oracle = make_decider_oracle("reviewed_statement.lean", trusted_execution=True)
config = RecurseConfig(validator=oracle.validator, feedback=oracle.feedback,
                       oracle_sufficient=oracle.sufficient,
                       oracle_note=oracle.note, oracle_rung=oracle.rung)
```

The skeleton, proof text, compiler, imported tactics, and execution environment
must be reviewed and trusted. Lean elaboration can execute code. Text screens are
not a sandbox; compiler stdout is not an authenticated certificate. A compromised
worker or malicious elaborator can defeat these assumptions. The current adapter
is not suitable as a security boundary for arbitrary adversarial generated proofs.

The Python tests exercise these adapters with a mocked compiler. They establish
Python-side routing, splicing, and parse behavior only. They do not establish a
kernel-checked proof, compiler compatibility, or security against hostile Lean.

## Local transports are not sandboxes

The bundled runtime contains no inference network transport. A supplied callback,
worker, or retriever can still access files and networks using its own code.
Use an isolated environment with OS-level restrictions when necessary.

Subprocess arguments are fixed by the operator and prompts go through stdin.
The output limit is checked after capture, not enforced as a streaming memory
quota. A timeout bounds the direct call but does not guarantee removal of all
process descendants. In-process callbacks cannot be forcibly interrupted by the
controller's cooperative deadline.

## Evidence handling

Traces retain full visible task state and may be sensitive. Write them explicitly
to a private directory, not into a release. Trace files are created exclusively
instead of overwriting an existing path. The publish helper copies only files
listed and hash-verified in the export manifest; it does not import arbitrary
untracked files, local runs, or the original Git object database.
