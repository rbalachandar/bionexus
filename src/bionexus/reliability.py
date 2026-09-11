"""Model-variance reporting — a verdict from one seed is a sample, not a fact.

Runs the same campaign spec across N lab seeds and reports verdict stability.
Unstable verdicts are the honest signal that the evidence is borderline —
the UI shows the spread instead of hiding it.
"""
from __future__ import annotations

import shutil
from collections import Counter
from pathlib import Path


def verdict_spread(specs: list[dict], threshold_um: float, k: int,
                   lab_seed: int = 5,
                   noise_variants: tuple[int, ...] = (0, 1, 2),
                   inbox: str | Path = ".data/variance-inbox") -> dict:
    """Same ground truth (one lab seed), N measurement-noise draws. A verdict
    that flips across noise variants is BORDERLINE EVIDENCE, not a flaky
    pipeline — that is the number a scientist should see."""
    from bionexus.adapters.lab.simulator import SimulatorLab
    from bionexus.adapters.store.sqlite import SqliteProvenanceStore
    from bionexus.autoloop import CampaignConfig, run_campaign
    from bionexus.core.hypothesis import Constraint, ProblemStatement

    per: dict[str, list[str | None]] = {}
    for nv in noise_variants:
        box = Path(inbox)
        shutil.rmtree(box, ignore_errors=True)
        box.mkdir(parents=True, exist_ok=True)
        problem = ProblemStatement(
            objective="variance probe",
            problem_id=f"var-{nv}",
            constraints=[Constraint(name="potency", description="d",
                                    kind="hard", limit=threshold_um,
                                    unit="uM")])
        cfg = CampaignConfig(
            problem=problem, hypotheses=[dict(s) for s in specs], k=k,
            autonomy="act", inbox=str(box), poll_secs=0.05,
            noise_variant=nv)
        report = run_campaign(cfg, SimulatorLab(seed=lab_seed),
                              SqliteProvenanceStore())
        for cand in [s["candidate"] for s in specs]:
            per.setdefault(cand, []).append(report.verdicts.get(cand))
    stable = {c: (len(set(v)) == 1) for c, v in per.items()}
    frac = (sum(stable.values()) / len(stable)) if stable else 0.0
    return {"per_candidate": per, "stable": stable,
            "stability": round(frac, 3), "lab_seed": lab_seed,
            "noise_variants": list(noise_variants)}
