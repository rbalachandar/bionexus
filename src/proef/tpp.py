"""Target Product Profile (TPP) — the structured, persistent success contract.

A TPP declares what the final candidate must achieve, in phases. It is the
root object every campaign round is evaluated against. Unlike ad-hoc
constraints on a ProblemStatement, the TPP is versioned, phased, and
explicitly separates desired vs. required properties.

Inspired by the real drug-discovery practice of defining a Product Target
Profile before chemistry begins, then measuring every design round against it.
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class CriterionPhase(str, Enum):
    hit = "hit"                       # early screening gate
    lead = "lead"                     # hit-to-lead gate
    candidate = "candidate"           # preclinical candidate gate
    clinical = "clinical"             # clinical candidate (IND-enabling)


class CriterionCategory(str, Enum):
    potency = "potency"
    selectivity = "selectivity"
    admet = "admet"
    physicochemical = "physicochemical"
    safety = "safety"
    efficacy = "efficacy"
    synthesizability = "synthesizability"


class Criterion(BaseModel):
    """A single measurable criterion with a threshold and direction."""
    name: str                         # e.g. "IC50_nM", "LogP", "hERG_inhibition_uM"
    category: CriterionCategory
    phase: CriterionPhase
    threshold: float
    direction: str = "max"            # "max" = higher is better, "min" = lower is better
    unit: str = ""
    required: bool = True             # required = hard gate; optional = nice-to-have
    description: str = ""


class TPP(BaseModel):
    """Target Product Profile: the structured success contract for a campaign."""
    tpp_id: str = ""
    program_name: str
    objective: str
    target_name: str
    indication: str = ""
    criteria: list[Criterion] = Field(default_factory=list)
    version: int = 1
    metadata: dict[str, Any] = Field(default_factory=dict)

    def criteria_for_phase(self, phase: CriterionPhase) -> list[Criterion]:
        """All criteria that apply at a given phase (cumulative: earlier phases included)."""
        order = list(CriterionPhase)
        idx = order.index(phase)
        return [c for c in self.criteria if order.index(c.phase) <= idx]

    def required_for_phase(self, phase: CriterionPhase) -> list[Criterion]:
        return [c for c in self.criteria_for_phase(phase) if c.required]

    def evaluate(self, measurements: dict[str, float], phase: CriterionPhase) -> "TPPEvaluation":
        """Score a set of measurements against the TPP criteria for a phase."""
        results: list[CriterionResult] = []
        applicable = self.criteria_for_phase(phase)
        for c in applicable:
            value = measurements.get(c.name)
            if value is None:
                results.append(CriterionResult(
                    criterion=c, value=None,
                    passed=not c.required,  # missing required = fail
                    note="not measured"))
                continue
            if c.direction == "min":
                passed = value <= c.threshold
            else:
                passed = value >= c.threshold
            margin = (value - c.threshold) if c.direction == "max" else (c.threshold - value)
            results.append(CriterionResult(
                criterion=c, value=value, passed=passed,
                margin=round(margin, 4),
                note="" if passed else f"{'above' if c.direction == 'max' else 'below'} threshold by {abs(margin):.4g}"))
        passed_all = all(r.passed for r in results if r.criterion.required)
        return TPPEvaluation(
            tpp_id=self.tpp_id, phase=phase,
            all_required_passed=passed_all,
            results=results,
        )

    def advance_version(self, updated_criteria: list[Criterion] | None = None) -> "TPP":
        """Return a new TPP version (immutable update pattern)."""
        new = self.model_copy(deep=True)
        new.version = self.version + 1
        if updated_criteria is not None:
            new.criteria = updated_criteria
        return new


class CriterionResult(BaseModel):
    criterion: Criterion
    value: float | None = None
    passed: bool = False
    margin: float | None = None
    note: str = ""


class TPPEvaluation(BaseModel):
    tpp_id: str
    phase: CriterionPhase
    all_required_passed: bool
    results: list[CriterionResult] = Field(default_factory=list)

    @property
    def failures(self) -> list[CriterionResult]:
        return [r for r in self.results if not r.passed and r.criterion.required]

    def summary(self) -> str:
        lines = [f"TPP '{self.tpp_id}' @ {self.phase.value}: "
                 f"{'PASS' if self.all_required_passed else 'FAIL'}"]
        for r in self.results:
            status = "PASS" if r.passed else "FAIL"
            val = f"{r.value:.4g}" if r.value is not None else "not measured"
            lines.append(f"  [{status:4}] {r.criterion.name}: {val} "
                         f"(threshold {'<=' if r.criterion.direction == 'min' else '>='} "
                         f"{r.criterion.threshold} {r.criterion.unit})")
        return "\n".join(lines)


# ------------------------------------------------------- standard templates

def standard_small_molecule_tpp(
    program_name: str,
    target_name: str,
    ic50_nm: float = 10.0,
    min_selectivity: float = 10.0,
    max_logp: float = 5.0,
    max_mw_da: float = 500.0,
) -> TPP:
    """Pre-built TPP for a small-molecule kinase/soluble-target program."""
    return TPP(
        program_name=program_name,
        objective=f"Identify a {target_name} inhibitor meeting the product target profile",
        target_name=target_name,
        criteria=[
            # Hit phase
            Criterion(name="IC50_nM", category=CriterionCategory.potency,
                      phase=CriterionPhase.hit, threshold=1000.0, direction="min",
                      unit="nM", description="Hit-level potency"),
            Criterion(name="MW_da", category=CriterionCategory.physicochemical,
                      phase=CriterionPhase.hit, threshold=max_mw_da, direction="min",
                      unit="Da", description="Molecular weight"),
            # Lead phase
            Criterion(name="IC50_nM", category=CriterionCategory.potency,
                      phase=CriterionPhase.lead, threshold=ic50_nm, direction="min",
                      unit="nM", description="Lead-level potency"),
            Criterion(name="selectivity_ratio", category=CriterionCategory.selectivity,
                      phase=CriterionPhase.lead, threshold=min_selectivity, direction="max",
                      description="Selectivity vs closest off-target"),
            Criterion(name="LogP", category=CriterionCategory.physicochemical,
                      phase=CriterionPhase.lead, threshold=max_logp, direction="min",
                      description="Lipophilicity"),
            Criterion(name="solubility_uM", category=CriterionCategory.admet,
                      phase=CriterionPhase.lead, threshold=50.0, direction="max",
                      unit="µM", description="Aqueous solubility"),
            # Candidate phase
            Criterion(name="hERG_inhibition_uM", category=CriterionCategory.safety,
                      phase=CriterionPhase.candidate, threshold=10.0, direction="min",
                      unit="µM", description="hERG channel safety margin"),
            Criterion(name="microsomal_CLint", category=CriterionCategory.admet,
                      phase=CriterionPhase.candidate, threshold=30.0, direction="min",
                      unit="µL/min/mg", description="Microsomal stability"),
            Criterion(name="Ames_positive", category=CriterionCategory.safety,
                      phase=CriterionPhase.candidate, threshold=0.0, direction="max",
                      description="Ames genotoxicity (0 = negative)"),
            Criterion(name="synthesis_steps", category=CriterionCategory.synthesizability,
                      phase=CriterionPhase.candidate, threshold=8, direction="min",
                      description="Convergent synthesis route length"),
        ],
    )
