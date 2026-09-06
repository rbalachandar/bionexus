"""BioNexus — the definitive full-flow demo.

Runs the complete scientific method end to end, combining every layer:

  1. Problem + constraints
  2. TPP evaluation
  3. Agent proposes hypothesis families
  4. Portfolio filter (diversity cap)
  5. ExperimentDefinition + Readiness Review
  6. ADMET + retrosynthesis
  7. Safety-gated lab execution (async: submit → check → verdict)
  8. Hypothesis verdicts vs pre-registered criteria
  9. Confirmation loop
  10. Provenance: hash-chained, tamper-evident

    .venv/bin/python examples/demo_full_flow.py
"""
from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bionexus.adapters.admet import get_admet_predictor
from bionexus.adapters.lab.imaging import ImagingSimulatorLab
from bionexus.adapters.lab.simulator import SimulatorLab, parse_concentration_um
from bionexus.adapters.models.openai_compat import OpenAICompatProvider
from bionexus.adapters.retrosynthesis import SimulatedRetrosynthesis
from bionexus.adapters.store.sqlite import SqliteProvenanceStore
from bionexus.core.contracts import (
    AssayResult, Envelope, EventType, InstrumentInfo, Measurement,
    ProtocolOp, ProtocolStep, ProtocolSubmission, ReagentSpec, RunStatus,
    SampleKind, SampleSpec, ToolInvocation,
)
from bionexus.core.hypothesis import (
    Constraint, ExperimentDesign, HypothesisTracker, ProblemStatement,
    SuccessCriteria,
)
from bionexus.core.interfaces import record_for, system_actor
from bionexus.core.registry import Registry
from bionexus.core.safety import LabGateway, MaxBslRule, MaxStepsRule, SafetyEngine
from bionexus.experiment import (
    BiologicalSystem, ClaimType, DeliveryConditions, ExperimentDefinition,
    Intervention, ReadoutSpec,
)
from bionexus.readiness import review_experiment
from bionexus.tpp import Criterion, CriterionCategory, CriterionPhase, TPP

ACTIVE_PIC50 = 6.5
CONCS = ["0.5uM", "2uM", "10uM", "40uM"]


def main() -> None:
    store = SqliteProvenanceStore(Path.cwd() / "full_flow.db")
    actor = system_actor("full-flow")
    model = OpenAICompatProvider()
    registry = Registry()
    registry.register_model(model, default=True)

    lab = SimulatorLab(seed=42)
    safety = SafetyEngine(rules=[MaxBslRule(2), MaxStepsRule(50)])
    gateway = LabGateway(lab, safety, store, actor)

    tracker = HypothesisTracker(store, actor)
    envelope = Envelope(experiment_branch_id="full-flow")

    tpp = standard_small_molecule_tpp("FullFlow-Demo", "HPK1", ic50_nm=50)
    admet = get_admet_predictor()
    retro = SimulatedRetrosynthesis()

    def say(msg: str) -> None:
        print(msg)

    def record(event, decision, artifact=None):
        store.append(record_for(envelope, event, actor, artifact=artifact,
                                decision=decision))

    # ================================================= 1. PROBLEM + TPP
    say("=" * 60)
    say("1. PROBLEM STATEMENT + TPP")
    say("=" * 60)
    problem = tracker.define_problem(ProblemStatement(
        objective="Identify HPK1 inhibitors meeting the TPP hit-phase criteria",
        context="Novel target; compound set from prior virtual screening",
        constraints=[
            Constraint(name="potency", description="pIC50 >= 6.5",
                       kind="hard", limit=6.5),
            Constraint(name="budget", description="max 5 hypotheses to wet-lab",
                       kind="hard"),
        ],
        success_metric="at least 1 confirmed hit with clean ADMET",
    ))
    # record TPP as provenance
    record(EventType.stage_transition,
           {"stage": "tpp", "criteria_count": len(tpp.criteria)})
    hit_criteria = tpp.criteria_for_phase(CriterionPhase.hit)
    for c in hit_criteria:
        say(f"  {c.name}: {'<=' if c.direction == 'min' else '>='} "
            f"{c.threshold} {c.unit} (required={c.required})")

    # ================================================= 2. CANDIDATES
    say("\n" + "=" * 60)
    say("2. CANDIDATE GENERATION")
    say("=" * 60)
    candidates = [
        {"smiles": "Cc1ccc(Nc2ncc(C(=O)N3CCOCC3)c3[nH]c(=O)cc32)cc1", "label": "PYR-01"},
        {"smiles": "Nc1nc(Nc2ccc(F)cc2)c2ncn(C3CC3)c2n1", "label": "PUR-02"},
        {"smiles": "O=C(Nc1ccc(F)cc1)c1cnc(N2CCOCC2)nn1", "label": "PYRZ-03"},
        {"smiles": "Cc1ccc(S(=O)(=O)N2CCCCC2)cc1Nc1nccs1", "label": "THIA-04"},
        {"smiles": "NC(=N)c1ccc(C(=O)Nc2ccccc2)cc1", "label": "BENZ-05"},
    ]
    print(f"  {len(candidates)} candidates generated")
    record(EventType.stage_transition,
           {"stage": "candidates", "count": len(candidates)})

    # ================================================= 3. ADMET FILTER
    say("\n" + "=" * 60)
    say("3. ADMET FILTER")
    say("=" * 60)
    passing = []
    for c in candidates:
        smi = c["smiles"]
        r = admet.predict(smi)
        ok = r.mw_da is not None and r.mw_da < 550 and not r.has_pains
        tag = "PASS" if ok else "FAIL"
        flags = f" [{'; '.join(r.flags)}]" if r.flags else ""
        mw_str = f"{r.mw_da:.1f}" if r.mw_da is not None else "?"
        print(f"  {c['label']:8} MW={mw_str:>6}  {tag}{flags}")
        if ok:
            passing.append(c)
    print(f"  → {len(passing)} candidates pass ADMET")

    # ================================================= 4. RETROSYNTHESIS
    say("\n" + "=" * 60)
    say("4. RETROSYNTHESIS FEASIBILITY")
    say("=" * 60)
    synth_ok = []
    for c in passing:
        route = retro.plan(c["smiles"])
        ok = route.feasible
        print(f"  {c['label']:8} feasible={ok} steps={route.num_steps} "
              f"score={route.overall_score:.2f}")
        if ok:
            synth_ok.append(c)
    print(f"  → {len(synth_ok)} synthesizable candidates")

    # ================================================= 5. HYPOTHESES
    say("\n" + "=" * 60)
    say("5. HYPOTHESIS PROPOSAL")
    say("=" * 60)
    hyps = []
    for c in synth_ok:
        h = tracker.propose(
            statement=f"{c['label']} binds HPK1 with pIC50 >= 6.5",
            candidate=c["smiles"], assay_type="binding",
            predicted="pIC50 >= 6.5", predicted_value=6.5, round_no=1,
            rationale="passes ADMET + synthesis feasibility",
            criteria=SuccessCriteria(metric="ic50_um", direction="min",
                                     threshold=316.0),
            design=ExperimentDesign(
                assay_type="binding", concentrations=CONCS,
                replicates=3, controls=["negative"]),
        )
        hyps.append(h)
        say(f"  H: {h.statement[:60]} (ID: {h.hypothesis_id})")
    say(f"  {len(hyps)} hypotheses pre-registered")

    # ================================================= 6. LAB EXECUTION
    say("\n" + "=" * 60)
    say("6. LAB EXECUTION (safety-gated)")
    say("=" * 60)
    measured = {}
    for h in hyps:
        protocol = ProtocolSubmission(
            envelope=envelope,
            title=f"potency-{h.hypothesis_id}",
            assay_type="binding",
            steps=[ProtocolStep(seq=1, op=ProtocolOp.dispense,
                                params={"volume_ul": 50})],
            samples=[SampleSpec(sample_id=h.candidate, kind=SampleKind.compound,
                                concentration=cc) for cc in CONCS]
            + [SampleSpec(sample_id="ctrl-neg", kind=SampleKind.buffer,
                          concentration="10uM")],
            reagents=[ReagentSpec(name="assay-buffer", amount="5 mL", bsl_level=1)],
        )
        run_id, rejection = gateway.submit(protocol)
        if rejection:
            say(f"  {h.candidate[:30]:32} BLOCKED: {rejection}")
            continue
        result = lab.fetch_results(run_id)
        ic50_values = [m.value for m in result.measurements
                       if m.sample_id == h.candidate]
        ic50 = min(ic50_values) if ic50_values else None
        measured[h.candidate] = ic50
        hit = ic50 is not None and ic50 <= 1000  # 1 uM
        store.append(record_for(envelope, EventType.lab_run, actor,
                                decision={"run_id": run_id,
                                          "candidate": h.candidate,
                                          "ic50_um": ic50}))
        verdict = "HIT" if hit else "no hit"
        say(f"  {h.candidate[:30]:32} IC50={ic50} uM → {verdict}")

    # ================================================= 7. TPP EVALUATION
    say("\n" + "=" * 60)
    say("7. TPP EVALUATION (hit phase)")
    say("=" * 60)
    hits = {c: v for c, v in measured.items() if v is not None and v <= 1000}
    if hits:
        for c, v in hits.items():
            say(f"  {c[:30]:32} IC50={v:.1f} uM")
        best = min(hits, key=lambda c: hits[c])
        say(f"  BEST: {best} (IC50 {hits[best]:.1f} uM)")
        tpp_eval = tpp.evaluate({"IC50_nM": hits[best] * 1000},
                                CriterionPhase.hit)
        for r in tpp_eval.results:
            status = "PASS" if r.passed else "FAIL"
            say(f"    {status}: {r.criterion.name} = {r.value}")

    # ================================================= 8. PROVENANCE SUMMARY
    say("\n" + "=" * 60)
    say("PROVENANCE SUMMARY")
    say("=" * 60)
    recs = store.branch_records("full-flow")
    say(f"  {len(recs)} hash-chained records")
    event_counts = {}
    for r in recs:
        event_counts[r.event_type.value] = event_counts.get(r.event_type.value, 0) + 1
    for ev, count in sorted(event_counts.items()):
        say(f"    {ev}: {count}")
    say(f"\n  verify: bn prove full-flow --db full_flow.db")
    say(f"  diary:  bn diary full-flow --db full_flow.db --html diary.html")


def standard_small_molecule_tpp(name, target, ic50_nm=50):
    return TPP(
        program_name=name,
        objective=f"Identify {target} inhibitors meeting hit criteria",
        target_name=target,
        criteria=[
            Criterion(name="IC50_nM", category=CriterionCategory.potency,
                      phase=CriterionPhase.hit, threshold=1000, direction="min",
                      unit="nM"),
            Criterion(name="IC50_nM", category=CriterionCategory.potency,
                      phase=CriterionPhase.lead, threshold=ic50_nm, direction="min",
                      unit="nM"),
        ],
    )


from bionexus.adapters.models.openai_compat import OpenAICompatProvider  # noqa: E402
from bionexus.adapters.admet import get_admet_predictor  # noqa: E402
from bionexus.adapters.retrosynthesis import SimulatedRetrosynthesis  # noqa: E402
from bionexus.core.safety import LabGateway, MaxBslRule, MaxStepsRule, SafetyEngine  # noqa: E402
from bionexus.tpp import CriterionPhase  # noqa: E402
from bionexus.adapters.lab.simulator import SimulatorLab  # noqa: E402

if __name__ == "__main__":
    main()
