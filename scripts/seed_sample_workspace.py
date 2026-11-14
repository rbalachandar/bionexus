#!/usr/bin/env python3
"""Seed a local workbench with two real (simulated-lab) campaigns so the UI has
something to show: a portfolio-score campaign with abstentions, and an
expected-improvement campaign with an applicability-domain veto.

    make sample           # seeds ./.sample and starts the workbench on :8000

Everything is produced by the real campaign engine against the virtual lab
(labelled simulated); nothing is mocked in the UI or the API.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
target = Path(sys.argv[1] if len(sys.argv) > 1 else ".sample").resolve()
target.mkdir(parents=True, exist_ok=True)
os.chdir(target)
os.environ["PROEF_DATA_DIR"] = str(target / ".data")
sys.path.insert(0, str(ROOT / "src"))

from proef.adapters.lab.simulator import SimulatorLab  # noqa: E402
from proef.adapters.store.sqlite import SqliteProvenanceStore  # noqa: E402
from proef.autoloop import CampaignConfig, run_campaign  # noqa: E402
from proef.core.hypothesis import Constraint, ProblemStatement  # noqa: E402
from proef.flywheel import Flywheel  # noqa: E402
from proef.paths import DATA_DIR  # noqa: E402
from proef.wizard_store import WizardStore  # noqa: E402

store = SqliteProvenanceStore("proef.db")
ws = WizardStore()


def campaign(eid, objective, specs, seed, acquisition=None, k=3, rounds=2, lab_seed=3):
    hyps = [{"statement": f"{c} binds the ATP pocket", "candidate": c,
             "assay_type": "binding", "predicted": f"{pv} uM",
             "predicted_value": pv,
             "mechanism": "hinge-binder with an electrophilic warhead",
             "metadata": {"predicted_sd": 0.25, "extrapolation": ad,
                          "ad_note": "nearest training neighbour Tanimoto 0.31 < 0.5" if ad else ""}}
            for c, pv, ad in specs]
    problem = ProblemStatement(objective=objective, constraints=[
        Constraint(name="potency", description="IC50", kind="hard",
                   limit=20.0, unit="uM")])
    cfg = CampaignConfig(problem=problem, hypotheses=hyps, k=k, rounds=rounds,
                         autonomy="act", inbox=str(DATA_DIR / "inbox"),
                         poll_secs=0.05, seed=seed, acquisition=acquisition,
                         flywheel=Flywheel(":memory:"))
    rep = run_campaign(cfg, SimulatorLab(seed=lab_seed), store,
                       notify=lambda m: None)
    ws.register_agent(eid, objective, log="", autonomy="act")
    ws.link_problem(eid, rep.problem_id)
    print(f"seeded {eid}: {rep.verdicts}")
    return rep.problem_id


from proef import program as programs  # noqa: E402


def program(name, objective, campaigns):
    """A program = the goal (one gate); its campaigns are runs against it."""
    programs.save_program_record(
        {"program": name, "custom": True, "objective": objective,
         "modality": "small molecule", "metric": "ic50_um", "direction": "min",
         "gate_value": 20, "unit": "µM", "mode": "autonomous"})
    for eid, question, root in campaigns:
        programs.link_leaf(name, eid, campaign_root=root, question=question,
                           status="verdict_recorded")


if not ws.get("cmp-egfr-1"):
    q1 = "Find a confirmed sub-20 µM EGFR binder"
    r1 = campaign("cmp-egfr-1", q1,
                  [("EG-01", 2.0, True), ("EG-02", 5.0, False), ("EG-03", 8.0, False),
                   ("EG-04", 11.0, False), ("EG-05", 90.0, False)], seed=5)
    q2 = "EGFR follow-up: extend the series around the first hits"
    r2 = campaign("cmp-egfr-2", q2,
                  [("EG-06", 4.0, False), ("EG-07", 7.0, False), ("EG-08", 13.0, False),
                   ("EG-09", 30.0, False)], seed=11, k=2, rounds=2, lab_seed=5)
    program("EGFR hit finding",
            "Find a small molecule that inhibits EGFR below 20 µM, confirmed by an orthogonal assay.",
            [("cmp-egfr-1", q1, r1), ("cmp-egfr-2", q2, r2)])
if not ws.get("cmp-kras-2"):
    q3 = "Rank KRAS G12C candidates by potency (EI batch selection)"
    r3 = campaign("cmp-kras-2", q3,
                  [("KR-01", 3.0, False), ("KR-02", 6.0, False), ("KR-03", 9.0, False),
                   ("KR-04", 14.0, False), ("KR-05", 1.5, True), ("KR-06", 70.0, False)],
                  seed=7, acquisition="bo-ei", k=2, rounds=3, lab_seed=4)
    program("KRAS G12C leads",
            "Identify covalent KRAS G12C leads with IC50 below 20 µM, chosen by expected improvement.",
            [("cmp-kras-2", q3, r3)])
print(f"sample workspace ready in {target}")
