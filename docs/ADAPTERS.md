# Writing an adapter

Adapters implement one (or more) of the five core protocols from
`bionexus.core.interfaces`. They live anywhere; core discovers them via
entry points or you construct them directly.

Rules (enforced in review):

1. Import core only through `bionexus.core` — never another adapter.
2. Declare capabilities explicitly; don't claim what you don't implement.
3. Stamp `model_version` / instrument identity on every result (P5 provenance).
4. Physical actions never happen in `BioTool` — only `LabAdapter`, and only
   via the `LabGateway` (P6).

## LabAdapter (the IAL)

```python
from bionexus.core.contracts import AssayResult, Envelope, ProtocolSubmission, RunStatus, InstrumentInfo

class MyRobotLab:
    name = "my-robot"

    def list_capabilities(self) -> dict:
        return {"assays": ["binding"], "throughput": {"plates_per_day": 10}, "bsl_max": 1}

    def submit_protocol(self, protocol: ProtocolSubmission) -> str:
        return self._robot.enqueue(compile(protocol))   # run_id

    def get_status(self, run_id: str) -> str:
        return self._robot.status(run_id)               # queued|running|done|failed|cancelled

    def fetch_results(self, run_id: str) -> AssayResult:
        raw = self._robot.results(run_id)
        return AssayResult(                              # normalize to the contract
            envelope=Envelope(experiment_branch_id="my-robot"),
            protocol_id=run_id,
            instrument=InstrumentInfo(adapter=self.name, instrument_id=self._id),
            status=RunStatus.completed,
            measurements=self._normalize(raw),
        )

    def cancel(self, run_id: str) -> None:
        self._robot.cancel(run_id)
```

Agents never call this directly — register it with `LabGateway(lab, safety, store, actor)`
and hand agents the gateway. Unsafe protocols are rejected with a reason before
your adapter ever sees them (P6).

## ModelProvider

```python
class MyProvider:
    name = "my-provider"
    model_version = "mine-2026-01"          # pinned, stamped on results (P5)

    def generate(self, invocation, prompt, **kw) -> ToolResult: ...
    def predict(self, invocation, kind, payload) -> ToolResult: ...
```

`bionexus/adapters/models/openai_compat.py` is the reference — including the
offline stub mode used by CI (P8). Copy it.

## BioTool

```python
class MyDocking:
    name = "my-docking"
    capabilities = (ToolName.sim_docking,)   # declare exactly what you serve

    def invoke(self, invocation: ToolInvocation) -> ToolResult: ...
```

Register on a `Registry` (`registry.register_tool(...)`) or expose via the
`bionexus.tools` entry point group. Resolution is capability → implementation.

## ProvenanceStore

`SqliteProvenanceStore` is the reference: append computes `record_hash` from
the previous record in the branch. Postgres/WORM implementations must keep the
chain verifiable and append-only.

## Publish via entry points

```toml
[project.entry-points."bionexus.labs"]
my-robot = "my_org.labs:MyRobotLab"
```

`Registry().load_entry_points()` picks these up; missing optional deps skip
silently, never fatally.

## Real device adapters (reference implementations)

Two production-shaped adapters ship in-tree:

- **`adapters/lab/opentrons.py`** — Opentrons OT-2/Flex over the robot HTTP API
  (port 31950). The **Make** step of DMTA: compiles `ProtocolSubmission` into an
  Opentrons Python protocol, uploads, plays the run, polls status. Results are
  execution evidence (succeeded commands), not assay values — read the plate
  afterwards with a reader adapter or `bn read`.
- **`adapters/lab/plate_reader_share.py`** — for readers configured to
  **auto-export completed reads to a network share** (Biotek Gen5, SoftMax Pro,
  SpectraMax...). Submit registers the expected run; `fetch_results` waits for
  the newest export and parses it with `labread` (autodetect, controls, IC50,
  Z' QC).

Both follow the P8 pattern: **CI runs against injected/recorded transports and
generated export files** — no hardware needed to develop or test. When you
connect hardware, only the transport changes.
