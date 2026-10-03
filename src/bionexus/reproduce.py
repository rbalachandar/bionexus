"""`bn reproduce` — replay a recorded experiment and diff the verdicts.

Reads a provenance branch, reconstructs the campaign EXACTLY as recorded
(hypotheses, criteria, lab adapter + seed, concentrations, autonomy, dose
design), re-runs it offline, and compares verdict-by-verdict. Reproducibility
as a command, not a promise.

Honest limits: LLM-proposed portfolios and live instruments cannot be replayed
byte-exactly (model drift, real-world noise) — those branches report
`not-reproducible: <reason>` rather than faking a match.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


def reproduce(branch: str, db_path: str = "bionexus.db",
              inbox: str | Path | None = None) -> dict:
    from bionexus.adapters.store.sqlite import SqliteProvenanceStore
    store = SqliteProvenanceStore(db_path)
    recs = store.branch_records(branch)
    if not recs:
        return {"status": "error", "reason": f"no records for '{branch}'"}

    env: dict = {}
    hypotheses: dict[str, dict] = {}
    recorded: dict[str, dict] = {}
    for r in recs:
        d = r.decision or {}
        et = r.event_type.value
        if et == "problem_defined":
            env = d.get("environment") or {}
            problem_doc = d
        elif et == "hypothesis_proposed":
            art = (r.artifact.metadata if r.artifact else {}) or {}
            cand = art.get("candidate")
            if cand:
                hypotheses[cand] = {
                    "statement": d.get("statement", ""),
                    "candidate": cand,
                    "assay_type": art.get("assay", "binding"),
                    "predicted": d.get("predicted", ""),
                    "predicted_value": (d.get("criteria") or {}).get(
                        "threshold"),
                    "mechanism": d.get("mechanism", ""),
                    "refutation_condition": d.get("refutation_condition", ""),
                    "citation": d.get("citation", ""),
                    "citation_status": d.get("citation_status", "unverified"),
                }
        elif et in ("hypothesis_validated", "hypothesis_invalidated",
                    "hypothesis_inconclusive",
                    "hypothesis_tested"):
            art = (r.artifact.metadata if r.artifact else {}) or {}
            cand = art.get("candidate")
            if cand and d.get("verdict"):
                recorded[cand] = d          # last one wins (final state)

    if not env.get("lab_seed") and env.get("lab") != "simulator":
        return {"status": "not-reproducible",
                "reason": "no recorded lab environment (pre-environment "
                          "provenance) or live lab — re-run once to capture"}
    if not hypotheses:
        return {"status": "not-reproducible",
                "reason": "no candidate hypotheses in branch"}

    from bionexus.adapters.lab.simulator import SimulatorLab
    from bionexus.autoloop import CampaignConfig, run_campaign
    from bionexus.core.hypothesis import Constraint, ProblemStatement

    labs = {"simulator": SimulatorLab}
    lab_cls = labs.get(env.get("lab", "simulator"))
    if lab_cls is None:
        return {"status": "not-reproducible",
                "reason": f"no replay adapter for lab '{env.get('lab')}' "
                          "(live labs replay via recording playback, not here)"}

    _replay_base = (problem_doc.get("problem_id") or "prob") + "-replay"
    _replay_id, _k = _replay_base, 1
    while store.branch_records(f"problem/{_replay_id}"):
        _k += 1
        _replay_id = f"{_replay_base}-{_k}"
    problem = ProblemStatement(
        objective=problem_doc.get("objective", ""),
        problem_id=_replay_id,
        constraints=[Constraint(**c)
                     for c in problem_doc.get("constraints", [])])
    cfg = CampaignConfig(
        problem=problem,
        hypotheses=list(hypotheses.values()),
        k=env.get("k", 2), autonomy="act",   # replay always runs through
        inbox=str(inbox or ".data/reproduce-inbox"),
        concentrations=tuple(env.get("concentrations",
                                     ["0.5uM", "2uM", "10uM", "40uM"])),
        dose_design=env.get("dose_design", "fixed"),
        poll_secs=0.05)
    _seed = env.get("lab_seed")
    if _seed is None:
        _seed = 7                       # pre-seed-capture branches default
    lab = lab_cls(seed=_seed)
    report = run_campaign(cfg, lab, SqliteProvenanceStore())

    diffs, matches = [], 0
    for cand, rec in sorted(recorded.items()):
        new_v = report.verdicts.get(cand)
        old_v = rec.get("verdict")
        if new_v == old_v:
            matches += 1
        else:
            diffs.append({"candidate": cand, "recorded": old_v,
                          "replayed": new_v})
    n = len(recorded)
    return {
        "status": "match" if not diffs and n else ("differs" if n else
                                                   "no-verdicts"),
        "branch": branch, "recorded_verdicts": n, "matched": matches,
        "diffs": diffs,
        "environment": env,
        "model_pinned": False,
        "note": ("simulated replay: identical lab seeds & structures; "
                 "the generation model "
                 f"{env.get('model') or 'n/a'} is NOT re-invoked — "
                 "hypotheses are replayed exactly as recorded. "
                 "Reproduced: the EXECUTION path, not the model's "
                 "creative step."),
    }
