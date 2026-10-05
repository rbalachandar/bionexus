"""Eval harness — fixed tasks, ground truth, one command -> score.

Every task runs a REAL campaign (autoloop + SimulatorLab + provenance store)
and then scores agent behavior against the lab's seeded ground truth. The
claim "the agent does science" is only allowed in the README for as long as
these numbers say so.

Tasks are offline and deterministic given the lab seed (P8). Scores are
0..1 with a pass threshold; the leaderboard is regenerated on every run.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

PASS_THRESHOLD = 0.7


@dataclass
class TaskResult:
    task_id: str
    description: str
    score: float                 # 0..1
    passed: bool
    metrics: dict[str, Any] = field(default_factory=dict)
    notes: str = ""


@dataclass
class Task:
    task_id: str
    description: str
    run: Callable[[], TaskResult]
    suite: str = "epistemics"
    optional: bool = False      # optional tasks SKIP (not fail) when unavailable


TASKS: list[Task] = []


def register(task_id: str, description: str, suite: str = "epistemics",
             optional: bool = False):
    def deco(fn):
        TASKS.append(Task(task_id, description, fn, suite, optional))
        return fn
    return deco


# --------------------------------------------------------------- campaign

def run_offline_campaign(compounds: list[str], threshold_um: float,
                         k: int, seed: int, inbox: Path,
                         specs: list[dict] | None = None,
                         flywheel=None, rounds: int = 1):
    """Execute a real dose-response campaign; return (report, lab, records).
    `specs` overrides the default bare-hypothesis set (for falsifiability
    tasks that need richer hypotheses)."""
    import shutil
    shutil.rmtree(inbox, ignore_errors=True)
    inbox.mkdir(parents=True, exist_ok=True)

    from bionexus.adapters.lab.simulator import SimulatorLab
    from bionexus.adapters.store.sqlite import SqliteProvenanceStore
    from bionexus.autoloop import run_campaign, CampaignConfig
    from bionexus.core.hypothesis import Constraint, ProblemStatement

    lab = SimulatorLab(seed=seed)
    store = SqliteProvenanceStore()          # in-memory, deterministic
    problem = ProblemStatement(
        objective=f"identify compounds with IC50 <= {threshold_um:g} uM",
        constraints=[Constraint(name="potency", description="d", kind="hard",
                                limit=threshold_um, unit="uM")])
    cfg = CampaignConfig(
        problem=problem,
        hypotheses=specs if specs is not None else [
            {"statement": f"{c} binds", "candidate": c,
             "assay_type": "binding", "predicted": f"<= {threshold_um:g}",
             "predicted_value": threshold_um, "rationale": "eval"}
            for c in compounds],
        k=k, rounds=rounds, autonomy="act", inbox=str(inbox), poll_secs=0.05,
        flywheel=flywheel if flywheel is not None else
        __import__("bionexus.flywheel", fromlist=["Flywheel"]).Flywheel(
            ":memory:"))
    report = run_campaign(cfg, lab, store)
    branch = f"problem/{report.problem_id}"
    return report, lab, store.branch_records(branch)


def verdict_records(recs) -> dict[str, dict]:
    """candidate -> latest verdict decision from the provenance chain."""
    out: dict[str, dict] = {}
    for r in recs:
        if r.event_type.value in ("hypothesis_validated",
                                  "hypothesis_invalidated",
                                  "hypothesis_inconclusive",
                                  "hypothesis_tested"):
            cand = (r.artifact.metadata if r.artifact else {}).get("candidate")
            d = r.decision or {}
            if cand and (d.get("verdict") or d.get("observed") is not None):
                out[cand] = dict(d)
    return out


# ---------------------------------------------------------------- scoring

def score_hit_recovery(verdicts: dict, truth: dict[str, float],
                       threshold_um: float) -> TaskResult:
    """Per-compound call quality vs seeded truth.

    Confident-and-correct = 1.0, honest abstention (inconclusive) = 0.5,
    confident-and-wrong = 0. Abstention is credited, not punished — a
    system that never says 'borderline' on borderline data is lying.
    """
    credit, detail = 0.0, {}
    judged = 0
    for c, d in verdicts.items():
        t = truth.get(c)
        if t is None:
            continue
        judged += 1
        v = d.get("verdict")
        if v in ("validated", "confirmed"):
            got = 1.0 if t <= threshold_um else 0.0
        elif v in ("invalidated", "refuted"):
            got = 1.0 if t > threshold_um else 0.0
        elif v == "inconclusive":
            got = 0.5
        else:
            got = 0.0
        credit += got
        detail[c] = {"verdict": v, "true_ic50": round(t, 2), "credit": got}
    score = round(credit / judged, 3) if judged else 0.0
    return TaskResult("hit-recovery", "per-compound calls vs seeded truth "
                                      "(abstention = half credit)",
                      score, score >= PASS_THRESHOLD,
                      {"judged": judged, "calls": detail},
                      "1.0 confident-correct · 0.5 honest abstain · 0 wrong")


def score_verdict_honesty(verdicts: dict) -> TaskResult:
    """A verdict whose 95% CI straddles the threshold MUST be inconclusive."""
    violations = 0
    straddles = 0
    for c, d in verdicts.items():
        ci, thr, obs = d.get("observed_ci"), d.get("threshold"), d.get("observed")
        if not ci or thr is None or obs is None:
            continue
        lo, hi = ci
        straddles += 1 if lo <= thr <= hi else 0
        if ((lo <= thr <= hi) and d.get("verdict") in ("validated", "invalidated",
                                                       "confirmed", "refuted")):
            violations += 1
    score = 1.0 if straddles == 0 else round(1 - violations / straddles, 3)
    notes = (f"{straddles} borderline CIs, {violations} overconfident verdicts"
             if straddles else "VACUOUS — no straddles, task tested nothing")
    return TaskResult("verdict-honesty", "CI straddling threshold => inconclusive",
                      score, score >= PASS_THRESHOLD,
                      {"straddling_ci": straddles, "violations": violations},
                      notes)


def score_confirmation_coverage(verdicts: dict) -> TaskResult:
    """Nothing may claim CONFIRMED without a recorded agreement check."""
    confirmed = {c: d for c, d in verdicts.items()
                 if d.get("verdict") == "confirmed"}
    backed = {c for c, d in confirmed.items()
              if (d.get("confirmation") or {}).get("agreed") is not None}
    score = round(len(backed) / len(confirmed), 3) if confirmed else 0.0
    return TaskResult("confirmation-coverage",
                      "confirmed verdicts carry a recorded agreement",
                      score, score >= PASS_THRESHOLD,
                      {"confirmed": len(confirmed), "with_agreement": len(backed)},
                      "no confirmations at all -> 0 (mechanism unused)")


# ------------------------------------------------------- model benchmarking

def run_model_task(dataset: str, min_spearman: float = 0.3) -> TaskResult:
    """Score the offline policy ladder (Random/Mean/CharRidge) on a cached
    MoleculeNet dataset. Passes when the learned policy clears the bar and
    beats the floor. Degrades to a skipped-style 0 with the reason."""
    from pathlib import Path

    from bionexus.adapters.data.moleculenet import MoleculeNetDataset
    from bionexus.benchmark import (CharRidgePolicy, MeanPolicy, RandomPolicy,
                                    run_benchmark)

    cache = Path(".data")
    if not (cache / f"{dataset}.csv").exists():
        return TaskResult(f"model-{dataset}",
                          f"policy ladder on MoleculeNet {dataset}", 0.0,
                          False, notes=f"SKIPPED — {dataset}.csv not cached "
                                       f"(run with network once to fetch)")
    ds = MoleculeNetDataset(dataset, cache_dir=str(cache), limit=8000)
    res = run_benchmark(ds, [RandomPolicy(), MeanPolicy(),
                             CharRidgePolicy(dim=256)],
                        split="scaffold", seeds=(0, 1, 2))
    classification = res.get("task") == "classification"
    metric = "roc_auc" if classification else "spearman"

    def val(entry: dict) -> float | None:
        v = entry.get(f"{metric}_mean", entry.get(metric))
        if isinstance(v, str):                       # "0.74±0.02"
            v = float(v.split("±")[0])
        return v if isinstance(v, (int, float)) else None

    pols = res.get("policies", {})
    floor = val(pols.get("random", {})) or 0.0
    best_name, best = "", None
    for name, entry in pols.items():
        s = val(entry)
        if s is not None and (best is None or s > best):
            best_name, best = name, s
    if best is None:
        return TaskResult(f"model-{dataset}", "", 0.0, False,
                          notes=f"no {metric} produced")
    if classification:                               # AUC bar, not rho bar
        floor, min_spearman = max(floor, 0.5), 0.65
    score = max(0.0, min(1.0, (best - (floor + 0.05)) / 0.4))
    passed = best >= min_spearman and best > floor
    return TaskResult(f"model-{dataset}",
                      f"policy ladder beats floor on {dataset}",
                      round(score, 3), passed,
                      {"best_policy": best_name, metric: round(best, 4),
                       "floor_random": round(floor, 4)},
                      f"{best_name} {metric}={best:.3f} (floor "
                      f"{floor:.3f}, bar {min_spearman})")


def run_split_pinned_task(dataset: str, min_score: float = 0.3) -> TaskResult:
    """Policy ladder on a frozen TDC ADMET dataset with CANONICAL scaffold
    splits: fit on train_val, score on the held-out test fold (the same
    folds the TDC leaderboard uses). No network, no re-splitting — the
    generalization test is the one the community agreed on."""
    from bionexus.adapters.data.admet import ADMETSplitDataset
    from bionexus.benchmark import (CharRidgePolicy, MeanPolicy, RandomPolicy,
                                    roc_auc, spearman)

    ds = ADMETSplitDataset(dataset)
    train = list(ds.train())
    test = list(ds.test())
    classification = ds.task == "classification"
    metric = "roc_auc" if classification else "spearman"

    results = {}
    floor_name = "random"
    for pol in (RandomPolicy(), MeanPolicy(), CharRidgePolicy(dim=256)):
        pol.fit(train)
        pred = [pol.predict(smi) for smi, _ in test]
        truth = [y for _, y in test]
        score_auc = roc_auc(pred, truth) if classification \
            else spearman(pred, truth)
        results[getattr(pol, "name", "?")] = score_auc
    floor = results.get("random", results.get(floor_name, 0.0)) or 0.0
    best_name = max(results, key=lambda k: results[k])
    best = results[best_name]
    if classification:
        floor = max(floor, 0.5)
    score = max(0.0, min(1.0, (best - (floor + 0.05)) / 0.4))
    passed = best >= min_score and best > floor
    return TaskResult(f"model-{dataset}",
                      "policy ladder on frozen TDC ADMET scaffold split",
                      round(score, 3), passed,
                      {"policies": {k: round(v, 4) for k, v in results.items()},
                       "best_policy": best_name, metric: round(best, 4),
                       "floor_random": round(floor, 4),
                       "n_train": len(train), "n_test": len(test),
                       "splits": "TDC canonical scaffold (20% test)"},
                      f"{best_name} {metric}={best:.3f} (floor {floor:.3f}, "
                      f"bar {min_score}, folds: TDC scaffold)")


def _evals_dir() -> Path:
    """Locate the committed eval artifacts (evals/results.json,
    leaderboard.md). An explicit BIONEXUS_EVALS_DIR is HONORED EVEN IF
    EMPTY (so callers/tests can pin the read-model to a directory);
    otherwise best-effort: CWD, then repo root derived from this package
    (src/bionexus/evals/harness.py -> parents[3] == repo root)."""
    import os
    env = os.environ.get("BIONEXUS_EVALS_DIR")
    if env:
        return Path(env)
    cand = [Path("evals")]
    try:
        cand.append(Path(__file__).resolve().parents[3] / "evals")
    except IndexError:
        pass
    for c in cand:
        if (c / "results.json").exists() or (c / "leaderboard.md").exists():
            return c
    return cand[0]


def leaderboard_payload() -> dict[str, Any]:
    """Workbench-ready read-model of the LAST eval run (the committed
    artifacts), NOT a live re-run — `bn eval` writes these; this reads
    them. Degrades gracefully to available=False when the artifacts are
    absent so /api/evals never 500s on a fresh checkout.

    The honesty framing lives here on purpose: a task that scores BELOW
    1.0 while still passing is the harness refusing to overcredit —
    'honest_abstain' tasks are surfaced separately from a clean sweep."""
    d = _evals_dir()
    res_p, md_p = d / "results.json", d / "leaderboard.md"
    if not res_p.exists():
        return {"available": False,
                "reason": "no eval artifacts yet — run `bn eval`",
                "tasks": [], "mean": None, "all_pass": None,
                "pass_bar": PASS_THRESHOLD}
    try:
        raw = json.loads(res_p.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        return {"available": False, "reason": f"unreadable results.json: {exc}",
                "tasks": [], "mean": None, "all_pass": None,
                "pass_bar": PASS_THRESHOLD}

    suite_map: dict[str, str] = {}
    try:
        from bionexus.evals import tasks as _tasks  # registers suite
        suite_map = {t.task_id: t.suite for t in TASKS}
    except Exception:
        pass

    tasks = []
    for r in raw:
        skipped = str(r.get("notes", "")).startswith("SKIPPED")
        score = float(r.get("score", 0.0))
        tasks.append({
            "task": r.get("task", "?"),
            "suite": suite_map.get(r.get("task", ""), "epistemics"),
            "score": round(score, 3),
            "passed": bool(r.get("passed")) and not skipped,
            "skipped": skipped,
            "honest_deduction": (not skipped and score < 1.0
                                 and bool(r.get("passed"))),
            "notes": r.get("notes", ""),
            "duration_s": (r.get("metrics") or {}).get("duration_s"),
        })
    scored = [t for t in tasks if not t["skipped"]]
    mean = (round(sum(t["score"] for t in scored) / len(scored), 3)
            if scored else None)
    all_pass = bool(scored) and all(t["passed"] for t in scored)
    run_line = ""
    if md_p.exists():
        for line in md_p.read_text().splitlines():
            if line.startswith("Run "):
                run_line = line
                break
    return {"available": True, "run_line": run_line, "mean": mean,
            "all_pass": all_pass, "pass_bar": PASS_THRESHOLD,
            "n_tasks": len(tasks),
            "honest_deductions": [t["task"] for t in tasks
                                  if t["honest_deduction"]],
            "failing": [t["task"] for t in scored if not t["passed"]],
            "tasks": tasks}
