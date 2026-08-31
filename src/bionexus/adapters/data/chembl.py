"""ChEMBL published-bioactivity dataset adapter (case-study data source).

Fetches real, published binding measurements for a target (default: EGFR /
CHEMBL203) from the ChEMBL web services, converts IC50 nM -> pIC50, caches
locally. These are values from actual experiments in published papers — the
ground truth for case study 01.
"""
from __future__ import annotations

import csv
import math
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

BASE = "https://www.ebi.ac.uk/chembl/api/data/activity.json"


def fetch_target_activities(target_chembl_id: str = "CHEMBL203",
                            cache_dir: str | Path = ".data",
                            max_records: int = 20000) -> Path:
    """Download published binding activities (pChEMBL >= 5 preferred) for a
    target; cache as CSV. Returns the cache path."""
    cache = Path(cache_dir) / f"chembl_{target_chembl_id}.csv"
    if cache.exists():
        return cache
    cache.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, str]] = []
    cursor = ""
    while len(rows) < max_records:
        url = (f"{BASE}?target_chembl_id={target_chembl_id}"
               f"&assay_type=B&limit=1000" + (f"&cursor={cursor}" if cursor else ""))
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310
            data = json_loads(resp.read())
        activities = data.get("activities", [])
        for a in activities:
            smiles = a.get("canonical_smiles")
            value = a.get("standard_value")
            units = a.get("standard_units")
            pc = a.get("pchembl_value")
            if not smiles or value in (None, "None"):
                continue
            try:
                v = float(value)
            except (TypeError, ValueError):
                continue
            if units == "nM" and v > 0:
                pic50 = -math.log10(v * 1e-9)
            elif pc is not None:
                pic50 = float(pc)
            else:
                continue
            if math.isnan(pic50):
                continue
            rows.append({"smiles": smiles, "pic50": f"{pic50:.3f}",
                         "assay": a.get("assay_chembl_id", "")})
        meta = data.get("page_meta", {})
        cursor = meta.get("next", "") and meta["next"].split("cursor=")[-1]
        if not cursor or not activities:
            break
    with cache.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["smiles", "pic50", "assay"])
        w.writeheader()
        w.writerows(rows)
    return cache


def json_loads(b: bytes) -> dict:
    import json
    return json.loads(b)


class ChemblDataset:
    """DatasetAdapter over the cached ChEMBL activities (pic50 regression)."""

    name = "chembl-egfr"
    task = "regression"

    def __init__(self, target_chembl_id: str = "CHEMBL203",
                 cache_dir: str | Path = ".data", limit: int | None = None,
                 min_pic50: float | None = None):
        path = fetch_target_activities(target_chembl_id, cache_dir)
        self.records: list[tuple[str, float]] = []
        with path.open(newline="") as f:
            for row in csv.DictReader(f):
                v = float(row["pic50"])
                if min_pic50 is not None and v < min_pic50:
                    continue
                self.records.append((row["smiles"], v))
                if limit and len(self.records) >= limit:
                    break

    def load(self) -> Iterator[tuple[str, float]]:
        yield from self.records
