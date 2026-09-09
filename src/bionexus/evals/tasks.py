"""The task suite. Add tasks here; the harness scores them."""
from __future__ import annotations

from pathlib import Path

from bionexus.evals.harness import (register, run_offline_campaign,
                                    score_confirmation_coverage,
                                    score_hit_recovery, score_verdict_honesty,
                                    verdict_records)

INBOX = Path(".data/evals/inbox")
COMPOUNDS = [f"E-{i:02d}" for i in range(1, 13)]


@register("hit-recovery",
          "screen 12 compounds, k=6; validated set must match seeded truth")
def _t_hit_recovery():
    threshold, seed = 20.0, 11
    report, lab, recs = run_offline_campaign(COMPOUNDS, threshold, 6, seed, INBOX)
    verdicts = verdict_records(recs)
    truth = {}
    for c, d in verdicts.items():
        run_id = d.get("evidence_run_id")
        if run_id:
            truth[c] = lab.true_ic50_um(run_id, c)
    return score_hit_recovery(verdicts, truth, threshold)


@register("verdict-honesty",
          "threshold set exactly at one compound's TRUE IC50 (the harness "
          "knows it): the agent must abstain on the compound sitting on the bar")
def _t_verdict_honesty():
    # potency is seed-stable per compound, so the harness can place the bar
    # exactly on a true value without peeking into the campaign
    from bionexus.adapters.lab.simulator import SimulatorLab
    seed = 11
    tight = SimulatorLab(seed=seed).true_ic50_um("any", "E-03")
    _, lab, recs = run_offline_campaign(COMPOUNDS, tight, 12, seed, INBOX)
    result = score_verdict_honesty(verdict_records(recs))
    result.notes = (f"bar at E-03's true IC50 ({tight:.2f} uM); "
                    + result.notes)
    return result


@register("confirmation-coverage",
          "every CONFIRMED verdict must carry a recorded agreement check")
def _t_confirmation():
    _, _, recs = run_offline_campaign(COMPOUNDS, 20.0, 6, 42, INBOX)
    return score_confirmation_coverage(verdict_records(recs))


# ------------------------------------------------------------- models suite

@register("model-lipophilicity", "policy ladder on MoleculeNet Lipophilicity",
          suite="models", optional=True)
def _m_lipo():
    from bionexus.evals.harness import run_model_task
    return run_model_task("lipophilicity", min_spearman=0.3)


@register("model-esol", "policy ladder on MoleculeNet ESOL",
          suite="models", optional=True)
def _m_esol():
    from bionexus.evals.harness import run_model_task
    return run_model_task("esol", min_spearman=0.5)


@register("model-hiv", "policy ladder on MoleculeNet HIV (classification)",
          suite="models", optional=True)
def _m_hiv():
    from bionexus.evals.harness import run_model_task
    return run_model_task("hiv", min_spearman=0.3)


# ------------------------------------------------------- reproductions suite

@register("repro-cs02-az3246", "blind reproduction of the AZ3246/HPK1 paper "
          "(contamination-free)", suite="reproductions", optional=True)
def _r_cs02():
    return _run_case_study("02-az3246-hpk1")


@register("repro-cs03-flow", "multi-paper flow validation (quantitative rows, "
          "no LLM)", suite="reproductions", optional=True)
def _r_cs03():
    return _run_case_study("03-multi-paper", args=["run.py"])


def _run_case_study(dirname: str, args=None):
    import os
    import subprocess
    import sys
    from pathlib import Path

    from bionexus.evals.harness import TaskResult
    if os.environ.get("BIONEXUS_EVAL_REPRO") != "1":
        return TaskResult(f"repro-{dirname}", f"case study {dirname}", 0.0,
                          True, notes="SKIPPED (opt-in) — set "
                          "BIONEXUS_EVAL_REPRO=1 to run; network-heavy, "
                          "~10 min per study")
    d = Path("case-studies") / dirname
    script = d / (args[0] if args else "run.py")
    if not script.exists():
        return TaskResult(f"repro-{dirname}", "", 0.0, False,
                          notes="SKIPPED — script missing")
    try:
        r = subprocess.run([sys.executable, script.name], cwd=str(d),
                           capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        return TaskResult(f"repro-{dirname}", "", 0.0, False,
                          notes="SKIPPED — timeout (needs network?)")
    ok = r.returncode == 0 and "COMPLETE" in (r.stdout + r.stderr)
    return TaskResult(f"repro-{dirname.split('-')[0]}",
                      f"case study {dirname} rerun", 1.0 if ok else 0.0, ok,
                      {"returncode": r.returncode},
                      "reproduced" if ok else
                      f"FAILED — {r.stdout.strip()[-120:] or r.stderr.strip()[-120:]}")


@register("falsifiability-tiebreak",
          "equal-scored hypotheses: the k selected must be the mechanistic, "
          "refutable, cited ones (explanatory power breaks ties)")
def _t_falsifiability():
    from bionexus.evals.harness import TaskResult
    k = 4
    specs = []
    for i, c in enumerate(COMPOUNDS):
        rich = i % 2 == 0
        spec = {"statement": f"{c} binds", "candidate": c,
                "assay_type": "binding", "predicted": "<= 20",
                "predicted_value": 20.0, "rationale": "eval"}
        if rich:
            spec.update(mechanism="covalent engagement of catalytic Cys",
                        refutation_condition="loss of activity upon Cys mutation",
                        citation="PMID:00000000")
        specs.append(spec)
    rich_set = {s["candidate"] for s in specs if s.get("mechanism")}
    _, _, recs = run_offline_campaign(COMPOUNDS, 20.0, k, 11, INBOX, specs=specs)
    selected = set()
    for r in recs:
        if r.event_type.value == "hypotheses_filtered":
            for dec in (r.decision or {}).get("decisions", []):
                if dec.get("selected"):
                    selected.add(dec.get("hypothesis_id"))
    # map ids->candidates via proposed records
    id2cand = {}
    for r in recs:
        if r.event_type.value == "hypothesis_proposed" and r.artifact:
            id2cand[r.artifact.artifact_id] = \
                (r.artifact.metadata or {}).get("candidate")
    picked = {id2cand.get(i) for i in selected}
    frac = len(picked & rich_set) / len(picked) if picked else 0.0
    return TaskResult("falsifiability-tiebreak",
                      "explanatory power breaks portfolio ties",
                      round(frac, 3), frac == 1.0,
                      {"selected": sorted(str(p) for p in picked),
                       "rich_candidates": sorted(rich_set)},
                      "all k picks must be mechanistic+cited")
