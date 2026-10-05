"""TDC ADMET Benchmark Group — frozen, scaffold-split, fully offline.

Three absorption/distribution endpoints (Caco-2 permeability, human
intestinal absorption, blood-brain barrier) with TDC's canonical scaffold
splits (20% held-out test) shipped as checksummed fixtures in
`frozen/admet/` (see MANIFEST.json for provenance + citations). This
replaces URL-chasing: deepchem's S3 has inconsistent per-object ACLs
(Caco2/Tox21 403 today), and CI must never need the network (P8).

The models tier ladder (Random/Mean/CharRidge) fits on train_val and is
scored on TDC's exact test folds — the same folds the TDC leaderboard
uses — so our floor-relative numbers are comparable to published ones
without trusting any live download.
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterator

FROZEN = Path(__file__).parent / "frozen" / "admet"

#: name -> task type (TDC ADMET Group)
ADMET_DATASETS: dict[str, str] = {
    "caco2_wang": "regression",       # log apparent permeability, n=906
    "hia_hou": "classification",      # human intestinal absorption, n=578
    "bbb_martins": "classification",  # blood-brain barrier, n=1,975
}


class ADMETSplitDataset:
    """Frozen TDC ADMET dataset: .train() / .test() yield (smiles, label)."""

    def __init__(self, name: str, limit: int | None = None):
        if name not in ADMET_DATASETS:
            raise ValueError(f"unknown ADMET dataset: {name} "
                             f"(have {sorted(ADMET_DATASETS)})")
        self.name = name
        self.task = ADMET_DATASETS[name]
        self.limit = limit
        self.dir = FROZEN / name

    def _rows(self, split: str) -> Iterator[tuple[str, float]]:
        p = self.dir / f"{split}.csv"
        if not p.exists():
            raise FileNotFoundError(f"frozen fixture missing: {p}")
        n = 0
        with p.open(newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                smi, y = (row.get("Drug") or "").strip(), row.get("Y")
                if not smi or y in (None, "", "NA"):
                    continue
                yield smi, float(y)
                n += 1
                if self.limit and n >= self.limit:
                    return

    def train(self) -> Iterator[tuple[str, float]]:
        return self._rows("train_val")

    def test(self) -> Iterator[tuple[str, float]]:
        return self._rows("test")
