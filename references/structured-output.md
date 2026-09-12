# Schema-constrained generation

`RecurseConfig.structured(schema, ...)` requires generation-time schema support.
The supplied client must implement `check_schema(model, schema) -> True` and
`complete(..., response_schema=schema)`. A legacy client is rejected before any
inference when this mode is requested. Plain calls and older transports remain
available; no silent downgrade or output repair is performed.

The included optional `LMStudioClient(port=1234)` connects only to `127.0.0.1`.
The operator must first start a local LM Studio server and load the exact model.
This adapter checks that the named model is already loaded with the GGUF backend,
then sends `response_format.type=json_schema`, temperature and output limits to
`/v1/chat/completions`. It does not load models, install packages, use hosted
inference, follow HTTP redirects or use environment proxies. This is a local API,
not literally API-free. The core still has zero runtime package dependencies.

Payload mode generates only the task result, such as `{"selected":["A"]}`.
Python retains the original candidate, request ticket and source bindings. The
whole candidate must be visible before whole replacement; stale responses and
changed schemas are rejected. Without a payload schema, structured action mode
keeps block selection and constrains it to the actual offered handles. Existing
archive reads, source authorization and complete-candidate checks remain in force.

The supported schema subset is explicit: closed objects, homogeneous arrays,
scalar types and enums, size/numeric bounds, and bounded `anyOf` alternatives.
Unknown keywords, references, regex patterns and `uniqueItems` fail preflight.
The host separately checks duplicates and task rules. A valid grammar result is
not proof of feasibility, correctness or optimality. Custom adapters are trusted
code and must actually enforce the schema; returning True is not attestation.

Format errors and truncated/refused/cancelled generations consume completion and
wall-time budgets but not candidate reasoning steps. Repeated failures still stop
the run. Raw text is archived before acceptance, with no fence stripping. Native
usage is recorded when reported; missing usage is unknown, not zero.

Optional `objective` and `candidate_identity` are versioned, host-owned callbacks.
An objective requires explicit feasibility guards and a separate sufficient final
validator. It preserves the best checked feasible candidate without calling it
optimal or turning an objective score into a probability. Resume recomputes the
objective. Domain-specific identity may sort a selection set; the engine never
sorts arbitrary arrays. Feedback remains separate from model-authored notes.

Examples (no model download or implicit activation):

```sh
# Requires the named model and localhost service already running.
reiterate --lmstudio-port 1234 --ladder loaded-model-id --response-schema schema.json \
  --max-tokens 128 --temperature 0 --profile research --rungs 6 "Your task"

# The fixed test with an explicitly supplied local model:
PYTHONPATH=src python examples/structured_selection.py --model loaded-model-id

# Existing finite solver; zero model generations:
PYTHONPATH=src python examples/structured_selection.py --exact
```

The tests in TESTING.md distinguish syntax, feasibility and optimality. LightMem,
compression and symbolic-map algorithms are not modified by this output layer.
