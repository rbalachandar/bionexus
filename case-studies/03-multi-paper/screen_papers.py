"""Screen recent ChEMBL documents for case-study-worthy papers:
>=20 unique compounds with IC50/Ki in nM/uM on a single target that has a
decent training pool (>=1000 other measurements).

    python screen_papers.py [--year 2025] [--limit 80]
"""
from __future__ import annotations

import json
import math
import sys
import time
import urllib.request
from collections import defaultdict


def chembl(path: str, tries: int = 6, soft: bool = False):
    for i in range(tries):
        try:
            req = urllib.request.Request(
                "https://www.ebi.ac.uk/chembl/api/data" + path,
                headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=90) as r:  # noqa: S310
                return json.loads(r.read())
        except Exception:
            if i == tries - 1:
                return {} if soft else None
            time.sleep(4 * (i + 1))


def pic50(a: dict) -> float | None:
    if a.get("standard_type") not in ("IC50", "Ki", "EC50", "AC50"):
        return None
    units, val = a.get("standard_units"), a.get("standard_value")
    if not val or units not in ("nM", "uM", "µM", "M"):
        return None
    try:
        v = float(val)
    except ValueError:
        return None
    nm = v * 1e9 if units == "M" else (v * 1000.0 if units in ("uM", "µM") else v)
    return -math.log10(nm * 1e-9) if 0 < nm < 1e6 else None


def main() -> None:
    year = "2025"
    limit = 80
    if "--year" in sys.argv:
        year = sys.argv[sys.argv.index("--year") + 1]
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])

    docs = chembl(f"/document.json?year={year}&document_type=PUBLICATION"
                  f"&limit={limit}&offset=0").get("documents", [])
    print(f"screening {len(docs)} {year} publications...")
    good = []
    for i, d in enumerate(docs):
        did = d["document_chembl_id"]
        acts = chembl(f"/activity.json?document_chembl_id={did}&limit=1000", soft=True)
        rows = acts.get("activities", []) if acts else []
        if len(rows) < 15:
            continue
        by_target: dict[str, set] = defaultdict(set)
        for a in rows:
            p = pic50(a)
            if p is not None and a.get("canonical_smiles") and a.get("target_chembl_id"):
                by_target[a["target_chembl_id"]].add(a["canonical_smiles"])
        if not by_target:
            continue
        target = max(by_target, key=lambda k: len(by_target[k]))
        n = len(by_target[target])
        if n < 20:
            continue
        pool = chembl(f"/activity.json?target_chembl_id={target}&limit=1",
                      soft=True) or {}
        pool_n = (pool.get("page_meta") or {}).get("total_count", 0)
        if pool_n < 1000:
            continue
        good.append({"doc": did, "target": target, "n_compounds": n,
                     "pool": pool_n, "title": (d.get("title") or "")[:90],
                     "doi": d.get("doi")})
        print(f"  [{i}] {did} target={target} compounds={n} pool={pool_n}")
    print(f"\n{len(good)} case-study-worthy papers")
    with open("papers_found.json", "w") as f:
        json.dump(good, f, indent=1)
    print("saved: papers_found.json")


if __name__ == "__main__":
    main()
