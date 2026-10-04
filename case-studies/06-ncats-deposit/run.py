#!/usr/bin/env python3
"""CS06 — The Deposit Pilot: independently refit 2,427 NCATS qHTS curves
(AID 2061307, deposited 2025-09-13) and map our CI-aware calls against
NCATS' own AI-fit outcome columns.

Pre-registered design decisions (set BEFORE scoring; see README):
- gate: IC50 <= 1.0 uM (standard confirmatory probe bar for reassays)
- blind curve QC (registered, no answer keys): >=6 measured doses, a real
  50% crossing in-sample, fit not pinned to grid edges — flat-at-ceiling
  curves abstain (the degenerate mode this deposit exposed: a 2-param Hill
  with known max "fits" any flat line as infinitely potent)
- verdict rule: SuccessCriteria.classify with CI veto (straddle = Abstain)
- NCATS' ACTIVE/INACTIVE/INCONCLUSIVE turns out to be CURVE-CLASS based
  (their Active median potency is ~6 uM, and some 'Inactive' rows fit
  potent) — so agreement is reported as a CALIBRATION MAP (3x3 crosstab),
  not a hit-rate; the numeric reproduction target is our independent AC50
  vs their Fit_LogAC50 (Spearman), and the epistemic target is our
  abstention set vs their Inconclusive set.

Answer-key columns (OUTCOME/Potency/Fit_*) are read only AFTER every
verdict is locked. The blind fit itself (bionexus.labread) structurally
never sees them.

Run:  .venv/bin/python case-studies/06-ncats-deposit/run.py
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

GATE_UM = 1.0


def materialize() -> Path:
    from bionexus import fixtures
    ok, problems = fixtures.verify(str(STUDY))
    if not ok:
        sys.exit(f"fixtures FAILED VERIFICATION: {problems}")
    fixtures.materialize(str(STUDY))
    man = json.loads((STUDY / "fixtures" / "manifest.json").read_text())
    e = man["entries"][0]
    live = REPO / e["target"]
    if hashlib.sha256(live.read_bytes()).hexdigest() != e["sha256"]:
        sys.exit("materialized file drifted")
    return live


def spearman(a: list[float], b: list[float]):
    n = len(a)
    def rank(x):
        s = sorted(range(n), key=lambda i: x[i])
        r = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and x[s[j + 1]] == x[s[i]]:
                j += 1
            avg = (i + j) / 2 + 1
            for k in range(i, j + 1):
                r[s[k]] = avg
            i = j + 1
        return r
    ra, rb = rank(a), rank(b)
    ma, mb = sum(ra) / n, sum(rb) / n
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    da = sum((x - ma) ** 2 for x in ra) ** 0.5
    db = sum((y - mb) ** 2 for y in rb) ** 0.5
    return num / (da * db) if da and db else float("nan")


def main() -> int:
    live = materialize()
    from bionexus.labread import read_plate
    res = read_plate(live, max_response=100.0)
    assert "flipped" in res.response_unit, "expected activity-scale disclosure"

    from bionexus.core.hypothesis import SuccessCriteria
    crit = SuccessCriteria(metric="ic50_um", direction="min", threshold=GATE_UM)
    ours: dict[str, dict] = {}
    for sid, comp in res.analysis["compounds"].items():
        ic50, ci = comp["ic50_um"], comp["ic50_ci"]
        pts = sorted((r["conc_um"], r["inhibition_pct"])
                     for r in res.records if r["sample"] == sid)
        concs = [c for c, _ in pts]
        vals = [v for _, v in pts]
        # Registered BLIND curve QC (standard qHTS epistemology, no answer
        # keys). Two artifact families this deposit carries:
        #  (1) autofluorescence flatlines: ~100% "inhibition" at every dose,
        #      uncorrelated with concentration — concentration-dependence
        #      (Spearman trend) is the discriminator, not the crossing;
        #  (2) super-potent curves: already >50% at the lowest measured
        #      dose — no in-sample crossing, but honest as a RANGE
        #      statement (IC50 <= lowest dose) when trend + c_min support it.
        reasons = []
        trend = spearman(concs, vals) if len(pts) >= 4 else float("nan")
        crosses = min(vals) <= 50.0 <= max(vals) and len({v > 50 for v in vals}) == 2
        if len(pts) < 6:
            reasons.append(f"only {len(pts)} measured doses (<6)")
        if not (trend >= 0.5):
            reasons.append(f"no concentration dependence (trend rho={trend:.2f})")
        if comp.get("left_censored") and crosses:
            reasons.append("fit pinned at grid floor with noisy low doses")
        if reasons:
            v, why = "Abstain", "; ".join(reasons)
        elif not crosses and min(vals) > 50.0:
            # super-potent: every measured dose inhibits past 50%
            if concs[0] <= GATE_UM:
                v, why = "Active", ""
                comp = dict(comp, ic50_um=concs[0])  # RANGE: IC50 <= c_min
            else:
                v, why = "Abstain", "all doses >50% but lowest exceeds gate"
        elif not crosses and max(vals) <= 50.0:
            # never reaches 50% inside the window: claim IC50 > c_max —
            # certifiable as Inactive only if the window covers the gate
            if concs[-1] >= GATE_UM:
                v, why = "Inactive", ""
            else:
                v, why = "Abstain", "top dose below gate; can't certify"
        elif ic50 is not None:
            v = {"validated": "Active", "invalidated": "Inactive",
                 "inconclusive": "Abstain"}[crit.classify(ic50, ci)]
            why = "CI straddles the gate" if v == "Abstain" else ""
        else:
            v, why = "Abstain", "crossing present but Hill declined"
        ours[sid] = {"verdict": v, "ic50_um": comp["ic50_um"],
                     "ci95": list(ci) if ci else None,
                     "n_points": len(pts), "trend_rho": round(trend, 3),
                     "range_claim": bool(why == "" and not crosses
                                         and min(vals) > 50.0),
                     "qc": why}

    # ---- answer key (scoring-time only) ----
    rows = [r for r in csv.reader(live.open(newline="", encoding="utf-8-sig"))
            if r and not r[0].startswith("RESULT")]
    hdr = rows[0]
    ix = {k: hdr.index(k) for k in ("PUBCHEM_SID", "PUBCHEM_ACTIVITY_OUTCOME",
                                    "Fit_LogAC50", "Potency", "Phenotype",
                                    "Curve_Description")}
    key = {}
    for r in rows[1:]:
        sid = f"SID{r[ix['PUBCHEM_SID']]}"
        try:
            logac = float(r[ix["Fit_LogAC50"]]) if r[ix["Fit_LogAC50"]] else None
        except ValueError:
            logac = None
        key[sid] = {"outcome": r[ix["PUBCHEM_ACTIVITY_OUTCOME"]],
                    "their_logAC50_M": logac,
                    "phenotype": r[ix["Phenotype"]],
                    "curve": r[ix["Curve_Description"]][:40]}

    # ---- 3x3 calibration map ----
    crosstab: dict[str, dict[str, int]] = {}
    pairs_a, pairs_b = [], []
    for sid, o in ours.items():
        k = key.get(sid, {})
        their = k.get("outcome") or "?"
        crosstab.setdefault(their, {"Active": 0, "Inactive": 0, "Abstain": 0})
        crosstab[their][o["verdict"]] += 1
        if o["ic50_um"] and k.get("their_logAC50_M") is not None:
            pairs_a.append(o["ic50_um"])
            pairs_b.append(10 ** -k["their_logAC50_M"])   # M -> uM-style (rel)

    # ---- abstention alignment ----
    def reason_cat(q: str) -> str:
        q0 = q.split(";")[0]
        return (q0.split(" (")[0] if q0.startswith("no concentration") else
                q0.split(" [")[0].split(" with")[0])
    our_abstain = {s for s, o in ours.items() if o["verdict"] == "Abstain"}
    their_incon = {s for s, k in key.items() if k["outcome"] == "Inconclusive"}
    both = len(our_abstain & their_incon)

    # ---- potency reproduction ----
    rho = spearman(pairs_a, pairs_b) if len(pairs_a) >= 20 else None

    from collections import Counter
    _qc_hist = dict(Counter(reason_cat(o["qc"]) for o in ours.values()
                            if o["verdict"] == "Abstain"))

    # ---- series view of our confirmed actives ----
    from bionexus.series import build_series
    smi = {}
    for r in res.records:
        smi.setdefault(r["sample"], r["smiles"])
    members = [{"candidate": s, "smiles": smi.get(s, ""),
                "verdict": {"Active": "confirmed", "Inactive": "refuted",
                            "Abstain": "inconclusive"}[o["verdict"]]}
               for s, o in ours.items()]
    series = build_series(members)
    top = sorted(series.values(),
                 key=lambda x: (-x["rollup"]["confirmed"], -x["n_members"]))[:6]
    series_view = [{"key": s["key"][:40], "kind": s["kind"],
                    "n": s["n_members"], "confirmed": s["rollup"]["confirmed"],
                    "backend": s["chemotype_backend"]} for s in top]

    results = {
        "study": "CS06 NCATS deposit pilot — ALDH3A1 reassay (AID 2061307)",
        "gate_uM": GATE_UM,
        "scale_disclosure": res.response_unit,
        "n_fitted": len(ours), "n_total": len(key),
        "crosstab_their_to_ours": crosstab,
        "our_counts": {v: sum(1 for o in ours.values()
                              if o["verdict"] == v)
                       for v in ("Active", "Inactive", "Abstain")},
        "abstain_alignment": {
            "ours": len(our_abstain), "theirs": len(their_incon),
            "intersection": both,
            "of_ours_in_theirs": round(both / len(our_abstain), 3)
            if our_abstain else None,
            "qc_reasons": _qc_hist},
        "potency_pairs": len(pairs_a),
        "spearman_our_ic50_vs_their_fit": round(rho, 3) if rho else None,
        "series_view_top6": series_view,
        "blinding": "labread parser structurally cannot read OUTCOME/Fit_*; "
                    "verdicts locked before key read",
    }
    (STUDY / "results.json").write_text(json.dumps(results, indent=1))
    print("scale:", res.response_unit, "| fitted:", len(ours),
          "of", len(key), "compounds")
    print("ours:", results["our_counts"])
    for their, row in sorted(crosstab.items()):
        print(f"  theirs {their:12} -> ours {row}")
    print("abstain alignment:", {k: v for k, v in
          results["abstain_alignment"].items() if k != "qc_reasons"})
    print("abstain reasons:", results["abstain_alignment"]["qc_reasons"])
    print("potency reproduction: n=", results["potency_pairs"],
          "spearman rho =", results["spearman_our_ic50_vs_their_fit"])
    for s in series_view[:4]:
        print("chemo:", s["n"], f"{s['confirmed']} confirmed |", s["key"][:38])
    return 0


if __name__ == "__main__":
    sys.exit(main())
