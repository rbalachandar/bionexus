"""Demo: full DMTA cycle with TPP, ADMET panel, retrosynthesis, and readiness.

    python examples/demo_dmta_cycle.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bionexus.adapters.admet import get_admet_predictor
from bionexus.adapters.retrosynthesis import SimulatedRetrosynthesis
from bionexus.agents import AgentRole, get_persona
from bionexus.core.contracts import Envelope
from bionexus.core.hypothesis import Constraint, HypothesisTracker, ProblemStatement
from bionexus.core.interfaces import system_actor
from bionexus.experiment import (
    BiologicalSystem, ClaimType, DeliveryConditions, ExperimentDefinition,
    Intervention, ReadoutCapability, ReadoutSpec,
)
from bionexus.readiness import review_and_record, review_experiment
from bionexus.tpp import Criterion, CriterionCategory, CriterionPhase, \
    standard_small_molecule_tpp

CANDIDATES = [
    "CC(=O)Nc1ccc(O)cc1",                     # paracetamol-like
    "CC(C)Nc1ccc(cc1)C(=O)NC2=CC=CC=C2",      # bigger
    "c1ccc2c(c1)[nH]c1ccccc12",               # fused aromatic
    "CC(C)(C)N=C(N)N",                        # metformin-like
    "OC(=O)c1ccccc1NC(=S)N1CCCCC1",           # piperidine + thiourea
]


def main() -> None:
    # 0. TPP
    tpp = standard_small_molecule_tpp("Demo-Program", "MAP4K1", ic50_nm=50)
    print(f"TPP: {tpp.program_name} ({len(tpp.criteria)} criteria)")
    for phase in CriterionPhase:
        cr = tpp.criteria_for_phase(phase)
        if cr:
            print(f"  {phase.value:12} {len(cr)} criteria")

    # 1. agents
    print("\n=== Agent Personas ===")
    for role in AgentRole:
        p = get_persona(role)
        print(f"  {p.display_name:24} tools: {', '.join(p.preferred_tools[:3])}")

    # 2. ADMET
    print("\n=== ADMET Panel ===")
    admet = get_admet_predictor()
    admet_results = {}
    for smi in CANDIDATES:
        r = admet.predict(smi)
        admet_results[smi] = r.summary()
        print(f"  {smi[:30]:32} MW={r.mw_da} Lipinski={r.lipinski_violations} "
              f"Veber={'PASS' if r.passes_veber else 'FAIL'} "
              f"PAINS={r.pains_alerts or 'none'}")

    # 3. retrosynthesis
    print("\n=== Retrosynthesis ===")
    rt = SimulatedRetrosynthesis()
    for smi in CANDIDATES:
        route = rt.plan(smi)
        print(f"  {smi[:30]:32} feasible={route.feasible} "
              f"steps={route.num_steps} score={route.overall_score}")

    # 4. TPP evaluation using ADMET data
    print("\n=== TPP Evaluation (hit phase, using ADMET results) ===")
    measurements = {}
    for smi in CANDIDATES:
        a = admet_results[smi]
        if a.get("mw_da"):
            measurements["MW_da"] = a["mw_da"]
        ev = tpp.evaluate(measurements, CriterionPhase.hit)
    print(ev.summary())

    # 5. readiness review with synthesis + ADMET
    print("\n=== Readiness Review ===")
    store = SqliteProvenanceStore = __import__(
        "bionexus.adapters.store.sqlite", fromlist=["SqliteProvenanceStore"]
    ).SqliteProvenanceStore()
    tracker = HypothesisTracker(store, system_actor("dmta-demo"))
    problem = tracker.define_problem(ProblemStatement(
        objective="Find a viable HPK1 inhibitor candidate",
        constraints=[Constraint(name="synthesis", description="must be synthesizable",
                                kind="hard")],
        success_metric="TPP hit-phase pass + synthesis feasibility"))

    for smi in CANDIDATES:
        a = admet_results[smi]
        route = rt.plan(smi)
        exp = ExperimentDefinition(
            experiment_id=f"exp-{smi[:12]}",
            scientific_question=f"Is {smi[:20]} viable for further optimization?",
            claim_type=ClaimType.detection_or_pulldown,
            intervention=Intervention(kind="binding_assay", target="HPK1",
                                      cassette=smi),
            system=BiologicalSystem(cell_line="biochemical"),
            readout=ReadoutSpec(assay="binding",
                                capabilities=[ReadoutCapability.signal_present]),
            controls=["DMSO"],
            metadata={"synthesis_check": True,
                      "synthesis_route": route.summary()},
        )
        env = Envelope(experiment_branch_id="dmta-demo")
        review = review_and_record(store, env, system_actor("dmta-demo"), exp)
        status = review.verdict.value
        if a.get("flags"):
            status += f" [ADMET: {'; '.join(a['flags'])}]"
        print(f"  {smi[:30]:32} {status}")


from bionexus.adapters.store.sqlite import SqliteProvenanceStore  # noqa: E402

if __name__ == "__main__":
    main()
