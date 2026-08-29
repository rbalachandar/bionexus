# Block D — Lab Execution (L2/L3 boundary)

The physical-world block. Fully buildable as software via the Virtual Lab Simulator
before any real hardware is touched.

## Standards alignment

- **MCP (Model Context Protocol)** — IAL tools are exposed both over the internal
  gRPC/REST contract and as MCP servers, so general-purpose agent frameworks
  (Claude, BioNeMo toolkit) can consume them without bespoke glue.
- **Anthropic Model Hardware Standard** — track this emerging spec for AI agents
  operating physical lab devices; the Safety & Constraint Engine is our enforcement
  point for it.
- **Isomorphic "bioresilience"** — safety posture assumes model error is inevitable;
  constraints are layered (protocol-level, run-level, instrument-level hard stops).

## Instrument Abstraction Layer (IAL)

The single contract for all lab hardware:

```text
submit_protocol(protocol_id, compiled_script, samples[]) -> run_id
get_status(run_id) -> {queued | running | done | failed, progress}
fetch_results(run_id) -> raw telemetry + files
cancel(run_id)
list_capabilities() -> instrument catalog, throughputs, constraints
```

Adapters: Opentrons/liquid handlers, plate readers, sequencers, cloud labs
(Emerald/Arctoris-style). A `SimulatorAdapter` implements the same interface.

## Protocol Compiler
- Abstract protocol (agent-authored, declarative) → instrument-specific scripts
- Validates against instrument capabilities from `list_capabilities()`
- Idempotent, resumable run plans

## Safety & Constraint Engine
- Policy layer **outside** any agent's trust boundary; agents cannot bypass or
  reconfigure it
- Hard blocks: reagent inventory limits, biosafety level constraints, forbidden
  reagent combinations, throughput caps
- Rejection reasons are returned to the agent so it can revise

## Lab State Manager
- Inventory (reagents, plates, samples) with expiry/lot tracking
- Scheduling queue per instrument; sample barcoding / chain of custody

## Telemetry Ingestor
- Streams raw instrument output → normalized `AssayResult`
- QC flags (failed wells, controls out of range)
- Publishes to Provenance Store with full run lineage

## Virtual Lab Simulator
- Mock instruments + physics/ML-based assay outcome simulation (backed by Block E)
- Seeded noise and failure modes for robust agent training/evaluation
- Zero-change swap: flip the IAL adapter, agents unaware
