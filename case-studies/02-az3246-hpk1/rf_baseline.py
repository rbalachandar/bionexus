"""CS02 RF baseline, recomputed OFFLINE from the frozen fixtures.

The agent's blinded ranking needs an LLM and a network and is recorded in
case_study.db; the Random-Forest comparator does not. This recomputes the RF
Spearman rho against the paper's 21 published pIC50s on the DEDUPLICATED
training pool, so that half of the headline comparison is reproducible.

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
from bionexus.benchmark import spearman  # noqa: E402


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
    truth = [c["pic50"] for c in paper]
    model = MorganFingerprintRF(n_estimators=300)
    model.fit(train)
    preds = [model.predict(c["smiles"]) for c in paper]
    rho = spearman(preds, truth)
    top_rank = 1 + sorted(preds, reverse=True).index(preds[0])
    print(f"paper compounds: {len(paper)} · training rows (deduplicated): "
          f"{len(train)}")
    print(f"RF rho vs published pIC50: {rho:+.3f} · rank of the most potent "
          f"compound: {top_rank} of {len(paper)}")


if __name__ == "__main__":
    main()
