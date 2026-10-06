#!/usr/bin/env python3
"""Derive slim, gzipped fixtures from the Proteinbase full download.

Source stays in .data/ (40 MB, gitignored). Derived tables + MANIFEST.json
(sha256 of source + derived, counts, ODC-By attribution) are committed so
the study is reproducible without the original file's weight.
"""
import csv, gzip, hashlib, json
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
SOURCE = Path(".data/proteinbase_all_data_28_01_2026.csv")  # repo-root rel


def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main():
    rows = list(csv.DictReader(SOURCE.open(newline="", encoding="utf-8-sig")))
    proteins, pairs = [], []
    for r in rows:
        pid = r["id"]
        d = {"id": pid, "method": r["designMethod"] or "unlabeled",
             "len": len(r["sequence"] or ""), "plddt": "", "mpnn": "",
             "expr_fail": "False", "seq": (r["sequence"] or "").strip()}
        for e in json.loads(r["evaluations"] or "[]"):
            m, ty, tgt, val = (e.get("metric"), e.get("type"),
                               e.get("target"), e.get("value"))
            if ty == "computational" and m == "esmfold_plddt":
                d["plddt"] = val
            elif ty == "computational" and m == "proteinmpnn_score":
                d["mpnn"] = val
            elif m == "expressed" and ty == "experimental":
                if val is False or str(val).lower() == "false":
                    d["expr_fail"] = "True"
            elif ty == "experimental" and m in ("binding", "binding_strength",
                                                "kd") and tgt:
                k = {"protein_id": pid, "target": tgt, "bound": "",
                     "strength": "", "kd_nM": ""}
                if m == "binding":
                    pairs[:] = pairs  # no-op keeps mypy calm
                    k["bound"] = str(bool(val))
                elif m == "binding_strength":
                    k["strength"] = str(val or "")
                else:
                    k["kd_nM"] = str(val or "")
                pairs.append({**{x: y for x, y in k.items() if y},
                              "protein_id": pid, "target": tgt})
        proteins.append(d)
    # merge pairs by (protein, target)
    merged = {}
    for p in pairs:
        m = merged.setdefault((p["protein_id"], p["target"]),
                              {"protein_id": p["protein_id"],
                               "target": p["target"], "bound": "",
                               "strength": "", "kd_nM": ""})
        for k in ("bound", "strength", "kd_nM"):
            if p.get(k):
                m[k] = p[k]
    plist = sorted(merged.values(), key=lambda x: (x["target"], x["protein_id"]))

    out = {}
    for name, cols, data in (
            ("proteins.csv", ["id", "method", "len", "plddt", "mpnn",
                              "expr_fail", "seq"], proteins),
            ("pairs.csv", ["protein_id", "target", "bound", "strength",
                           "kd_nM"], plist)):
        raw = ",".join(cols) + "\n" + "\n".join(
            ",".join(str(x[c]) for c in cols) for x in data) + "\n"
        gz = HERE / "fixtures" / (name + ".gz")
        gz.write_bytes(gzip.compress(raw.encode(), 9))
        out[name] = {"sha256_raw": hashlib.sha256(raw.encode()).hexdigest(),
                     "rows": len(data), "bytes_gz": gz.stat().st_size}

    manifest = {
        "source": {"file": SOURCE.name,
                   "sha256": sha(SOURCE),
                   "url": "https://storage.proteinbase.com/"
                          "proteinbase_all_data_28_01_2026.csv",
                   "retrieved": "2026-10-05"},
        "license": "ODC-By v1.0 — attribution: 'This work used Proteinbase "
                   "by Adaptyv Bio under ODC-By license'",
        "derived": out,
        "semantics": "pair = (protein, target) experimental binding unit; "
                     "binding value is boolean; kd_nM only where measured",
    }
    (HERE / "fixtures" / "MANIFEST.json").write_text(
        json.dumps(manifest, indent=1) + "\n")
    print(json.dumps(manifest["derived"], indent=1))


if __name__ == "__main__":
    main()
