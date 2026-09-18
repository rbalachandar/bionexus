"""Materials DMTA runner — Design-of-experiments property sweep.

For material modality programs: Design a formulation sweep, Make each
formulation, Test it on the sweep rig, Analyze the best against the
program gate. Produces the same provenance shape as every other
campaign (problem_defined -> lab_run -> verdict -> review), so the
workbench, `bn prove`, and the reviewer treat it identically.

Gate direction is honored: for max-metrics (tensile strength, t_half,
yield) a sweep is validated when its best value MEETS OR EXCEEDS the
gate; the reviewer reads the recorded direction.
"""
from __future__ import annotations

import random
import uuid
from pathlib import Path

from bionexus.assays.properties import read_property_sweep
from bionexus.assays.simulate import simulate_property_sweep
from bionexus.core.contracts import (Envelope, EventType, Artifact,
                                     ArtifactKind)
from bionexus.core.interfaces import record_for, system_actor


def run_materials_sweep(objective: str, formulations: list[float],
                        gate: float, unit: str = "MPa",
                        metric: str = "tensile_strength_mpa",
                        param: str = "crosslinker_pct",
                        direction: str = "max",
                        store=None, exports_dir: str = ".data/exports",
                        seed: int | None = None,
                        notify=None) -> dict:
    say = notify or (lambda m: print(f"[materials] {m}"))
    store = store if store is not None else __import__(
        "bionexus.adapters.store.sqlite",
        fromlist=["SqliteProvenanceStore"]).SqliteProvenanceStore()
    problem_id = f"mat-{uuid.uuid4().hex[:6]}"
    branch = f"problem/{problem_id}"
    rng = random.Random(seed if seed is not None else uuid.uuid4().hex)

    def rec(event_type, decision, actor="materials"):
        return store.append(record_for(
            Envelope(experiment_branch_id=branch),
            EventType(event_type) if isinstance(event_type, str)
            else event_type, system_actor(actor), decision=decision))

    # Design: the registered problem, honestly shaped for this modality
    rec("problem_defined", {
        "problem_id": problem_id, "objective": objective,
        "modality": "material",
        "constraints": [{"name": metric,
                         "description": f"{metric} {direction} {gate:g}",
                         "kind": "hard", "limit": gate, "unit": unit}],
        "success_metric": f"best {metric} meets the {gate:g} {unit} gate",
        "environment": {"kind": "materials-sweep",
                        "formulations": formulations,
                        "gate": gate, "metric": metric, "param": param}})

    cand = f"{metric} {direction} {gate:g} {unit}"
    rec("hypothesis_proposed", {
        "hypothesis_id": f"hyp-{problem_id}", "candidate": cand,
        "statement": f"{objective} — best formulation reaches {metric} "
                     f"{direction} {gate:g} {unit}",
        "rationale": "formulation sweep around the program gate"},
        actor="materials")

    # Make + Test: produce and measure each formulation (hidden true
    # optimum lives in the rig's seed — the analysis must find it)
    hidden_optimum = rng.choice(formulations) + rng.uniform(-0.4, 0.4)
    rows, truth = simulate_property_sweep(
        formulations, optimum=round(hidden_optimum, 3), seed=rng.randint(
            0, 10 ** 6), metric=metric, param=param)
    exports = Path(exports_dir)
    exports.mkdir(parents=True, exist_ok=True)
    sweep_file = exports / f"{problem_id}-sweep.csv"
    keys = list(rows[0].keys())
    sweep_file.write_text(",".join(keys) + "\n" + "\n".join(
        ",".join(str(r[k]) for k in keys) for r in rows) + "\n")
    for i, (row, x) in enumerate(zip(rows, formulations)):
        rec("lab_run", {
            "run_id": f"sweep-{i + 1:03d}",
            "title": f"formulation {x:g} {param}",
            "assay": f"{metric} sweep",
            "n_samples": 1, "replicates": 1, "n_controls": 0,
            "concentrations": [x],
            "instrument": "materials-sweep-rig",
            "instrument_version": "sweep-v1",
            "export": str(sweep_file)}, actor="materials-rig")
        say(f"produced and measured formulation {x:g} {param} "
            f"-> {row[metric]} {unit}")

    # Analyze: best formulation vs the gate (direction-aware)
    result = read_property_sweep(sweep_file, param=param, metric=metric)
    best = result["best"]
    meets = (best["value"] >= gate) if direction == "max" \
        else (best["value"] <= gate)
    verdict = "validated" if meets else "invalidated"
    rec("hypothesis_tested", {
        "hypothesis_id": f"hyp-{problem_id}", "candidate": cand,
        "verdict": None, "run_id": f"sweep-{len(formulations):03d}",
        "observed": best["value"]}, actor="analysis")
    rec("hypothesis_validated" if verdict == "validated"
        else "hypothesis_invalidated", {
        "hypothesis_id": f"hyp-{problem_id}", "candidate": cand,
        "verdict": verdict,
        "observed": best["value"],
        "observed_ci": None, "threshold": gate, "direction": direction,
        "evidence_run_id": f"sweep-{formulations.index(best['param']) + 1:03d}",
        "derivation": {"method": "property-sweep best-of",
                       "measured_by": "materials-sweep-rig",
                       "raw": f"{metric} per formulation",
                       "derived": {"metric": metric,
                                   "best_param": best["param"]}},
        "note": result["note"]}, actor="analysis")
    say(f"best: {best['param']:g} {param} at {best['value']:g} {unit} "
        f"vs gate {gate:g} -> {verdict}"
        + (f" ({result['note']})" if result["note"] else ""))

    # Reviewer: same independent audit as every other campaign
    from bionexus.reviewer import review_campaign
    review = review_campaign(store.branch_records(branch))
    rec("stage_transition", {"kind": "review_report", **review},
        actor="reviewer")
    say(f"reviewer: {review['critical']} critical / "
        f"{review['warnings']} warnings")

    return {"problem_id": problem_id, "branch": branch, "verdict": verdict,
            "best": best, "review": review,
            "truth": {"hidden_optimum": truth["true_optimum"]}}
