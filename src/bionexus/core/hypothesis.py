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


class SuccessCriteria(BaseModel):
    """Declared BEFORE the experiment runs (pre-registration semantics)."""
    metric: str                          # e.g. "ic50_um", "percent_inhibition"
    direction: str = "min"               # "min" | "max"  (which direction is good)
    threshold: float                     # success boundary on the metric
    min_replicates: int = 1              # minimum evidence required to conclude
    inconclusive_if_qc_failed: bool = True  # bad QC -> inconclusive, not invalidated

    def met(self, value: float) -> bool:
        return value <= self.threshold if self.direction == "min" else value >= self.threshold


class ExperimentDesign(BaseModel):
    """The experiment that will test the hypothesis — specified up-front."""
    assay_type: str
    concentrations: list[str] = Field(default_factory=list)
    replicates: int = 1
    controls: list[str] = Field(default_factory=list)
    design_notes: str = ""
    protocol_id: str | None = None       # filled when the protocol is submitted
    run_id: str | None = None


class Hypothesis(BaseModel):
    hypothesis_id: str
    branch_id: str
    statement: str                      # falsifiable prediction
    rationale: str = ""                 # why we believe it (prior evidence)
    candidate: str                      # molecule/sample id under test
    assay_type: str = ""
    predicted: str                      # human-readable prediction
    predicted_value: float | None = None
    round: int = 1
    status: str = "proposed"            # proposed | designed | tested | validated | invalidated | inconclusive
    criteria: SuccessCriteria | None = None
    design: ExperimentDesign | None = None
    observed_value: float | None = None
    qc_passed: bool | None = None
    evidence_run_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class HypothesisTracker:
    """Records the full hypothesis lifecycle into the provenance store."""

    def __init__(self, store: ProvenanceStore, actor: Actor):
        self.store = store
        self.actor = actor
        self.hypotheses: dict[str, Hypothesis] = {}

    def propose(self, statement: str, candidate: str, assay_type: str,
                predicted: str, predicted_value: float | None = None,
                rationale: str = "", round_no: int = 1,
                criteria: SuccessCriteria | None = None,
                design: ExperimentDesign | None = None, **meta: Any) -> Hypothesis:
        env = Envelope(experiment_branch_id=f"hyp/{round_no}")
        if criteria is None:
            # derive explicit criteria from the point prediction (min-direction:
            # IC50-style assays). Callers should override for max-direction.
            criteria = SuccessCriteria(metric="ic50_um", direction="min",
                                       threshold=predicted_value or 0.0)
        if design is None:
            design = ExperimentDesign(assay_type=assay_type)
        h = Hypothesis(
            hypothesis_id=f"hyp-{abs(hash((statement, candidate, round_no))) % 10**8}",
            branch_id=env.experiment_branch_id,
            statement=statement,
            rationale=rationale,
            candidate=candidate,
            assay_type=assay_type,
            predicted=predicted,
            predicted_value=predicted_value,
            round=round_no,
            criteria=criteria,
            design=design,
            metadata=meta,
        )
        self.hypotheses[h.hypothesis_id] = h
        self.store.append(self._record(env, EventType.hypothesis_proposed, h,
                                       decision={"statement": statement,
                                                 "predicted": predicted,
                                                 "criteria": h.criteria.model_dump(),
                                                 "design": h.design.model_dump(),
                                                 "rationale": rationale}))
        return h

    def specify_design(self, h: Hypothesis, design: ExperimentDesign) -> Hypothesis:
        """Declare the experiment design before running it (designed state)."""
        h.design = design
        h.status = "designed"
        self.hypotheses[h.hypothesis_id] = h
        self.store.append(self._record(
            Envelope(experiment_branch_id=h.branch_id), EventType.stage_transition,
            self.actor,  # design event; keeps stage_transition for workflow linkage
            artifact=self._artifact(h),
            decision={"designed_for": h.hypothesis_id, "design": design.model_dump()},
        ))
        return h

    def attach_test(self, h: Hypothesis, protocol: ProtocolSubmission, run_id: str) -> None:
        h.design = h.design or ExperimentDesign(assay_type=protocol.assay_type.value)
        h.design.protocol_id = protocol.protocol_id
        h.design.run_id = run_id
        h.status = "tested" if h.status in ("proposed", "designed") else h.status
        self.hypotheses[h.hypothesis_id] = h
        env = Envelope(experiment_branch_id=h.branch_id)
        self.store.append(self._record(env, EventType.hypothesis_tested, h,
                                       decision={"run_id": run_id,
                                                 "protocol_id": protocol.protocol_id}))

    def verdict(self, h: Hypothesis, result: AssayResult,
                threshold: float | None = None) -> Hypothesis:
        """Assess against the pre-declared criteria. QC-failed or missing-evidence
        runs yield 'inconclusive', never a silent invalidate."""
        if threshold is not None and h.criteria is None:
            h.criteria = SuccessCriteria(metric="ic50_um", threshold=threshold)
        criteria = h.criteria or SuccessCriteria(metric="value", threshold=threshold or 0.0)
        qc_ok = getattr(result.qc, "controls_passed", True)
        value = next(
            (m.value for m in result.measurements
             if m.sample_id == h.candidate
             and (criteria.metric == "value" or criteria.metric in m.derived_metrics
                  or m.unit == criteria.metric)),
            None,
        )
        h.observed_value = value
        h.qc_passed = qc_ok
        h.evidence_run_id = result.run_id
        if not qc_ok:
            h.status = "inconclusive"
        elif value is None:
            h.status = "inconclusive"  # no usable evidence (right-censored etc.)
        else:
            h.status = "validated" if criteria.met(value) else "invalidated"
        event = {
            "validated": EventType.hypothesis_validated,
            "invalidated": EventType.hypothesis_invalidated,
        }.get(h.status, EventType.hypothesis_tested)
        env = Envelope(experiment_branch_id=h.branch_id)
        self.store.append(self._record(env, event, h, decision={
            "metric": criteria.metric, "threshold": criteria.threshold,
            "observed": value, "qc_passed": qc_ok,
            "evidence_run_id": result.run_id,
            "verdict": h.status,
        }))
        return h

    def _artifact(self, h: Hypothesis) -> Artifact:
        return Artifact(
            artifact_id=h.hypothesis_id,
            kind=ArtifactKind.hypothesis,
            uri=f"mem://{h.branch_id}/{h.hypothesis_id}",
            metadata={"candidate": h.candidate, "assay": h.assay_type,
                      "statement": h.statement},
        )

    def _record(self, env: Envelope, event: EventType, h: Hypothesis,
                decision: dict) -> ProvenanceRecord:
        return record_for(env, event, self.actor,
                          artifact=self._artifact(h), decision=decision)

    def summary(self) -> dict[str, int]:
        counts = {"proposed": len(self.hypotheses), "validated": 0,
                  "invalidated": 0, "inconclusive": 0}
        for h in self.hypotheses.values():
            if h.status in ("validated", "invalidated", "inconclusive"):
                counts[h.status] += 1
        return counts
