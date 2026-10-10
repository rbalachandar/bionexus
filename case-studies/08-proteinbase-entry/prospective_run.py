#!/usr/bin/env python3
"""CS08 step 2 PROSPECTIVE analysis — real models, real GPU run, real controls.

82 BindCraft/MPNN PD-L1 designs + 30 self-run controls (20 amino-acid
composition-matched scrambles of the top-20 designs, 10 random 100-mers),
ALL scored by the same Boltz-2 prediction (identical protocol, seed-free)
and compared against the same ipTM >= 0.7 competition-style gate.

The question: can interface-confidence RANK designs above random-looking
sequences at the individual level? (Replay said global scores lose; here
we generate the data ourselves, prospective, one target, one day.)

Raw artifacts: .data/cs08-designs/night1/ (results.csv, boltz_predictions/,
ctrl_predictions/, boltz_in2/, controls_in/) — run on an RTX A5000, Oct 2026.
"""
from __future__ import annotations

import csv, json, random, re, statistics as st, sys
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parents[1]
DATA = ROOT / ".data" / "cs08-designs" / "night1"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "src"))

from entry_gates import check_sequence                      # noqa: E402
from bionexus.adapters.lab.protein_design import (          # noqa: E402
    ProteinDesignLabAdapter,
)

GATE = 0.7
BAND = (0.65, 0.75)          # abstention band around the gate


def seq_from_yaml(path: Path) -> str:
    m = re.search(r"id: A\n      sequence: (\w+)", path.read_text())
    return m.group(1) if m else ""


from cs08_io import load_scores as load_iptms   # noqa: E402


def main() -> None:
    if not DATA.exists():
        sys.exit(f"missing raw data dir: {DATA}")

    designs = load_iptms(DATA / "boltz_predictions")
    ctrls = load_iptms(DATA / "ctrl_predictions")
    scr = {k: v for k, v in ctrls.items() if k.startswith("SCR_")}
    rnd = {k: v for k, v in ctrls.items() if k.startswith("RND_")}

    binders = {p.stem: seq_from_yaml(p)
               for p in sorted((DATA / "boltz_in2").glob("*.yaml"))}
    ctrl_seqs = {p.stem: seq_from_yaml(p)
                 for p in sorted((DATA / "controls_in").glob("*.yaml"))}

    # --- layer 2: quality floor on REAL measured pLDDT --------------------
    adapter = ProteinDesignLabAdapter(mock=False)
    rows = [{"name": n, "sequence": binders.get(n, ""), "plddt": c["complex_plddt"],
             "iptm": c["iptm"]} for n, c in designs.items()]
    passing, rejected = adapter.apply_quality_floor(rows)

    # --- composition gates: blind by construction (scrambles keep AA
    # composition; random peptides pass sanity) — measure, don't assume
    gate_des = [check_sequence(s)["pass"] for s in binders.values() if s]
    gate_scr = [check_sequence(ctrl_seqs[k])["pass"] for k in scr if k in ctrl_seqs]
    gate_rnd = [check_sequence(ctrl_seqs[k])["pass"] for k in rnd if k in ctrl_seqs]

    # --- verdicts: gate + abstention band, all labeled PREDICTED ----------
    from cs08_io import verdict   # ONE mechanism across the study

    verd = {n: verdict(c["iptm"]) for n, c in designs.items()}

    D = [c["iptm"] for c in designs.values()]
    S = [c["iptm"] for c in scr.values()]
    R = [c["iptm"] for c in rnd.values()]
    C = S + R
    allc = sorted((n, v["iptm"]) for n, v in list(scr.items()) + list(rnd.items()))
    dmed = st.median(D)
    above = [(n, round(v, 3)) for n, v in allc if v >= dmed]

    # --- small-n stats: Mann-Whitney + bootstrap CI on median difference --
    from scipy.stats import mannwhitneyu
    u_s, p_s = mannwhitneyu(D, S, alternative="greater")
    u_r, p_r = mannwhitneyu(D, R, alternative="greater")
    rng = random.Random(19)
    boot = sorted(st.median(rng.choices(D, k=len(D)))
                  - st.median(rng.choices(C, k=len(C))) for _ in range(10_000))
    ci = (round(boot[int(0.025 * len(boot))], 4), round(boot[int(0.975 * len(boot))], 4))
    auc = sum((d > c) + 0.5 * (d == c) for d in D for c in C) / (len(D) * len(C))

    out = {
        "n_designs": len(D), "n_scrambles": len(S), "n_random": len(R),
        "iptm": {
            "designs": {"median": round(dmed, 4), "mean": round(st.mean(D), 4),
                        "min": round(min(D), 4), "max": round(max(D), 4)},
            "scrambles": {"median": round(st.median(S), 4),
                          "max": round(max(S), 4)},
            "random": {"median": round(st.median(R), 4), "max": round(max(R), 4)},
        },
        "median_diff_bootstrap_ci95": ci,
        "mannwhitney": {"vs_scrambles_p": f"{p_s:.2e}", "vs_random_p": f"{p_r:.2e}"},
        "auc_design_vs_control": round(auc, 4),
        "controls_above_design_median": above,
        "quality_floor": {"pass": len(passing), "reject": [
            {"name": d["name"], "reasons": d["rejection_reasons"]} for d in rejected]},
        "gate_band_abstentions": sum(1 for v in verd.values() if v == "abstain"),
        "verdicts": {"confirm_predicted": sum(1 for v in verd.values() if v.startswith("confirm")),
                     "refute_predicted": sum(1 for v in verd.values() if v.startswith("refute")),
                     "abstain": sum(1 for v in verd.values() if v == "abstain")},
        "eligibility_gate_pass": {
            "designs": f"{sum(gate_des)}/{len(gate_des)}",
            "scrambles": f"{sum(gate_scr)}/{len(gate_scr)}",
            "random": f"{sum(gate_rnd)}/{len(gate_rnd)}"},
        "labeled": "ALL verdicts are PREDICTED (proxy evidence: Boltz-2 on "
                   "BindCraft designs). Nothing here is measured binding.",
    }
    (HERE / "prospective_results.json").write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
