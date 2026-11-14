"""Retrosynthesis planning adapter — synthesis feasibility assessment.

Protocol for retrosynthesis services (ASKCOS, IBM RXN, AiZynthFinder, or
simulated). Returns a structured route with feasibility scoring so the
readiness review can block compounds with no viable synthesis pathway.

`RuleBasedRetrosynthesis` plans named-reaction routes (amide coupling,
Suzuki–Miyaura, Buchwald–Hartwig, CuAAC click, ...) from a tiny public
corpus of disconnection rules. Yield, lead-time and cost are MODELED per
candidate (deterministic per SMILES, seeded) — every plan carries the
SIMULATED stamp. It is a makeability gate, not a chemistry oracle.
"""
from __future__ import annotations

import hashlib
import random
import re
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


SIM_LABEL = ("simulated: named-reaction rule corpus (8 disconnection "
             "rules; per-candidate seeded yield/lead-time/cost — not a "
             "real reaction database)")

YIELD_FLOOR_PCT = 5.0    # below this, a route is not worth attempting
LEAD_TIME_CEIL_DAYS = 60.0


@dataclass
class RoutePlan:
    """One modeled route to the target. Units: percent, days, USD."""
    route: str
    steps: int
    yield_pct: float
    lead_time_days: float
    cost_usd: float
    reagents: list[str] = field(default_factory=list)
    feasible: bool = True
    data_origin: str = SIM_LABEL

    def summary(self) -> dict[str, Any]:
        return {"route": self.route, "steps": self.steps,
                "yield_pct": self.yield_pct,
                "lead_time_days": self.lead_time_days,
                "cost_usd": self.cost_usd, "feasible": self.feasible,
                "reagents": self.reagents, "data_origin": self.data_origin}


# Public named-reaction corpus (v1): motif => (display name, match fn,
# per-step yield mean %, reaction days/step, reagent $/step). Motifs are
# approximate SMILES disconnection triggers — a gate heuristic, not a
# chemistry oracle.
_RULES: list[tuple[str, Any, float, float, float]] = [
    ("amide", lambda s: "NC(=O)" in s or "C(=O)N" in s, 85.0, 1.0, 180.0),
    ("biaryl", lambda s: s.count("ccccc") >= 2 or "c1ccc2" in s,
     78.0, 1.5, 260.0),
    ("aryl-N heteroaryl", lambda s: "Nc" in s or "[nH]" in s or "nccn" in s,
     70.0, 1.5, 300.0),
    ("N-alkylation", lambda s: "NCC" in s or "OCC" in s or "SCC" in s,
     82.0, 0.5, 60.0),
    ("carbonyl (red. amination / Grignard)",
     lambda s: "C(=O)" in s or "C=O" in s, 75.0, 1.0, 90.0),
    ("terminal alkyne / triazole (CuAAC click)",
     lambda s: "C#C" in s or "C#N" in s or "n1nnc" in s, 88.0, 1.0, 120.0),
    ("halogen handle (SNAr / cross-coupling precursor)",
     lambda s: any(tok in s for tok in ("Cl", "Br", "F", "I")),
     80.0, 1.0, 110.0),
    ("saturated aliphatic ring (hydrogenation / ring build)",
     lambda s: "C1CCCCC1" in s or "[CH]1CCC" in s, 76.0, 1.0, 140.0),
]


def _complexity(smiles: str) -> int:
    """Estimated minimum linear steps: ring closures (each bond-closure
    digit appears twice) + stereocenters + a size penalty. String
    heuristics — a documented approximation, not a step-count oracle."""
    if not smiles:
        return 1
    rings = len(re.findall(r"[1-9]", smiles)) // 2
    stereo = smiles.count("@")
    return max(1, rings // 2 + stereo + (1 if len(smiles) > 70 else 0))


def _model_route(rule_name: str, smiles: str, steps: int) -> RoutePlan:
    """Per-candidate modeled yield/lead-time/cost, deterministic for the
    (SMILES, route) pair — the STAMPED simulated numbers the gate runs on."""
    rng = random.Random(hashlib.sha256(
        f"{rule_name}|{smiles}|{steps}".encode()).hexdigest())
    step_yields = [max(30.0, min(97.0, rng.gauss(
        next(r[2] for r in _RULES if r[0] == rule_name), 8.0)))
        for _ in range(steps)]
    overall = 100.0 * eval_prod(step_yields)
    days = next(r[3] for r in _RULES if r[0] == rule_name)
    cost_s = next(r[4] for r in _RULES if r[0] == rule_name)
    lead = steps * days + steps * rng.uniform(0.5, 1.5) + \
        rng.choice([1.0, 3.0, 7.0, 14.0])
    cost = sum(rng.uniform(0.55, 1.45) * c for c in (cost_s, 250.0, 150.0)
               [:steps]) + 40.0 * steps
    return RoutePlan(route=rule_name.replace("_", " "), steps=steps,
                     yield_pct=round(max(0.5, overall), 1),
                     lead_time_days=round(lead, 1), cost_usd=round(cost, 0),
                     feasible=(overall >= YIELD_FLOOR_PCT
                               and lead <= LEAD_TIME_CEIL_DAYS))


def eval_prod(vals: list[float]) -> float:
    p = 1.0
    for v in vals:
        p *= v / 100.0
    return p


class RuleBasedRetrosynthesis:
    """Named-reaction rule-corpus planning: how MANY routes, how LONG, at
    what COST, each yield modeled per candidate and stamped simulated."""

    name = "rule-based"

    def plan_routes(self, smiles: str) -> list[RoutePlan]:
        steps = _complexity(smiles)
        rules = [r[0] for r in _RULES if r[1](smiles or "")]
        if not rules:
            # no disconnection motif found: one generic linear route, but
            # step-heavy targets fail their own feasibility floor — the
            # block is earned by the model, not by an unparseable string
            rules = ["generic_linear"]
            return [RoutePlan(
                route="generic linear synthesis", steps=steps,
                yield_pct=round(max(0.5, 100.0 * eval_prod(
                    [70.0] * steps)), 1),
                lead_time_days=round(steps * 2.0 + 7.0, 1),
                cost_usd=round(steps * 300.0, 0),
                feasible=(steps <= 6 and 100.0 * eval_prod([70.0] * steps)
                          >= YIELD_FLOOR_PCT),
                data_origin=SIM_LABEL)]
        # a real chemist tries convergent options: at most 3 distinct routes
        routes = [_model_route(r, smiles, steps) for r in rules[:3]]
        # step economy: a shorter second strategy if the target is step-heavy
        if steps >= 4 and len({r.route for r in routes}) < len(routes):
            routes.append(_model_route(rules[-1], smiles, max(1, steps - 1)))
        return routes

    def plan(self, smiles: str) -> SynthesisRoute:
        """Protocol-shaped view of the best route."""
        routes = self.plan_routes(smiles)
        best = max(routes, key=lambda r: (r.feasible, r.yield_pct))
        return SynthesisRoute(
            target_smiles=smiles, feasible=best.feasible,
            num_steps=best.steps, overall_score=round(best.yield_pct / 100, 3),
            route_confidence=0.4,
            starting_materials=["commercial building blocks (modeled)"],
            notes=f"{SIM_LABEL} | routes={len(routes)} best={best.route} "
                  f"{best.lead_time_days}d ~${best.cost_usd:.0f}")


def get_retrosynthesis_adapter(name: str = "rule-based") -> RetrosynthesisAdapter:
    if name == "simulated":
        return SimulatedRetrosynthesis()
    if name == "rule-based":
        return RuleBasedRetrosynthesis()
    raise ValueError(f"unknown retrosynthesis adapter: {name}")
