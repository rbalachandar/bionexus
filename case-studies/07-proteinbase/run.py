#!/usr/bin/env python3
"""CS07 — Proteinbase/Adaptyv reproduction: wet-lab binder data, third
modality, zero GPU. Reproduce what the competitions measured, then confront
the question the GPU answer raised: can OUR selection machinery beat the
pool baseline? (The honest answer is in results.json, both ways.)"""
from __future__ import annotations

import csv, gzip, hashlib, json, sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parents[0] / "src"))

PUBLISHED = {"nipah-glycoprotein-g": 0.093, "egfr": 0.14}  # site-stated


def load(name):
    p = HERE / "fixtures" / f"{name}.csv.gz"
    raw = gzip.decompress(p.read_bytes())
    man = json.loads((HERE / "fixtures" / "MANIFEST.json").read_text())
    assert hashlib.sha256(raw).hexdigest() == man["derived"][name + ".csv"]["sha256_raw"], name
    return list(csv.DictReader(raw.decode().splitlines()))


def pct(x):
    return f"{x:.1%}"


def main():
    proteins = {p["id"]: p for p in load("proteins")}
    pairs = load("pairs")

    # 1) hit rates per target vs published
    bytgt = defaultdict(lambda: [0, 0])
    for x in pairs:
        if x["bound"] in ("True", "False"):
            t = bytgt[x["target"]]
            t[0] += 1
            t[1] += x["bound"] == "True"
    hits_table = []
    for tgt, (n, h) in sorted(bytgt.items(), key=lambda kv: -kv[1][0]):
        if n >= 30:
            hits_table.append({"target": tgt, "n": n, "hits": h,
                               "hit_rate": round(h / n, 4),
                               "published": PUBLISHED.get(tgt)})

    # 2) nipah method spread
    mb = defaultdict(lambda: [0, 0])
    for x in pairs:
        if x["target"] == "nipah-glycoprotein-g" and x["bound"] in ("True", "False"):
            m = proteins.get(x["protein_id"], {}).get("method", "?")
            mb[m][0] += 1
            mb[m][1] += x["bound"] == "True"
    methods = [{"method": m, "n": n, "hits": h, "rate": round(h / n, 4)}
               for m, (n, h) in sorted(mb.items(), key=lambda kv: -(kv[1][1] / max(1, kv[1][0])))
               if n >= 15]

    # 3) expression QC
    ef = sum(1 for p in proteins.values() if p["expr_fail"] == "True")
    expression = {"proteins": len(proteins), "with_expr_failure": ef,
                  "rate": round(ef / len(proteins), 4)}

    # 4) selection replay: does computed confidence steer test slots?
    def replay(target, key):
        pool = [(x, float(proteins[x["protein_id"]][key]))
                for x in pairs
                if x["target"] == target and x["bound"] in ("True", "False")
                and proteins.get(x["protein_id"], {}).get(key) not in ("", None)]
        if len(pool) < 80:
            return None
        q = max(1, len(pool) // 4)
        top = sorted(pool, key=lambda t: -t[1])[:q]
        base = sum(x["bound"] == "True" for x, _ in pool) / len(pool)
        sel = sum(x["bound"] == "True" for x, _ in top) / len(top)
        return {"target": target, "signal": key, "pool_n": len(pool),
                "baseline_hit": round(base, 4), "top_quartile_hit": round(sel, 4),
                "lift": round(sel - base, 4)}
    replays = [r for r in (replay("nipah-glycoprotein-g", "plddt"),
                           replay("nipah-glycoprotein-g", "mpnn"),
                           replay("egfr", "plddt"),
                           replay("egfr", "mpnn")) if r]

    # 5) applicability domain transfer: a domain fitted to Nipah-tested
    # chemistry, applied to EGFR-tested chemistry (aa 3-gram basis —
    # bionexus.ad is string-agnostic). A cross-target claim should ARRIVE
    # stamped extrapolation; the in-target control measures the stamp's
    # false-alarm floor.
    from bionexus.ad import ApplicabilityDomain
    nip_seqs = [proteins[x["protein_id"]]["seq"] for x in pairs
                if x["target"] == "nipah-glycoprotein-g"
                and proteins.get(x["protein_id"], {}).get("seq")]
    egfr_seqs = [proteins[x["protein_id"]]["seq"] for x in pairs
                 if x["target"] == "egfr"
                 and proteins.get(x["protein_id"], {}).get("seq")]
    if nip_seqs and egfr_seqs:
        dom = ApplicabilityDomain.from_smiles(nip_seqs, basis="char3")
        def extrate(seqs):
            xs = [dom.check(s)["extrapolation"] for s in seqs]
            return round(sum(xs) / len(xs), 4)
        # control: leave-one-out-ish sample of the domain itself (first half
        # fits, second half queries -> in-domain false-alarm floor)
        import random
        rng = random.Random(7)
        samp = rng.sample(nip_seqs, min(200, len(nip_seqs)))
        half = len(samp) // 2
        dom2 = ApplicabilityDomain.from_smiles(samp[:half], basis="char3")
        ctrl = round(sum(dom2.check(s)["extrapolation"]
                         for s in samp[half:]) / (len(samp) - half), 4)
        ad_transfer = {"domain_n": len(nip_seqs), "query_n": len(egfr_seqs),
                       "cross_target_extrapolation_rate": extrate(egfr_seqs),
                       "in_target_control_extrapolation_rate": ctrl,
                       "floor": 0.5, "basis": "aa-char3-tanimoto (bionexus.ad)"}
    else:
        ad_transfer = None

    results = {"study": "CS07 Proteinbase reproduction (third-modality, wet-lab labels)",
               "attribution": "This work used Proteinbase by Adaptyv Bio under ODC-By license",
               "hits_vs_published": hits_table, "nipah_methods": methods,
               "expression": expression, "selection_replays": replays,
               "ad_transfer": ad_transfer,
               "headline_negative": next(
                   (f"{r['signal']}-selection on {r['target']} achieves "
                    f"{pct(r['top_quartile_hit'])} vs pool {pct(r['baseline_hit'])} "
                    f"(lift {r['lift']:+.1%})" for r in replays if r["lift"] <= 0), None)}
    (HERE / "results.json").write_text(json.dumps(results, indent=1))
    for t in hits_table:
        pub = f" (published {t['published']:.1%})" if t["published"] else ""
        print(f"  {t['target']:26} n={t['n']:4} hit={pct(t['hit_rate']):6}{pub}")
    print("methods:", *[f"\n  {m['method']:28} {m['hits']}/{m['n']} {pct(m['rate'])}" for m in methods])
    print("expression:", expression)
    if ad_transfer:
        print("AD transfer:", ad_transfer)
    for r in replays:
        print(f"  replay {r['target'][:12]:12} {r['signal']:5}: baseline "
              f"{pct(r['baseline_hit'])} -> top-quartile {pct(r['top_quartile_hit'])} "
              f"({r['lift']:+.1%})")


if __name__ == "__main__":
    main()
