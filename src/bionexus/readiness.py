"""ExperimentReadinessReview — decide whether an experiment, if it succeeds,
would support its claim.

The review runs BEFORE the lab is engaged. It separates:

  blockers    the result would be uninterpretable or unsafe; the experiment
              must be redesigned, not merely re-run
  warnings    interpretability caveats attached to the result
  passes      structural checks that cleared

This is the scientific counterpart of the SafetyEngine: the SafetyEngine
decides whether an action is *allowed*; the readiness review decides whether
the action is *worth running* given the claim it is supposed to support.
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from bionexus.core.contracts import Envelope, EventType
from bionexus.core.interfaces import ProvenanceStore, record_for
from bionexus.experiment import (
    ClaimType,
    ExperimentDefinition,
    ReadoutCapability,
)


class ReviewVerdict(str, Enum):
    ready = "ready"
    ready_with_warnings = "ready_with_warnings"
    blocked = "blocked"


class ReadinessFinding(BaseModel):
    check: str
    severity: str            # "pass" | "warning" | "blocker"
    message: str


class ExperimentReadinessReview(BaseModel):
    experiment_id: str | None = None
    hypothesis_id: str | None = None
    verdict: ReviewVerdict
    findings: list[ReadinessFinding] = Field(default_factory=list)

    @property
    def blockers(self) -> list[ReadinessFinding]:
        return [f for f in self.findings if f.severity == "blocker"]

    @property
    def warnings(self) -> list[ReadinessFinding]:
        return [f for f in self.findings if f.severity == "warning"]

    def summary(self) -> str:
        lines = [f"verdict: {self.verdict.value}"]
        for f in self.findings:
            lines.append(f"  [{f.severity}] {f.check}: {f.message}")
        return "\n".join(lines)


# --------------------------------------------------------------- the review

# Claims that require the readout to distinguish edited from unedited target
# (the "missing denominator" problem).
_DENOMINATOR_CLAIMS = {
    ClaimType.loss_of_function,
    ClaimType.causal_modification,
}

# Claims that require an authentic modification, not a phosphomimetic or
# other surrogate.
_AUTHENTIC_MODIFICATION_CLAIMS = {
    ClaimType.causal_modification,
    ClaimType.occupancy_vs_catalysis,
}


def review_experiment(defn: ExperimentDefinition) -> ExperimentReadinessReview:
    findings: list[ReadinessFinding] = []

    def add(check: str, ok: bool, warning_only: bool, message: str) -> None:
        if ok:
            findings.append(ReadinessFinding(check=check, severity="pass", message=message))
        elif warning_only:
            findings.append(ReadinessFinding(check=check, severity="warning", message=message))
        else:
            findings.append(ReadinessFinding(check=check, severity="blocker", message=message))

    # 1. the claim must be statable
    add("scientific_question", bool(defn.scientific_question.strip()), False,
        "scientific question is stated" if defn.scientific_question.strip()
        else "no scientific question is stated")

    # 2. the readout must be able to support the claim type
    r = defn.readout
    if defn.claim_type in _DENOMINATOR_CLAIMS and not r.measures_edited_fraction:
        add("edited_fraction_denominator", False, False,
            "claim requires an edited-vs-unedited denominator, but the readout "
            "does not quantify the edited fraction; negative results would be "
            "uninterpretable")
    else:
        add("edited_fraction_denominator", True, True,
            "edited fraction accounted for" if r.measures_edited_fraction
            else "not required for this claim type")

    if defn.claim_type in _AUTHENTIC_MODIFICATION_CLAIMS and \
            not r.distinguishes_modified_from_mimetic:
        add("authentic_modification", False, False,
            "claim requires an authentic modification, but the readout cannot "
            "distinguish it from a mimetic")
    else:
        add("authentic_modification", True, True,
            "authentic modification distinguishable" if defn.claim_type in
            _AUTHENTIC_MODIFICATION_CLAIMS else "not required for this claim type")

    # 3. kinetic compatibility: target turnover vs experiment window
    half_life = defn.system.target_half_life_min
    if half_life is not None and half_life < 30 and \
            defn.claim_type == ClaimType.turnover_or_pulse_cohort:
        add("turnover_window", False, True,
            f"target half-life ({half_life} min) is comparable to the editing "
            "window; survivorship bias expected — pulse-cohort claims are "
            "marginal")
    elif half_life is not None and half_life < 30:
        add("turnover_window", True, True,
            f"target half-life ({half_life} min) is short; expect survivorship "
            "bias in edited cohorts")
    else:
        add("turnover_window", True, True, "no turnover conflict declared")

    # 4. delivery variance
    if defn.delivery.method and not defn.delivery.per_cell_loading_measured:
        add("delivery_variance", True, True,
            "per-cell loading not measured; time-resolved claims carry "
            "unmeasured delivery variance")
    else:
        add("delivery_variance", True, True, "no delivery variance concern declared")

    # 5. acceptor-bearing state (the cassette burden)
    if defn.intervention.requires_prior_genome_edit:
        add("acceptor_burden", True, True,
            "target carries the construct before the experiment; the "
            "acceptor-bearing state, not the edit, may drive the phenotype")

    # 6. controls
    add("controls", bool(defn.controls), True,
        f"{len(defn.controls)} control(s) declared" if defn.controls
        else "no controls declared")

    # 7. denominators for interpretable negative results
    add("denominators", bool(defn.denominators), True,
        f"{len(defn.denominators)} denominator(s) declared" if defn.denominators
        else "no denominators declared; negative results are weaker")

    # 8. readout capabilities cover the claim's resolution needs
    if defn.claim_type == ClaimType.detection_or_pulldown and \
            ReadoutCapability.signal_present not in r.capabilities and \
            ReadoutCapability.edited_vs_unedited not in r.capabilities:
        add("readout_capability", False, False,
            "detection/pulldown claim requires at least signal detection")
    else:
        add("readout_capability", True, True, "readout capabilities adequate")

    # 9. synthesis feasibility (if the intervention produces a compound)
    meta = defn.metadata or {}
    if meta.get("synthesis_check") and meta.get("synthesis_route"):
        route = meta["synthesis_route"]
        if not route.get("feasible", True):
            add("synthesis_feasibility", False, False,
                f"no viable synthesis route: {route.get('notes', '')}")
        elif route.get("num_steps", 0) > 12:
            add("synthesis_feasibility", True, True,
                f"long route ({route['num_steps']} steps) — consider simplification")
        else:
            add("synthesis_feasibility", True, True,
                f"viable route ({route.get('num_steps', '?')} steps)")
    else:
        add("synthesis_feasibility", True, True,
            "not assessed (no synthesis route provided)")

    blockers = [f for f in findings if f.severity == "blocker"]
    if blockers:
        verdict = ReviewVerdict.blocked
    elif any(f.severity == "warning" for f in findings):
        verdict = ReviewVerdict.ready_with_warnings
    else:
        verdict = ReviewVerdict.ready
    return ExperimentReadinessReview(
        experiment_id=defn.experiment_id,
        hypothesis_id=defn.hypothesis_id,
        verdict=verdict,
        findings=findings,
    )


def review_and_record(
    store: ProvenanceStore,
    envelope: Envelope,
    actor: Any,
    defn: ExperimentDefinition,
) -> tuple[ExperimentReadinessReview, Any]:
    """Run the readiness review and append it to the provenance chain."""
    review = review_experiment(defn)
    store.append(record_for(
        envelope, EventType.experiment_readiness_reviewed, actor,
        decision={
            "experiment_id": defn.experiment_id,
            "hypothesis_id": defn.hypothesis_id,
            "verdict": review.verdict.value,
            "blockers": [b.message for b in review.blockers],
            "warnings": [w.message for w in review.warnings],
        }))
    return review
