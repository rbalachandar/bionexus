"""CS02 non-LLM baselines, recomputed OFFLINE from the frozen fixtures.

The agent's blinded ranking needs an LLM and a network and is recorded in
case_study.db; the comparators do not. Against the paper's 21 published
pIC50s, on the DEDUPLICATED training pool, this reports Spearman rho WITH a
bootstrap 95% CI for: the Morgan+RF model, a nearest-neighbour baseline
(pIC50 of the most Tanimoto-similar training compound; and a similarity-
weighted 5-NN), and Crippen logP (a trivial physico-chemical ordering).
With n = 21 every interval is wide — that is the point of printing them.

    python case-studies/02-az3246-hpk1/rf_baseline.py
"""
from __future__ import annotations

import importlib.util
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))
spec = importlib.util.spec_from_file_location("cs02", HERE / "run.py")
cs02 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cs02)

from bionexus import fixtures  # noqa: E402
from bionexus.adapters.models.sklearn_policy import MorganFingerprintRF  # noqa: E402
from bionexus.benchmark import spearman_ci  # noqa: E402


def _rows(activities, skip_doc=None):
    for a in activities:
        if skip_doc and a.get("document_chembl_id") == skip_doc:
            continue
        if a.get("standard_units") == "nM" and a.get("canonical_smiles"):
            try:
                v = float(a["standard_value"])
            except (TypeError, ValueError):
                continue
            if v > 0:
                yield a["canonical_smiles"], -math.log10(v * 1e-9)


def main() -> None:
    fixtures.materialize(HERE)
    acts = cs02.chembl_json(f"/activity.json?document_chembl_id="
                            f"{cs02.PAPER_DOC}&assay_type=B&limit=1000")
    by = defaultdict(list)
    for smi, p in _rows(acts.get("activities", [])):
        by[smi].append(p)
    paper = sorted(({"smiles": s, "pic50": statistics.mean(v)}
                    for s, v in by.items()), key=lambda c: -c["pic50"])
    truth = [c["pic50"] for c in paper]
    train, seen = [], set()
    url = (f"/activity.json?target_chembl_id={cs02.TARGET}"
           "&assay_type=B&limit=1000")
    while url and len(train) < 25000:
        d = cs02.chembl_json(url)
        for row in _rows(d.get("activities", []), skip_doc=cs02.PAPER_DOC):
            if row not in seen:                 # offset paging can repeat rows
                seen.add(row)
                train.append(row)
        nxt = (d.get("page_meta") or {}).get("next") or ""
        url = nxt.replace("https://www.ebi.ac.uk", "") \
                 .replace("/chembl/api/data", "", 1) or ""
        if not d.get("activities"):
            break
    smis = [c["smiles"] for c in paper]
    print(f"paper compounds: {len(paper)} · training rows (deduplicated): "
          f"{len(train)}")

    def report(name, preds):
        rho, lo, hi = spearman_ci(preds, truth)
        rank = 1 + sorted(preds, reverse=True).index(preds[0])
        print(f"  {name:<34} rho {rho:+.3f}  95% CI [{lo:+.2f}, {hi:+.2f}]"
              f"  · most potent ranked {rank}/{len(paper)}")

    model = MorganFingerprintRF(n_estimators=300, compute_ad=False)
    model.fit(train)
    report("Morgan+RF (300 trees)", [model.predict(x) for x in smis])

    from rdkit import Chem, DataStructs
    from rdkit.Chem import Crippen, rdFingerprintGenerator
    gen = rdFingerprintGenerator.GetMorganGenerator(radius=2, fpSize=2048)

    def fp(smi):
        m = Chem.MolFromSmiles(smi)
        return gen.GetFingerprint(m) if m else None
    tfps = [(fp(s), y) for s, y in train]
    tfps = [(f, y) for f, y in tfps if f is not None]
    nn1, nn5 = [], []
    for smi in smis:
        sims = DataStructs.BulkTanimotoSimilarity(fp(smi),
                                                  [f for f, _ in tfps])
        order = sorted(range(len(sims)), key=lambda i: -sims[i])[:5]
        nn1.append(tfps[order[0]][1])
        w = [max(sims[i], 1e-6) for i in order]
        nn5.append(sum(wi * tfps[i][1] for wi, i in zip(w, order)) / sum(w))
    report("nearest neighbour (top-1)", nn1)
    report("similarity-weighted 5-NN", nn5)
    report("Crippen logP (higher = more potent)",
           [Crippen.MolLogP(Chem.MolFromSmiles(x)) for x in smis])
    print("  agent (recorded runs, not re-run): rho +0.42 and +0.34 in the "
          "two sealed runs — raw scores were not kept, so no bootstrap; "
          "Fisher-z 95% interval for rho=+0.42 at n=21 is about [-0.02, +0.73]")


if __name__ == "__main__":
    main()
