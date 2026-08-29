# Block A — Workflow & Orchestration (L1)

Owner-separable: pure software, no hardware or model dependencies. Can be built
entirely against stub tool endpoints.

## Components

### Stage Graph Engine
- Declarative DAG of stages; each stage = `StageTask` producer/consumer
- Constructs: sequential, parallel fan-out/fan-in, retry, conditional branch,
  human-gate
- Stage-exit criteria evaluated per iteration (loops back for the active learning cycle)

### Agent Router
- Matches `StageTask` requirements (capability, modality) to registered agent instances
- Tracks agent health/heartbeat; reassigns on failure

### Human-in-the-Loop Gates
- Gate types: `approve_candidate_batch`, `approve_wetlab_protocol`,
  `approve_trial_protocol`, `arbitrary_redirect`
- Pausing a gate pauses the owning sandbox (AgentENV pause/resume) so full context
  survives long human latencies

### Provenance Store
- WORM append-only records; every artifact versioned and hash-chained
- Query API for lineage: "which prompts/model versions produced molecule X?"

### Experiment Ledger
- Claims: instrument slots, reagent reservations, GPU batches
- Cost tracking per experiment branch

## Interfaces

| Direction | Contract | Notes |
|---|---|---|
| → Agents (B) | `StageTask` / `StageResult` | async, idempotent, resumable |
| → C/D/E | `ToolInvocation` / `ToolResult` | typed tool registry |
| → L0 | gate events, audit queries | UI-facing |
| ← all | `ProvenanceRecord` | mandatory on every artifact |

## Build order
1. Contracts (schemas) + in-memory stage graph
2. Gate + provenance store (SQLite → Postgres)
3. Router with heartbeat
4. Cost/ledger
