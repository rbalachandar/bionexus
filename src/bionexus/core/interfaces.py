"""BioNexus core interfaces (P2: interfaces, not implementations).

Five protocols define every block boundary. Core consumes only these; adapters
implement them. All results are provenance-wrapped (P5); physical lab actions
are dispatched through the SafetyEngine (P6); Sandbox exposes fork/snapshot as
first-class operations (P7).
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from bionexus.core.contracts import (
    Actor,
    AssayResult,
    Envelope,
    EventType,
    ProtocolSubmission,
    ProvenanceRecord,
    ToolInvocation,
    ToolName,
    ToolResult,
)


@runtime_checkable
class ModelProvider(Protocol):
    """Any foundation model (P3). Implementations must pin model+version so the
    provenance chain can record exactly what produced an artifact."""

    name: str
    model_version: str

    def generate(self, invocation: ToolInvocation, prompt: str, **kwargs: Any) -> ToolResult:
        """Text/completion generation (e.g. molecule proposals, reflections)."""
        ...

    def predict(self, invocation: ToolInvocation, kind: ToolName, payload: dict[str, Any]) -> ToolResult:
        """Structured prediction (property, ADMET, structure). `kind` selects the task."""
        ...


@runtime_checkable
class BioTool(Protocol):
    """A computational bio capability (RDKit, docking, ADMET...). Adapters declare
    capabilities; the registry matches tool names to implementations (P2)."""

    name: str
    capabilities: tuple[ToolName, ...]

    def invoke(self, invocation: ToolInvocation) -> ToolResult:
        """Run a local computation. Must not perform physical actions."""
        ...


@runtime_checkable
class SafetyEngine(Protocol):
    """Policy layer in the physical-action path (P6). Outside any agent's trust
    boundary: agents cannot register rules or mark protocols safe."""

    def check(self, protocol: ProtocolSubmission) -> tuple[bool, str | None]:
        """Return (approved, rejection_reason)."""
        ...


@runtime_checkable
class LabAdapter(Protocol):
    """The IAL: simulator, Opentrons, cloud lab — one contract (P4). Concrete
    adapters must NOT expose this directly to agents; dispatch goes through
    core's LabGateway which enforces SafetyEngine first (P6)."""

    name: str

    def list_capabilities(self) -> dict[str, Any]:
        """Instrument catalog: assays supported, throughput, constraints."""
        ...

    def submit_protocol(self, protocol: ProtocolSubmission) -> str:
        """Queue a compiled protocol; returns run_id. Call only after safety approval."""
        ...

    def get_status(self, run_id: str) -> str:
        """queued | running | done | failed | cancelled"""
        ...

    def fetch_results(self, run_id: str) -> AssayResult:
        """Normalized AssayResult with QC flags and instrument lineage."""
        ...

    def cancel(self, run_id: str) -> None: ...


@runtime_checkable
class Sandbox(Protocol):
    """Experiment-branch lifecycle (P7): create/fork/snapshot/resume. Adapters may
    degrade (e.g. local deep-copy forks) but the interface must hold."""

    sandbox_id: str
    branch_id: str

    def snapshot(self) -> str:
        """Freeze full state; returns snapshot_id usable by fork/restore."""
        ...

    def fork(self, snapshot_id: str | None = None) -> "Sandbox":
        """New sandbox branching from this one (or a stored snapshot)."""
        ...

    def resume(self, snapshot_id: str | None = None) -> None: ...

    def destroy(self) -> None: ...


@runtime_checkable
class ProvenanceStore(Protocol):
    """Append-only, hash-chained lineage (P5). Implementations: SQLite, Postgres,
    WORM bucket. Records are immutable once written."""

    def append(self, record: ProvenanceRecord) -> ProvenanceRecord:
        """Compute and stamp record_hash from prev chain; store; return final."""
        ...

    def lineage(self, artifact_id: str) -> list[ProvenanceRecord]:
        """All records touching an artifact, root-first."""
        ...

    def branch_records(self, branch_id: str) -> list[ProvenanceRecord]:
        """Every record within an experiment branch."""
        ...


# ------------------------------------------------------------------ helpers

def make_envelope(branch_id: str, parent_branch_id: str | None = None) -> Envelope:
    return Envelope(experiment_branch_id=branch_id, parent_branch_id=parent_branch_id)


def system_actor(name: str = "bionexus-core") -> Actor:
    return Actor(kind="service", id=name)


def record_for(
    envelope: Envelope,
    event_type: EventType,
    actor: Actor,
    **kwargs: Any,
) -> ProvenanceRecord:
    """Convenience: build a ProvenanceRecord in this branch."""
    return ProvenanceRecord(
        envelope=envelope.model_copy(),
        event_type=event_type,
        actor=actor,
        **kwargs,
    )
