# Integration Contracts

Five versioned schemas are the only coupling between blocks. Pin these first —
each block then builds independently against stubs.

| Contract | Producer → Consumer | Purpose |
|---|---|---|
| `StageTask` / `StageResult` | Orchestration (A) → Agents (B) | stage assignment + outputs, idempotent/resumable |
| `ToolInvocation` / `ToolResult` | A/B → C/D/E | typed calls to models, simulators, lab |
| `ProtocolSubmission` | Assay Agent (B) → Compiler (D) | abstract wet-lab protocol |
| `AssayResult` | Telemetry (D) → A/Analysis (B) | normalized results + QC + lineage |
| `ProvenanceRecord` | everything → Provenance Store (A) | immutable lineage entry |

Draft OpenAPI 3.1 schemas live under [`v1/`](v1/) (all validate as YAML;
`$ref` to `envelope.yaml` for the shared envelope):

- [x] `envelope.yaml` — shared Envelope + ID conventions
- [x] `stage_task.yaml` — `StageTask` / `StageResult`
- [x] `tool_invocation.yaml` — `ToolInvocation` / `ToolResult` (+ tool name registry)
- [x] `protocol_submission.yaml` — `ProtocolSubmission`
- [x] `assay_result.yaml` — `AssayResult`
- [x] `provenance_record.yaml` — `ProvenanceRecord`

## Conventions

- Each contract lives in its own OpenAPI or protobuf file under this directory,
  versioned (`v1/`), never mutated in place — additive evolution only.
- Every contract carries a shared envelope: `contract_id`, `schema_version`,
  `experiment_branch_id`, `provenance_ref`, `created_at`.
- ID conventions: ULIDs for artifacts, `(branch_id, seq)` for records within a branch.
