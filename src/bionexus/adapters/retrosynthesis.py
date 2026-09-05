"""Retrosynthesis planning adapter — synthesis feasibility assessment.

Protocol for retrosynthesis services (ASKCOS, IBM RXN, AiZynthFinder, or
simulated). Returns a structured route with feasibility scoring so the
readiness review can block compounds with no viable synthesis pathway.

The simulated implementation uses molecular complexity heuristics and is
sufficient for CI; real adapters wrap external APIs with the same contract.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class SynthesisStep:
    """One step in a retrosynthesis route."""
    step_number: int
    transformation: str            # e.g. "amide coupling", "Suzuki coupling"
    product_smiles: str
    reactant_smiles: list[str]
    reagents: list[str] = field(default_factory=list)
    conditions: str = ""
    yield_percent: float | None = None


@dataclass
class SynthesisRoute:
    """A complete retrosynthesis route."""
    target_smiles: str
    feasible: bool
    num_steps: int
    starting_materials: list[str] = field(default_factory=list)
    steps: list[SynthesisStep] = field(default_factory=list)
    overall_score: float = 0.0     # 0-1, higher = more feasible
    route_confidence: float = 0.0
    notes: str = ""

    def summary(self) -> dict[str, Any]:
        return {
            "target": self.target_smiles,
            "feasible": self.feasible,
            "steps": self.num_steps,
            "score": round(self.overall_score, 3),
            "starting_materials": self.starting_materials,
        }


class RetrosynthesisAdapter(Protocol):
    """Protocol for retrosynthesis planning backends."""

    name: str

    def plan(self, smiles: str) -> SynthesisRoute:
        """Generate a retrosynthesis route for the target compound."""
        ...


class SimulatedRetrosynthesis:
    """Complexity-heuristic retrosynthesis for CI and offline use (P8).

    Estimates feasibility from molecular complexity signals (ring count,
    stereocenters, sp3 fraction) without calling external services.
    """

    name = "simulated-retrosynthesis"

    def plan(self, smiles: str) -> SynthesisRoute:
        complexity = self._complexity_score(smiles)
        feasible = complexity < 0.7
        num_steps = max(1, round(complexity * 8))
        return SynthesisRoute(
            target_smiles=smiles,
            feasible=feasible,
            num_steps=num_steps,
            overall_score=round(1.0 - complexity, 3),
            route_confidence=0.5,  # simulated: low confidence
            notes=f"simulated: complexity {complexity:.2f} "
                  f"({'feasible' if feasible else 'challenging'})",
        )

    def _complexity_score(self, smiles: str) -> float:
        """0 = simple, 1 = very complex. Pure SMILES string heuristics."""
        score = 0.0
        rings = smiles.count("1") + smiles.count("2") + smiles.count("3")
        score += min(rings * 0.08, 0.3)
        if "@" in smiles:
            score += 0.15  # stereocenters
        if "#" in smiles:
            score += 0.1   # triple bonds
        if "[" in smiles:
            score += 0.1   # charged/annotated atoms
        hetero = sum(smiles.count(a) for a in "NOS")
        score += min(hetero * 0.03, 0.15)
        if len(smiles) > 60:
            score += 0.1
        return min(round(score, 3), 1.0)


def get_retrosynthesis_adapter(name: str = "simulated") -> RetrosynthesisAdapter:
    if name == "simulated":
        return SimulatedRetrosynthesis()
    raise ValueError(f"unknown retrosynthesis adapter: {name}")
