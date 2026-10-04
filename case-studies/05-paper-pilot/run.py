#!/usr/bin/env python3
"""CS05 — The Paper Pilot: reproduce the Jacobs 2013 confirmatory cascade
from the lab's own deposited tables, blind, and score against their calls.

Gate pre-registered here (not tuned later): the paper's claim is ACTIVE iff
IC50 < 10 uM. Our verdict uses the production rule only — SuccessCriteria.
classify with CI veto (right-censored curves get a range statement, never
a number). Answer-key columns (OUTCOME / submitter IC50) are read ONLY in
the scoring step, after every verdict is fixed.

Run:  .venv/bin/python case-studies/05-paper-pilot/run.py
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path

STUDY = Path(__file__).parent
REPO = STUDY.parents[1]
sys.path.insert(0, str(REPO / "src"))

GATE_UM = 10.0


def materialize() -> dict[str, Path]:
    from bionexus import fixtures
    ok, problems = fixtures.verify(str(STUDY))
    if not ok:
        sys.exit(f"fixtures FAILED VERIFICATION: {problems}")
    fixtures.materialize(str(STUDY))
    man = json.loads((STUDY / "fixtures" / "manifest.json").read_text())
    live = {}
    for e in man["entries"]:
        p = REPO / e["target"]
        if hashlib.sha256(p.read_bytes()).hexdigest() != e["sha256"]:
            sys.exit(f"materialized file drifted: {e['target']}")
        live[e["path"]] = p
    return live


def blind_read(path: Path):
    """Engine step: labread native-PubChem parse + per-compound Hill fits.
    Structurally blind — OUTCOME/IC50 columns are not in what comes back."""
    from bionexus.labread import read_plate
    return read_plate(path, max_response=100.0)


def verdicts(res, gate: float = GATE_UM) -> dict[str, dict]:
    from bionexus.core.hypothesis import SuccessCriteria
    crit = SuccessCriteria(metric="ic50_um", direction="min", threshold=gate)
    out: dict[str, dict] = {}
    for sid, comp in res.analysis["compounds"].items():
        ic50, ci = comp["ic50_um"], comp["ic50_ci"]
        pts = [(r["conc_um"], r["inhibition_pct"]) for r in res.records
               if r["sample"] == sid]
        top = max(pts)[-1] if pts else None
        if ic50 is not None:
            v = {"validated": "Active", "invalidated": "Inactive",
                 "inconclusive": "Abstain"}[crit.classify(ic50, ci)]
        else:  # no crossing inside the measurement window
            v = ("Inactive" if top is not None and top < 50.0 else "Abstain")
        out[sid] = {"verdict": v, "ic50_um": ic50, "ci95": list(ci) if ci else None,
                    "max_inhibition_pct": top,
                    "right_censored": ic50 is None}
    return out


def answer_key(path: Path) -> dict[str, dict]:
    """Scoring-time ONLY: the submitter's deposited calls + their fits."""
    with path.open(newline="", encoding="utf-8-sig") as f:
        rd = csv.reader(f)
        rows = [r for r in rd if r and not r[0].startswith("RESULT")]
    hdr = rows[0]
    i_out, i_sid, i_ic50 = hdr.index("PUBCHEM_ACTIVITY_OUTCOME"), \
        hdr.index("PUBCHEM_SID"), hdr.index("IC50")
    i_smi = hdr.index("PUBCHEM_EXT_DATASOURCE_SMILES")
    return {f"SID{r[i_sid]}": {"outcome": r[i_out],
                               "submitter_ic50_uM": (float(r[i_ic50])
                                 if r[i_ic50] and r[i_ic50] != "NA" else None),
                               "smiles": r[i_smi]} for r in rows[1:]}


def secondary(path: Path) -> dict[str, dict]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        rows = [r for r in csv.reader(f) if r and not r[0].startswith("RESULT")]
    hdr = rows[0]
    i_sid, i_inh, i_sd, i_out = (hdr.index("PUBCHEM_SID"),
                                 hdr.index("Inhibition"),
                                 hdr.index("Standard Deviation"),
                                 hdr.index("PUBCHEM_ACTIVITY_OUTCOME"))
    return {f"SID{r[i_sid]}": {"inh6uM": float(r[i_inh]) if r[i_inh] else None,
            "sd": float(r[i_sd]) if r[i_sd] else None, "outcome": r[i_out]}
            for r in rows[1:]}


def main() -> int:
    live = materialize()
    doseres = live["aid_1890.csv"]
    secres = live["aid_1879.csv"]

    res = blind_read(doseres)
    ours = verdicts(res)
    key = answer_key(doseres)
    sec = secondary(secres)

    # verdicts are locked before the key is touched
    table = {}
    for sid, o in ours.items():
        theirs = key.get(sid, {}).get("outcome", "?")
        agree = ((theirs == "Active" and o["verdict"] == "Active")
                 or (theirs == "Inactive" and o["verdict"] == "Inactive"))
        table[sid] = {**o, "deposited": theirs,
                      "submitter_ic50_uM": key.get(sid, {}).get(
                          "submitter_ic50_uM"),
                      "agree": agree}

    n = len(table)
    conf = {"TP": 0, "FP": 0, "TN": 0, "FN": 0, "ABSTAIN": 0}
    for t in table.values():
        if t["verdict"] == "Abstain":
            conf["ABSTAIN"] += 1
        elif t["deposited"] == "Active":
            conf["TP" if t["verdict"] == "Active" else "FN"] += 1
        else:
            conf["TN" if t["verdict"] == "Inactive" else "FP"] += 1
    decisive = n - conf["ABSTAIN"]
    agreement = (conf["TP"] + conf["TN"]) / decisive if decisive else 0.0

    # cross-plate consistency: their own secondary @6uM vs their OWN
    # deposited dose-response curve (Hill-1 predicted %inh at 6 uM).
    # Flag only LARGE mismatches (>25 points) — different plates, different
    # days; this audits their cascade, not our verdicts. Key data used at
    # scoring/audit time only, never in the blind fit.
    cascade_conflicts = []
    for sid, t in table.items():
        s = sec.get(sid)
        if not s or s["inh6uM"] is None or t["submitter_ic50_uM"] is None:
            continue
        pred = 100.0 * 6.0 / (6.0 + t["submitter_ic50_uM"])
        delta = s["inh6uM"] - pred
        if abs(delta) > 25.0:
            cascade_conflicts.append({
                "sid": sid, "secondary_inh6": s["inh6uM"],
                "predicted_from_their_curve": round(pred, 1),
                "delta": round(delta, 1),
                "issue": f"their secondary ({s['inh6uM']:.0f}% inh @6 uM) "
                         f"is {abs(delta):.0f} points "
                         f"{'below' if delta < 0 else 'above'} their own "
                         f"confirmatory-curve prediction ({pred:.0f}%)"})

    # series view over our confirmed actives
    from bionexus.series import build_series
    vmap = {"Active": "confirmed", "Inactive": "refuted",
            "Abstain": "inconclusive"}
    members = [{"candidate": sid, "smiles": key[sid]["smiles"],
                "verdict": vmap[t["verdict"]]}
               for sid, t in table.items() if sid in key]
    series = build_series(members)
    chemo = sorted(series.values(),
                   key=lambda s: (-s["rollup"]["confirmed"], -s["n_members"]))[:8]
    series_view = [{"key": s["key"][:40], "kind": s["kind"],
                    "n": s["n_members"],
                    "actives": s["rollup"]["confirmed"],
                    "backend": s["chemotype_backend"]} for s in chemo]

    disagreements = [{"sid": sid, "cid": next(
                        (r["cid"] for r in res.records if r["sample"] == sid), ""),
                      "ours": t["verdict"], "ours_ic50": t["ic50_um"],
                      "ci95": t["ci95"], "deposited": t["deposited"],
                      "submitter_ic50_uM": t["submitter_ic50_uM"],
                      "max_inh": t["max_inhibition_pct"]}
                     for sid, t in sorted(table.items())
                     if not t["agree"]]

    results = {
        "study": "CS05 paper pilot — Jacobs 2013 SARS-CoV 3CLpro confirmatory",
        "gate_uM": GATE_UM, "blinded": "verdicts locked before answer_key read",
        "n": n, "confusion_vs_deposited": conf,
        "agreement_decisive": round(agreement, 3),
        "abstain_rate": round(conf["ABSTAIN"] / n, 3),
        "their_active_count": sum(1 for t in table.values()
                                  if t["deposited"] == "Active"),
        "our_active_count": sum(1 for t in table.values()
                                if t["verdict"] == "Active"),
        "disagreements": disagreements,
        "cascade_conflicts": cascade_conflicts,
        "series_view_top8": series_view,
        "per_compound": {k: table[k] for k in sorted(table)},
    }
    (STUDY / "results.json").write_text(json.dumps(results, indent=1))

    print(f"n={n} | gate IC50<{GATE_UM} uM | vs deposited calls: "
          f"TP{conf['TP']} TN{conf['TN']} FP{conf['FP']} FN{conf['FN']} "
          f"abstain{conf['ABSTAIN']}")
    print(f"agreement on decisive verdicts: {agreement:.1%} · "
          f"abstain rate {conf['ABSTAIN']/n:.1%}")
    print(f"cascade conflicts (deposited vs their own secondary): "
          f"{len(cascade_conflicts)}")
    for d in disagreements[:12]:
        print(f"  DISAGREE {d['sid']} cid{d['cid']}: ours {d['ours']} "
              f"(ic50 {d['ours_ic50']} ci {d['ci95']}) vs deposited "
              f"{d['deposited']} (their IC50 {d['submitter_ic50_uM']})")
    print("top chemotypes:", "; ".join(
        f"{s['n']}x {s['key'][:26]} ({s['actives']} active)"
        for s in series_view[:4]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
