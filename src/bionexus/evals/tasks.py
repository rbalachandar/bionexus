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


@register("adaptive-dose-design",
          "3-well Bayesian sequential design must beat the fixed 4-point "
          "series on IC50 accuracy (and report its own CI coverage honestly)")
def _t_adaptive():
    import math
    import random

    from bionexus.adaptive import run_adaptive_series
    from bionexus.evals.harness import TaskResult
    from bionexus.labread import fit_ic50_ci

    rmax, sigma = 500.0, 15.0
    rng = random.Random(2027)
    trues = [10 ** rng.uniform(math.log10(0.3), math.log10(150))
             for _ in range(16)]
    wins, errs_a, errs_f, covered = 0, [], [], 0
    for i, true in enumerate(trues):
        est, ci, wells = run_adaptive_series(true, rmax, sigma, 3,
                                             random.Random(i))
        noise = random.Random(100 + i)
        pts = [(c, max(0.0, rmax / (1 + true / c) + noise.gauss(0, sigma)))
               for c in (0.5, 2.0, 10.0, 40.0)]
        f = fit_ic50_ci(pts, None)
        ea = abs(math.log10(est / true))
        ef = abs(math.log10(f["ic50"] / true)) if f and f["ic50"] else 1.0
        errs_a.append(ea)
        errs_f.append(ef)
        wins += 1 if ea <= ef else 0
        covered += 1 if ci[0] <= true <= ci[1] else 0
    mean_a, mean_f = sum(errs_a) / 16, sum(errs_f) / 16
    score = round(wins / 16, 3)
    passed = score >= 0.6 and mean_a < mean_f
    return TaskResult("adaptive-dose-design",
                      "adaptive beats fixed on per-compound accuracy",
                      score, passed,
                      {"wins": f"{wins}/16", "mean_err_adaptive_3well": round(mean_a, 3),
                       "mean_err_fixed_4well": round(mean_f, 3),
                       "ci_coverage": f"{covered}/16"},
                      f"3 wells beat 4: err {mean_a:.3f} vs {mean_f:.3f}; "
                      f"CI coverage {covered}/16 (nominal 15.2)")


@register("flywheel-memory",
          "a family invalidated in campaign 1 must be discounted in "
          "campaign 2's portfolio selection (negative results steer)")
def _t_flywheel():
    from bionexus.evals.harness import TaskResult, run_offline_campaign
    from bionexus.flywheel import Flywheel

    fw = Flywheel(":memory:")
    # campaign 1: impossible bar (0.001 uM) on family "scaffold-A"
    specs_a = [{"statement": f"X-{i} binds", "candidate": f"X-{i}",
                "assay_type": "binding", "predicted": "<=0.001",
                "predicted_value": 0.001, "family": "scaffold-A"}
               for i in (1, 2)]
    run_offline_campaign([s["candidate"] for s in specs_a], 0.001, 2, 5,
                         INBOX, specs=specs_a)
    # the temp flywheel above is campaign-internal; replay its outcomes:
    # simpler — submit directly what campaign 1 proved
    # (campaign 1 used its own default flywheel; we record equivalently)
    # NOTE: run_offline_campaign wires cfg.flywheel; pass ours in:
    # (re-run with injected flywheel so the memory is isolated)
    from bionexus.autoloop import CampaignConfig, run_campaign
    from bionexus.adapters.lab.simulator import SimulatorLab
    from bionexus.adapters.store.sqlite import SqliteProvenanceStore
    from bionexus.core.hypothesis import Constraint, ProblemStatement
    import shutil
    inbox = INBOX
    shutil.rmtree(inbox, ignore_errors=True); inbox.mkdir(parents=True)
    problem = ProblemStatement(
        objective="o", problem_id="prob-f1",
        constraints=[Constraint(name="potency", description="d", kind="hard",
                                limit=0.001, unit="uM")])
    run_campaign(CampaignConfig(
        problem=problem, hypotheses=specs_a, k=2, autonomy="act",
        inbox=str(inbox), poll_secs=0.05, flywheel=fw),
        SimulatorLab(seed=5), SqliteProvenanceStore())
    ruled_out = {n["candidate"] for n in fw.negative_summary()}
    if not ruled_out:
        return TaskResult("flywheel-memory", "negative results steer later "
                          "selection", 0.0, False,
                          notes="campaign 1 produced no recorded negatives")
    # campaign 2: dead family A vs fresh B/C (diversity cap takes 1/family,
    # so the test is that A gets NO slot at all)
    mixed = ([{"statement": f"X-{i} binds", "candidate": f"X-{i}",
               "assay_type": "binding", "predicted": "<=20",
               "predicted_value": 20.0, "family": "scaffold-A"}
              for i in (3, 4)]
             + [{"statement": f"Y-{i} binds", "candidate": f"Y-{i}",
                 "assay_type": "binding", "predicted": "<=20",
                 "predicted_value": 20.0, "family": "scaffold-B"}
                for i in (1, 2)]
             + [{"statement": f"Z-{i} binds", "candidate": f"Z-{i}",
                 "assay_type": "binding", "predicted": "<=20",
                 "predicted_value": 20.0, "family": "scaffold-C"}
                for i in (1, 2)])
    from bionexus.autoloop import run_campaign as rc2
    import shutil as sh
    sh.rmtree(inbox, ignore_errors=True); inbox.mkdir(parents=True)
    problem2 = ProblemStatement(
        objective="o", problem_id="prob-f2",
        constraints=[Constraint(name="potency", description="d", kind="hard",
                                limit=20.0, unit="uM")])
    report2 = rc2(CampaignConfig(
        problem=problem2, hypotheses=mixed, k=2, autonomy="act",
        inbox=str(inbox), poll_secs=0.05, flywheel=fw),
        SimulatorLab(seed=6), SqliteProvenanceStore())
    picks_a = sum(1 for c in report2.selected if c.startswith("X-"))
    score = round(1 - picks_a / max(1, len(report2.selected)), 3)
    return TaskResult("flywheel-memory",
                      "failed family discounted in next portfolio",
                      score, score == 1.0,
                      {"selected": report2.selected,
                       "ruled_out_campaign1": sorted(ruled_out),
                       "family_A_prior": fw.family_prior("scaffold-A")},
                      "the dead family must get zero lab slots")


@register("verdict-stability",
          "same hypotheses across 3 lab seeds: what fraction of verdicts "
          "are stable? (unstable = borderline evidence, honestly reported)")
def _t_stability():
    from bionexus.evals.harness import TaskResult
    from bionexus.reliability import verdict_spread
    specs = [{"statement": f"S-{i} binds", "candidate": f"S-{i}",
              "assay_type": "binding", "predicted": "<=20",
              "predicted_value": 20.0} for i in (1, 2, 3, 4)]
    out = verdict_spread(specs, 20.0, k=4, lab_seed=5,
                         noise_variants=(0, 1, 2),
                         inbox=INBOX.parent / "variance")
    score = out["stability"]
    return TaskResult("verdict-stability",
                      "verdicts stable across lab seeds", score,
                      score >= 0.5,
                      {"stability": score, "per_candidate": out["per_candidate"]},
                      "unstable verdicts flag borderline evidence — reported, "
                      "not hidden")
