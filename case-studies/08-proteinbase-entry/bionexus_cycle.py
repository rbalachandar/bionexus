#!/usr/bin/env python3
"""CS08 step 3 — the BioNexus loop OVER the real GPU data. CPU-only, no LLM.

Reads the measured Boltz-2 scores (.data/cs08-designs/night1/) and runs
them through the actual framework: quality floor -> EVERY survivor
proposed as a hypothesis (pre-registered SuccessCriteria, predicted_by
stamps) -> verdict via CI veto (single-prediction band: no replicates,
so ipTM ± 0.05 gets declared and can force 'inconclusive') -> outcomes
sealed into the SQLite hash-chained provenance store -> verify_chain().

Controls (scrambles/randoms) enter as first-class hypotheses too, tagged
role="control" — when a scramble VALIDATES at 0.93 the tracker records it
honestly. The chain is the deliverable: the score's ranking failure is
EVIDENCE in the store, not a footnote.
"""
from __future__ import annotations

import json, statistics as st, sys
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parents[1]
DATA = ROOT / ".data" / "cs08-designs" / "night1"
DB = ROOT / ".data" / "cs08-bionexus-cycle.db"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "src"))

from bionexus.adapters.lab.protein_design import ProteinDesignLabAdapter  # noqa: E402
from bionexus.adapters.store.sqlite import SqliteProvenanceStore          # noqa: E402
from bionexus.core.hypothesis import (Constraint, HypothesisTracker,      # noqa: E402
                                      ProblemStatement, SuccessCriteria)
from bionexus.core.interfaces import system_actor                         # noqa: E402

GATE, BAND_HALF = 0.7, 0.05


from cs08_io import load_scores   # noqa: E402


def main() -> None:
    if not DATA.exists():
        sys.exit(f"missing raw data dir: {DATA}")
    DB.unlink(missing_ok=True)

    store = SqliteProvenanceStore(str(DB))
    tr = HypothesisTracker(store, system_actor("cs08-cycle"))
    prob = ProblemStatement(objective="PD-L1 binder design (CS08 prospective)",
                            constraints=[Constraint(name="iptm", kind="hard",
                                                    limit=GATE, unit="iptm",
                                                    description="Boltz-2 interface confidence")])
    tr.define_problem(prob)
    branch = f"problem/{prob.problem_id}"
    criteria = SuccessCriteria(metric="iptm", direction="max", threshold=GATE,
                               proxy_of="pd_l1_binding_kd")

    designs = load_scores(DATA / "boltz_predictions")
    ctrls = load_scores(DATA / "ctrl_predictions")

    adapter = ProteinDesignLabAdapter(mock=False)
    rows = [{"name": n, "sequence": "", "plddt": c["complex_plddt"]}
            for n, c in designs.items()]
    for r in rows:                       # floor needs sequences for length/AA checks
        y = DATA / "boltz_in2" / f"{r['name']}.yaml"
        import re
        m = re.search(r"id: A\n      sequence: (\w+)", y.read_text()) if y.exists() else None
        r["sequence"] = m.group(1) if m else "X" * 50
    passing, rejected = adapter.apply_quality_floor(rows)
    pass_names = {d["name"] for d in passing}

    def run_one(name: str, c: dict, role: str) -> str:
        h = tr.propose(
            statement=f"{name}: Boltz-2 ipTM >= {GATE}",
            candidate=name, assay_type="protein_binder_screen",
            predicted=f"ipTM >= {GATE}", predicted_value=c["iptm"],
            rationale=f"BindCraft design (role={role}), screened by Boltz-2 "
                      f"with MSA server; single prediction, declared "
                      f"±{BAND_HALF} band (no replicates)",
            branch_id=branch, criteria=criteria,
            predicted_by={"source": "bindcraft+mpnn" if role == "design"
                          else "scramble|random (control)", "policy":
                          "AF2-backprop+MPNN -> boltz2 ipTM"},
            role=role, model="boltz-2", n_replicates=1)
        ci = (round(c["iptm"] - BAND_HALF, 4), round(c["iptm"] + BAND_HALF, 4))
        h.status = {"validated": "validated", "invalidated": "invalidated",
                    "inconclusive": "inconclusive"}[
                        criteria.classify(c["iptm"], ci)]
        h.observed_value = c["iptm"]
        h.observed_ci = ci
        h.qc_passed = True
        tr.record_outcome(h, extra={"evidence_tier": "proxy",
                                    "iptm": c["iptm"], "complex_plddt":
                                    c["complex_plddt"]})
        return h.status

    tally = {"design": {}, "control_scramble": {}, "control_random": {}}
    for n, c in sorted(designs.items()):
        if n in pass_names:
            s = run_one(n, c, "design")
            tally["design"][s] = tally["design"].get(s, 0) + 1
    for n, c in sorted(ctrls.items()):
        role = "control_scramble" if n.startswith("SCR_") else "control_random"
        s = run_one(n, c, role)
        tally[role][s] = tally[role].get(s, 0) + 1

    bad = store.verify_chain()
    out = {
        "db": str(DB.relative_to(ROOT)),
        "floor": {"pass": len(passing), "reject": len(rejected)},
        "verdict_tallies": tally,
        "chain_intact": bad == [], "chain_problems": bad,
        "evidence_line": criteria.evidence_line(),
        "embarrassing_records": sorted(
            f"{n} ({c['iptm']:.3f} -> validated)"
            for n, c in ctrls.items()
            if criteria.classify(c["iptm"], (c["iptm"] - BAND_HALF,
                                             c["iptm"] + BAND_HALF))
            == "validated"),
        "design_median_iptm": round(st.median(list(c["iptm"] for c in designs.values())), 4),
    }
    (HERE / "bionexus_cycle_results.json").write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
