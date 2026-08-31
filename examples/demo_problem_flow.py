"""Demo: the full scientific flow, from problem statement to closed loop.

    problem + constraints
        -> multiple hypotheses proposed (portfolio)
        -> analyzed & filtered to the few worth testing
        -> FOR EACH selected hypothesis:
               proposed -> designed -> performed in lab/device
               -> event -> noticed -> analyzed -> verdict -> recommendation
               -> confirmation auto-submitted through the safety gateway

    .venv/bin/python examples/demo_problem_flow.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, "src")

from bionexus.adapters.lab.simulator import SimulatorLab
from bionexus.adapters.store.sqlite import SqliteProvenanceStore
from bionexus.core.contracts import (
    Envelope, EventType, ProtocolOp, ProtocolStep, ProtocolSubmission,
    ReagentSpec, SampleKind, SampleSpec,
)
from bionexus.core.hypothesis import (
    Constraint, ExperimentDesign, HypothesisTracker, ProblemStatement,
    SuccessCriteria,
)
from bionexus.core.interfaces import system_actor
from bionexus.core.safety import LabGateway, SafetyEngine
from bionexus.watch import AutoAnalysisAgent, DeviceMonitor

INBOX = Path(".data/inbox-problem")
NOTIFY = lambda msg: print(f"[agent] {msg}")  # noqa: E731


def main() -> None:
    store = SqliteProvenanceStore()
    actor = system_actor("problem-flow")
    tracker = HypothesisTracker(store, actor)
    gateway = LabGateway(SimulatorLab(seed=42), SafetyEngine(), store, actor)

    # ------------------------------------------------ 0. problem + constraints
    problem = tracker.define_problem(ProblemStatement(
        objective="Find a confirmed sub-20uM KRAS_G12C binder for lead development",
        context="Prior screen produced a hit list; binding assay validated at 4 concentrations.",
        constraints=[
            Constraint(name="potency", description="IC50 must be <= 20 uM",
                       kind="hard", limit=20.0, unit="uM"),
            Constraint(name="budget", description="max 2 hypotheses taken to wet-lab this round",
                       kind="hard"),
            Constraint(name="developability", description="prefer clean counterscreen profile",
                       kind="soft"),
        ],
        success_metric="confirmed IC50 <= 20 uM in orthogonal assay",
    ))
    print(f"[flow] problem defined: {problem.objective}")
    print(f"[flow] constraints: {[c.name for c in problem.constraints]}")

    # --------------------------------------- 1. portfolio of hypotheses proposed
    portfolio_specs = [
        {"statement": "C-101 binds KRAS_G12C with IC50 <= 20 uM", "candidate": "C-101",
         "assay_type": "binding", "predicted": "IC50 <= 20", "predicted_value": 20.0,
         "rationale": "covalent warhead fits switch-II pocket (model + precedent)"},
        {"statement": "C-102 binds KRAS_G12C with IC50 <= 20 uM", "candidate": "C-102",
         "assay_type": "binding", "predicted": "IC50 <= 20", "predicted_value": 20.0,
         "rationale": "scaffold hop, better developability predicted"},
        {"statement": "C-103 binds KRAS_G12C with IC50 <= 10 uM", "candidate": "C-103",
         "assay_type": "binding", "predicted": "IC50 <= 10", "predicted_value": 10.0,
         "rationale": "hash-derived analog of C-101 with extra hydrophobe",
         "criteria": SuccessCriteria(metric="ic50_um", direction="min", threshold=10.0)},
        {"statement": "C-104 shows assay interference, not true binding", "candidate": "C-104",
         "assay_type": "counterscreen", "predicted": "interference detected",
         "rationale": "aggregator-like, fluorescent"},
    ]
    # 1b. structure: mechanistic FAMILIES with variant sweeps
    families = [
        {"family": "covalent-warhead",
         "parent_statement": "A covalent warhead targeting Cys12 of KRAS_G12C inhibits binding",
         "kind": "mechanistic", "rationale": "switch-II pocket precedent",
         "variants": [portfolio_specs[0], portfolio_specs[2]]},
        {"family": "noncovalent-scaffold-hop",
         "parent_statement": "A non-covalent scaffold can achieve sub-20uM binding",
         "kind": "mechanistic", "rationale": "developability over potency",
         "variants": [portfolio_specs[1]]},
        {"family": "artifact-hypothesis",
         "parent_statement": "C-104 signal is assay interference, not binding",
         "kind": "artifact-explanation", "rationale": "fluorescent aggregator-like",
         "variants": [portfolio_specs[3]]},
    ]
    portfolio = tracker.propose_families(problem, families)
    print(f"[flow] {len(families)} families, {len(portfolio)} variant hypotheses proposed")

    # ------------------------------------------- 2. analyze + filter to few
    def score(h) -> float:
        # stand-in for the analysis step: feasibility x novelty
        base = {"C-101": 0.9, "C-102": 0.8, "C-103": 0.85, "C-104": 0.6}
        return base.get(h.candidate, 0.5)

    # diversity cap: a sweep of one family cannot crowd out different ideas
    selected = tracker.select_portfolio(problem, portfolio, score_fn=score, k=2,
                                        max_per_family=1)
    print(f"[flow] selected for testing: "
          f"{[(h.candidate, h.statement[:40] + '...') for h in selected]}")

    # ------------------------- 3. per-hypothesis: design -> perform -> notice
    for h in selected:
        protocol = ProtocolSubmission(
            envelope=Envelope(experiment_branch_id=f"problem/{problem.problem_id}"),
            title=f"test-{h.candidate}", assay_type=h.assay_type,
            steps=[ProtocolStep(seq=1, op=ProtocolOp.dispense, params={"volume_ul": 50})],
            samples=[SampleSpec(sample_id=h.candidate, kind=SampleKind.compound, concentration=k)
                     for k in ["0.5uM", "2uM", "10uM", "40uM"]]
            + [SampleSpec(sample_id="ctrl-neg", kind=SampleKind.buffer, concentration="10uM"),
               SampleSpec(sample_id="ctrl-neg2", kind=SampleKind.buffer, concentration="10uM")],
            reagents=[ReagentSpec(name="assay-buffer", amount="5 mL", bsl_level=1)],
        )
        h.design = ExperimentDesign(
            assay_type=h.assay_type, concentrations=["0.5uM", "2uM", "10uM", "40uM"],
            replicates=3, controls=["negative"], protocol_id=protocol.protocol_id)
        run_id = gateway.submit(protocol)[0]
        h.design.run_id = run_id

        # instrument "finishes" and drops its export; the agent notices on its own
        INBOX.mkdir(parents=True, exist_ok=True)
        (INBOX / f"{run_id}.csv").write_text(
            "Well ID,Compound,Conc (uM),RFU\n"
            f"A1,ctrl,10,100\nA2,ctrl,10,104\n"
            f"A3,{h.candidate},0.5,110\nA4,{h.candidate},2,145\n"
            f"A5,{h.candidate},10,289\nA6,{h.candidate},40,540\n")

    agent = AutoAnalysisAgent(notify=NOTIFY, tracker=tracker, gateway=gateway,
                              branch_id=f"problem/{problem.problem_id}")
    monitor = DeviceMonitor(INBOX, poll_secs=0.3)
    time.sleep(0.2)
    for ev in monitor.events(stop_after=len(selected)):
        agent.handle(ev)

    # ------------------------------------------------------------- summary
    print(f"\n[flow] hypothesis summary: {tracker.summary()}")
    for r in store.branch_records(f"problem/{problem.problem_id}"):
        print(f"  {r.event_type.value:22} {str(r.decision)[:80]}")


if __name__ == "__main__":
    main()
