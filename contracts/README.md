# Contracts

## Source of truth

The normative data contracts are the **pydantic models in
[`src/bionexus/core/contracts/`](../src/bionexus/core/contracts/)**. They are
validated by the test suite on every commit and evolve per the rules in
[`docs/stability.md`](../docs/stability.md): additive fields only within a
major version; consumers must ignore unknown fields.

## Archived OpenAPI drafts

[`archived-openapi/`](archived-openapi/) contains the original pre-implementation
OpenAPI 3.1 drafts (v1, 2026-08). They are **superseded and no longer
maintained** — they drifted from the implementation during development (e.g.
counterscreen assays, hypothesis artifacts, and the QC `z_prime` field were all
added in code first). Keep them for historical/design reference only; do not
generate clients from them.

If machine-readable schemas are needed for cross-organization work, generate
JSON Schema **from the pydantic models** so they cannot drift:

```sh
python -c "from bionexus.core.contracts import AssayResult; \
print(AssayResult.model_json_schema())"
```
