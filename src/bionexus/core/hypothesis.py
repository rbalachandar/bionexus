"""First-class hypotheses (P5: proposed → tested → validated/invalidated).

A hypothesis is a falsifiable prediction tied to a candidate and an assay.
Its lifecycle is fully provenance-recorded: proposal, test run, and verdict
(with evidence) are separate immutable records, so the scientific trail is
auditable end to end.
"""
from __future__ import annotations

import uuid
from typing import Any, Callable

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


__all__ = [
    "Constraint", "ExperimentDesign", "Hypothesis", "HypothesisTracker",
    "PortfolioDecision", "ProblemStatement", "SuccessCriteria",
]


class SuccessCriteria(BaseModel):
    """Declared BEFORE the experiment runs (pre-registration semantics)."""
    metric: str                          # e.g. "ic50_um", "percent_inhibition"
    direction: str = "min"               # "min" | "max"  (which direction is good)
    threshold: float                     # success boundary on the metric
    min_replicates: int = 1              # minimum evidence required to conclude
    inconclusive_if_qc_failed: bool = True  # bad QC -> inconclusive, not invalidated

    def met(self, value: float) -> bool:
        return value <= self.threshold if self.direction == "min" else value >= self.threshold

    def classify(self, value: float,
                 ci: tuple[float | None, float | None] | None = None) -> str:
        """Point estimate decides; the CI can VETO certainty.

        If the 95% interval straddles the threshold, the honest verdict is
        'inconclusive' — not a coin-flip dressed as a result.
        """
        if ci is None or ci[0] is None or ci[1] is None:
            return "validated" if self.met(value) else "invalidated"
        lo, hi = ci
        if self.direction == "min":
            if hi <= self.threshold:
                return "validated"
            if lo > self.threshold:
                return "invalidated"
        else:
            if lo >= self.threshold:
                return "validated"
            if hi < self.threshold:
                return "invalidated"
        return "inconclusive"


class Constraint(BaseModel):
    """A hard or soft constraint on the solution space, declared with the problem."""
    name: str
    description: str = ""
    kind: str = "hard"                   # "hard" | "soft" | "preference"
    limit: float | None = None           # numeric bound where applicable
    unit: str | None = None


class ProblemStatement(BaseModel):
    """Stage 0: what are we trying to achieve, and within what constraints?

    Everything downstream (hypotheses, experiments, verdicts) traces back here.
    """
    problem_id: str = Field(default_factory=lambda: f"prob-{uuid.uuid4().hex[:8]}")
    objective: str                       # the scientific question / goal
    context: str = ""                    # background, prior evidence
    constraints: list[Constraint] = Field(default_factory=list)
    success_metric: str | None = None    # what "solved" means
    proposed_by: str = "scientist"


class PortfolioDecision(BaseModel):
    """Why a hypothesis made / did not make the cut."""
    hypothesis_id: str
    selected: bool
    score: float = 0.0
    reason: str = ""


class ExperimentDefinitionRef(BaseModel):
    """Reference to the scientific experiment definition (see bionexus.experiment)."""
    experiment_id: str
    scientific_question: str
    claim_type: str
    summary: str = ""


class ExperimentDesign(BaseModel):
    """The experiment that will test the hypothesis — specified up-front."""
    assay_type: str
    concentrations: list[str] = Field(default_factory=list)
    replicates: int = 1
    controls: list[str] = Field(default_factory=list)
    design_notes: str = ""
    protocol_id: str | None = None       # filled when the protocol is submitted
    run_id: str | None = None
    definition: ExperimentDefinitionRef | None = None   # scientific manifest
    readiness_verdict: str | None = None  # ready / ready_with_warnings / blocked


class Hypothesis(BaseModel):
    hypothesis_id: str
    branch_id: str
    statement: str                      # falsifiable prediction
    rationale: str = ""                 # why we believe it (prior evidence)
    mechanism: str = ""                 # the CAUSAL story, not just correlation
    predicted_observables: list[str] = Field(default_factory=list)
    refutation_condition: str = ""      # what observation KILLS this hypothesis
    citation: str = ""                  # PMID/DOI grounding the rationale
    candidate: str                      # molecule/sample id under test
    assay_type: str = ""
    predicted: str                      # human-readable prediction
    predicted_value: float | None = None
    round: int = 1
    status: str = "proposed"            # proposed | designed | tested | validated | invalidated | inconclusive
    criteria: SuccessCriteria | None = None
    design: ExperimentDesign | None = None
    observed_value: float | None = None
    observed_ci: tuple[float | None, float | None] | None = None
    qc_passed: bool | None = None
    evidence_run_id: str | None = None
    problem_id: str | None = None        # root problem this hypothesis addresses
    portfolio_rank: int | None = None    # order in the proposed portfolio
    family: str | None = None            # mechanistic family (same claim, many variants)
    metadata: dict[str, Any] = Field(default_factory=dict)


def explanatory_bonus(h: "Hypothesis") -> float:
    """Explanatory power is worth a portfolio edge: a hypothesis that says
    WHY (mechanism), HOW IT COULD DIE (refutation condition), and WHERE IT
    COMES FROM (citation) is more testable science than a bare prediction.
    Capped at 0.2 so it breaks ties, never overrides real scores."""
    bonus = 0.0
    if h.mechanism:
        bonus += 0.10
    if h.refutation_condition:
        bonus += 0.05
    if h.citation:
        bonus += 0.05
    return min(bonus, 0.2)


class HypothesisTracker:
    """Records the full hypothesis lifecycle into the provenance store.

    Stage 0: define_problem -> propose_portfolio -> select_portfolio
    Then each selected hypothesis enters the flow: propose/designed -> tested
    -> validated | invalidated | inconclusive.
    """

    def __init__(self, store: ProvenanceStore, actor: Actor,
                 on_verdict: Callable[[Any], None] | None = None):
        self.store = store
        self.actor = actor
        self.hypotheses: dict[str, Hypothesis] = {}
        self.on_verdict = on_verdict      # flywheel hook (best-effort)

    def define_experiment(
        self,
        problem: ProblemStatement,
        definition: Any,
        review: Any = None,
    ) -> Any:
        """Register a scientific ExperimentDefinition (bionexus.experiment)
        with its readiness review before any protocol is submitted.
        `definition` is an ExperimentDefinition; `review` is the readiness
        review result if already computed."""
        branch = f"problem/{problem.problem_id}"
        env = Envelope(experiment_branch_id=branch)
        verdict = review.verdict.value if review is not None else None
        self.store.append(self._record(
            env, EventType.experiment_defined, self.actor,
            decision={
                "experiment_id": definition.experiment_id,
                "scientific_question": definition.scientific_question,
                "claim_type": definition.claim_type.value,
                "target": definition.intervention.target,
                "verdict": verdict,
            }))
        self.store.append(record_for(
            env, EventType.experiment_readiness_reviewed, self.actor,
            decision={
                "experiment_id": definition.experiment_id,
                "verdict": verdict,
                "warnings": [f.message for f in review.warnings] if review else [],
                "blockers": [b.message for b in review.blockers] if review else [],
            }))
        return definition

    # ------------------------------------------- stage 0: problem & portfolio

    def define_problem(self, problem: ProblemStatement) -> ProblemStatement:
        """Record the problem + constraints. Root of the provenance tree."""
        self.store.append(self._record(
            Envelope(experiment_branch_id=f"problem/{problem.problem_id}"),
            EventType.problem_defined, None,
            decision={
                "problem_id": problem.problem_id,
                "objective": problem.objective,
                "constraints": [c.model_dump() for c in problem.constraints],
                "success_metric": problem.success_metric,
            },
        ))
        return problem

    def propose_portfolio(
        self,
        problem: ProblemStatement,
        hypotheses: list[dict[str, Any]],
    ) -> list[Hypothesis]:
        """Register a batch of candidate hypotheses addressing the problem.
        Each dict: statement, candidate, assay_type, predicted, rationale,
        predicted_value, optional criteria/design. All recorded; selection next."""
        proposed: list[Hypothesis] = []
        for i, spec in enumerate(hypotheses, start=1):
            h = self.propose(
                branch_id=f"problem/{problem.problem_id}",
                statement=spec["statement"],
                candidate=spec["candidate"],
                assay_type=spec.get("assay_type", "binding"),
                predicted=spec.get("predicted", spec["statement"]),
                predicted_value=spec.get("predicted_value"),
                rationale=spec.get("rationale", ""),
                mechanism=spec.get("mechanism", ""),
                refutation_condition=spec.get("refutation_condition", ""),
                predicted_observables=spec.get("predicted_observables"),
                citation=spec.get("citation", ""),
                round_no=0,
                criteria=spec.get("criteria"),
                design=spec.get("design"),
            )
            h.problem_id = problem.problem_id
            h.portfolio_rank = i
            h.family = spec.get("family")
            h.branch_id = f"problem/{problem.problem_id}"
            self.hypotheses[h.hypothesis_id] = h
            proposed.append(h)
        return proposed

    def propose_families(
        self,
        problem: ProblemStatement,
        families: list[dict[str, Any]],
    ) -> list[Hypothesis]:
        """Register mechanistically DISTINCT hypothesis families, each with
        variant hypotheses (same claim, different parameterizations — e.g.
        analogs of one warhead). Each family dict:
          {family, parent_statement, kind, rationale,
           variants: [variant-spec dicts as in propose_portfolio]}
        Returns flat variant list, each tagged with its family; the family
        parent claim itself is provenance-recorded."""
        all_variants: list[Hypothesis] = []
        for fam in families:
            fid = fam.get("family") or f"fam-{abs(hash(fam['parent_statement'])) % 10**8}"
            self.store.append(self._record(
                Envelope(experiment_branch_id=f"problem/{problem.problem_id}"),
                EventType.hypothesis_proposed, None,
                decision={
                    "family_id": fid,
                    "parent_statement": fam["parent_statement"],
                    "kind": fam.get("kind", "mechanistic"),
                    "rationale": fam.get("rationale", ""),
                    "n_variants": len(fam.get("variants", [])),
                }))
            for spec in fam.get("variants", []):
                spec = dict(spec)
                spec.setdefault("rationale", fam.get("rationale", ""))
                for k in ("mechanism", "refutation_condition", "citation"):
                    spec.setdefault(k, fam.get(k, ""))
                h = self.propose(
                    branch_id=f"problem/{problem.problem_id}",
                    statement=spec["statement"],
                    candidate=spec["candidate"],
                    assay_type=spec.get("assay_type", "binding"),
                    predicted=spec.get("predicted", spec["statement"]),
                    predicted_value=spec.get("predicted_value"),
                    rationale=spec.get("rationale", ""),
                    mechanism=spec.get("mechanism", ""),
                    refutation_condition=spec.get("refutation_condition", ""),
                    predicted_observables=spec.get("predicted_observables"),
                    citation=spec.get("citation", ""),
                    round_no=0,
                    criteria=spec.get("criteria"),
                    design=spec.get("design"),
                )
                h.problem_id = problem.problem_id
                h.family = fid
                self.hypotheses[h.hypothesis_id] = h
                all_variants.append(h)
        return all_variants

    def select_portfolio(self, problem: ProblemStatement,
                         proposed: list[Hypothesis],
                         score_fn: Callable[[Hypothesis], float],
                         k: int = 2,
                         max_per_family: int | None = None) -> list[Hypothesis]:
        """Analyze + filter the portfolio to the k hypotheses worth testing.
        With max_per_family, selection enforces DIVERSITY: at most N variants
        of the same mechanistic family are taken (a sweep of one idea cannot
        crowd out different ideas). Every accept/reject decision is
        provenance-recorded with its reason."""
        def _total(h: Hypothesis) -> float:
            return score_fn(h) + explanatory_bonus(h)
        scored = sorted(proposed, key=_total, reverse=True)
        selected, decisions = [], []
        family_counts: dict[str, int] = {}
        for h in scored:
            sel = len(selected) < k
            reason = "top-k by score"
            if sel and max_per_family is not None and h.family:
                if family_counts.get(h.family, 0) >= max_per_family:
                    sel = False
                    reason = (f"family '{h.family}' already has "
                              f"{max_per_family} selected (diversity cap)")
            if sel:
                selected.append(h)
                if h.family:
                    family_counts[h.family] = family_counts.get(h.family, 0) + 1
            bonus = explanatory_bonus(h)
            decisions.append(PortfolioDecision(
                hypothesis_id=h.hypothesis_id, selected=sel,
                score=round(score_fn(h) + bonus, 4),
                reason=(reason + (f" (+{bonus:.2f} explanatory power)"
                                  if bonus else ""))))
        self.store.append(self._record(
            Envelope(experiment_branch_id=f"problem/{problem.problem_id}"),
            EventType.hypotheses_filtered, None,
            decision={
                "problem_id": problem.problem_id,
                "k": k,
                "decisions": [d.model_dump() for d in decisions],
            },
        ))
        return selected

    def propose(self, statement: str, candidate: str, assay_type: str,
                predicted: str, predicted_value: float | None = None,
                rationale: str = "", round_no: int = 1,
                mechanism: str = "", refutation_condition: str = "",
                predicted_observables: list[str] | None = None,
                citation: str = "",
                criteria: SuccessCriteria | None = None,
                design: ExperimentDesign | None = None,
                branch_id: str | None = None, **meta: Any) -> Hypothesis:
        env = Envelope(experiment_branch_id=branch_id or f"hyp/{round_no}")
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
            mechanism=mechanism,
            refutation_condition=refutation_condition,
            predicted_observables=predicted_observables or [],
            citation=citation,
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
                                                 "rationale": rationale,
                                                 "mechanism": mechanism,
                                                 "refutation_condition":
                                                     refutation_condition,
                                                 "citation": citation,
                                                 "predicted_observables":
                                                     h.predicted_observables}))
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
                                                 "protocol_id": protocol.protocol_id,
                                                 "assay": getattr(
                                                     protocol.assay_type, "value",
                                                     str(protocol.assay_type))}))

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
        ci = None
        for m in result.measurements:
            if m.sample_id == h.candidate:
                low = m.derived_metrics.get("ic50_ci_low")
                high = m.derived_metrics.get("ic50_ci_high")
                if low is not None and high is not None:
                    ci = (low, high)
        if not qc_ok:
            h.status = "inconclusive"
        elif value is None:
            h.status = "inconclusive"  # no usable evidence (right-censored etc.)
        else:
            h.status = criteria.classify(value, ci)
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
                      "statement": h.statement,
                      **({"mechanism": h.mechanism} if h.mechanism else {}),
                      **({"citation": h.citation} if h.citation else {})},
        )

    def record_outcome(self, h: Hypothesis, extra: dict | None = None) -> Hypothesis:
        """Provenance-record a verdict already determined on `h` (e.g. by the
        auto-analysis agent fitting a device export). Same event shape as
        `verdict()` — observed, threshold, qc, evidence run — so the pipeline
        view and diary see agent-side and lab-side verdicts identically."""
        event = {
            "validated": EventType.hypothesis_validated,
            "confirmed": EventType.hypothesis_validated,
            "invalidated": EventType.hypothesis_invalidated,
        }.get(h.status, EventType.hypothesis_tested)
        env = Envelope(experiment_branch_id=h.branch_id)
        decision = {
            "metric": h.criteria.metric if h.criteria else "value",
            "threshold": h.criteria.threshold if h.criteria else None,
            "observed": h.observed_value,
            "observed_ci": list(h.observed_ci) if h.observed_ci else None,
            "qc_passed": h.qc_passed,
            "evidence_run_id": h.evidence_run_id,
            "verdict": h.status,
        }
        if extra:
            decision.update(extra)
        self.store.append(self._record(env, event, h, decision=decision))
        if self.on_verdict is not None:
            try:
                self.on_verdict(h)
            except Exception:
                pass                       # the flywheel must never break a run
        return h

    def _record(self, env: Envelope, event: EventType, h: Any,
                decision: dict) -> ProvenanceRecord:
        artifact = self._artifact(h) if isinstance(h, Hypothesis) else None
        return record_for(env, event, self.actor, artifact=artifact, decision=decision)

    def summary(self) -> dict[str, int]:
        counts = {"proposed": len(self.hypotheses), "validated": 0,
                  "invalidated": 0, "inconclusive": 0}
        for h in self.hypotheses.values():
            if h.status in ("validated", "invalidated", "inconclusive"):
                counts[h.status] += 1
        return counts
