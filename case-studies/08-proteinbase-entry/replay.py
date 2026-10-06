#!/usr/bin/env python3
"""Selection-policy replay on the frozen Proteinbase tested corpus.

Question CS07 left open: global-confidence ranking loses to the pool.
Does gate+diversity selection at least NOT lose? (It cannot be expected
to WIN without an interface-aware score — the point is whether
discipline is free, and what eligibility costs in raw pass-through.)
"""
from __future__ import annotations

import csv, gzip, json, random, sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "src"))

from entry_gates import check_sequence, _kmers          # noqa: E402
from diversity_select import select_diverse              # noqa: E402


def load():
    fx = HERE.parents[0] / "07-proteinbase" / "fixtures"
    with gzip.open(fx / "proteins.csv.gz", "rt") as fh:
        prot = {p["id"]: p for p in csv.DictReader(fh)}
    pairs = list(csv.DictReader(gzip.open(
        HERE.parents[0] / "07-proteinbase/fixtures/pairs.csv.gz", "rt")))
    return prot, pairs


def main():
    prot, pairs = load()
    out = {}
    for tgt in ("nipah-glycoprotein-g", "egfr"):
        pool = [(x, prot.get(x["protein_id"], {})) for x in pairs
                if x["target"] == tgt and x["bound"] in ("True", "False")
                and prot.get(x["protein_id"], {}).get("seq")]
        if len(pool) < 80:
            continue
        n = max(1, len(pool) // 4)
        hit = lambda xs: sum(x["bound"] == "True" for x, _ in xs) / max(1, len(xs))
        base = hit(pool)
        gated = [(x, p) for x, p in pool
                 if check_sequence(p["seq"])["pass"]]
        gates_pass = len(gated) / len(pool)
        pl = [(x, p) for x, p in pool if p.get("plddt") not in ("", None)]
        top_pl = sorted(pl, key=lambda t: -float(t[1]["plddt"]))[:n]
        sets = [(x["protein_id"], _kmers(p["seq"])) for x, p in gated]
        div_ids = set(select_diverse(sets, n))
        divpick = [(x, p) for x, p in gated if x["protein_id"] in div_ids]
        rng = random.Random(7)
        rnd = rng.sample(pool, n)
        out[tgt] = {
            "pool_n": len(pool), "slot_n": n,
            "gate_pass_rate": round(gates_pass, 4),
            "hit_baseline": round(base, 4),
            "hit_random_slots": round(hit(rnd), 4),
            "hit_plddt_top": round(hit(top_pl), 4),
            "hit_gated_random": round(hit(rng.sample(gated, min(n, len(gated)))), 4),
            "hit_gated_diverse": round(hit(divpick), 4),
        }
    print(json.dumps(out, indent=1))
    (HERE / "replay_results.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
