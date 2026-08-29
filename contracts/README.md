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

## Status

- [ ] `StageTask` — draft
- [ ] `ToolInvocation` — draft
- [ ] `ProtocolSubmission` — draft
- [ ] `AssayResult` — draft
- [ ] `ProvenanceRecord` — draft

## Conventions

- Each contract lives in its own OpenAPI or protobuf file under this directory,
  versioned (`v1/`), never mutated in place — additive evolution only.
- Every contract carries a shared envelope: `contract_id`, `schema_version`,
  `experiment_branch_id`, `provenance_ref`, `created_at`.
- ID conventions: ULIDs for artifacts, `(branch_id, seq)` for records within a branch.
