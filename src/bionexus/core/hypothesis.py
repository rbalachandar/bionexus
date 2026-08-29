"""First-class hypotheses (P5: proposed → tested → validated/invalidated).

A hypothesis is a falsifiable prediction tied to a candidate and an assay.
Its lifecycle is fully provenance-recorded: proposal, test run, and verdict
(with evidence) are separate immutable records, so the scientific trail is
auditable end to end.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from bionexus.core.contracts import (
    Actor,
    Artifact,
    ArtifactKind,
    AssayResult,
    Envelope,
    EventType,
    ProtocolSubmission,
    ProvenanceRecord,
)
from bionexus.core.interfaces import ProvenanceStore, record_for


class Hypothesis(BaseModel):
    hypothesis_id: str
    branch_id: str
    statement: str                      # falsifiable prediction
    candidate: str                      # molecule/sample id under test
    assay_type: str
    predicted: str                      # e.g. ">= 60 percent_inhibition"
    predicted_value: float | None = None
    round: int = 1
    status: str = "proposed"            # proposed | validated | invalidated
    evidence_run_id: str | None = None
    measured_value: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class HypothesisTracker:
    """Records the full hypothesis lifecycle into the provenance store."""

    def __init__(self, store: ProvenanceStore, actor: Actor):
        self.store = store
        self.actor = actor
        self.hypotheses: dict[str, Hypothesis] = {}

    def propose(self, statement: str, candidate: str, assay_type: str,
                predicted: str, predicted_value: float | None = None,
                round_no: int = 1, **meta: Any) -> Hypothesis:
        env = Envelope(experiment_branch_id=f"hyp/{round_no}")
        h = Hypothesis(
            hypothesis_id=f"hyp-{abs(hash((statement, candidate, round_no))) % 10**8}",
            branch_id=env.experiment_branch_id,
            statement=statement,
            candidate=candidate,
            assay_type=assay_type,
            predicted=predicted,
            predicted_value=predicted_value,
            round=round_no,
            metadata=meta,
        )
        self.hypotheses[h.hypothesis_id] = h
        self.store.append(self._record(env, EventType.hypothesis_proposed, h,
                                       decision={"statement": statement, "predicted": predicted}))
        return h

    def attach_test(self, h: Hypothesis, protocol: ProtocolSubmission, run_id: str) -> None:
        env = Envelope(experiment_branch_id=h.branch_id)
        self.store.append(self._record(env, EventType.hypothesis_tested, h,
                                       decision={"run_id": run_id,
                                                 "protocol_id": protocol.protocol_id}))

    def verdict(self, h: Hypothesis, result: AssayResult, threshold: float) -> Hypothesis:
        """Compare measured vs predicted; record validated/invalidated + evidence."""
        value = next(
            (m.value for m in result.measurements if m.sample_id == h.candidate),
            None,
        )
        h.measured_value = value
        h.evidence_run_id = result.run_id
        h.status = "validated" if (value is not None and value >= threshold) else "invalidated"
        event = EventType.hypothesis_validated if h.status == "validated" else EventType.hypothesis_invalidated
        env = Envelope(experiment_branch_id=h.branch_id)
        self.store.append(self._record(env, event, h, decision={
            "predicted": h.predicted_value, "measured": value,
            "threshold": threshold, "evidence_run_id": result.run_id,
        }))
        return h

    def _record(self, env: Envelope, event: EventType, h: Hypothesis,
                decision: dict) -> ProvenanceRecord:
        return record_for(
            env, event, self.actor,
            artifact=Artifact(
                artifact_id=h.hypothesis_id,
                kind=ArtifactKind.hypothesis,
                uri=f"mem://{h.branch_id}/{h.hypothesis_id}",
                metadata={"candidate": h.candidate, "assay": h.assay_type,
                          "statement": h.statement},
            ),
            decision=decision,
        )

    def summary(self) -> dict[str, int]:
        counts = {"proposed": len(self.hypotheses), "validated": 0, "invalidated": 0}
        for h in self.hypotheses.values():
            if h.status in ("validated", "invalidated"):
                counts[h.status] += 1
        return counts
