"""CS01 RF baseline, recomputed OFFLINE from the frozen EGFR fixture.

The agent's blinded ranking needs an LLM and is recorded in case_study.db; the
Random-Forest comparator does not. This recomputes it against the held-out
Gazit et al. 1989 assay (CHEMBL674643, 67 compounds) with a deduplicated
training pool of every other EGFR assay.

    python case-studies/01-egfr-blind-reproduction/rf_baseline.py
"""
from __future__ import annotations

import importlib.util
import statistics
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))
spec = importlib.util.spec_from_file_location("cs01", HERE / "run.py")
cs01 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cs01)

from proef import fixtures  # noqa: E402
from proef.adapters.models.sklearn_policy import MorganFingerprintRF  # noqa: E402
from proef.benchmark import spearman_ci  # noqa: E402


def main() -> None:
    fixtures.materialize(HERE)
    by_assay = cs01.load_all()
    held = by_assay.pop(cs01.HELD_ASSAY)
    by_smi = defaultdict(list)
    for r in held:
        by_smi[r["smiles"]].append(r["pic50"])
    paper = sorted(((s, statistics.mean(v)) for s, v in by_smi.items()),
                   key=lambda t: -t[1])
    train = [(r["smiles"], r["pic50"]) for v in by_assay.values() for r in v]
    model = MorganFingerprintRF(n_estimators=300, compute_ad=False)
    model.fit(train)
    preds = [model.predict(s) for s, _ in paper]
    truth = [p for _, p in paper]
    rho, lo, hi = spearman_ci(preds, truth)
    mae = sum(abs(a - b) for a, b in zip(preds, truth)) / len(truth)
    rank = 1 + sorted(preds, reverse=True).index(preds[0])
    print(f"held-out assay {cs01.HELD_ASSAY}: {len(paper)} compounds · "
          f"training: {len(train)} rows from {len(by_assay)} other assays")
    print(f"RF rho {rho:+.3f} (95% CI {lo:+.2f}..{hi:+.2f}) · MAE {mae:.2f} "
          f"pIC50 · rank of the most potent compound: {rank} of {len(paper)}")


if __name__ == "__main__":
    main()
