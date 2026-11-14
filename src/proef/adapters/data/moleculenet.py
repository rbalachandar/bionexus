"""Dataset adapters (T4.5-adjacent): public chemistry/biology datasets.

A DatasetAdapter yields (input, label) examples plus task metadata. First
adapter: MoleculeNet CSV datasets (Lipophilicity, BACE, ESOL...), downloaded
once and cached. Tests use embedded fixtures so CI stays offline (P8).
"""
from __future__ import annotations

import csv
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Protocol

MOLECULENET = {
    # name -> (url, label column, smiles column, task type)
    "lipophilicity": ("https://deepchemdata.s3-us-west-1.amazonaws.com/datasets/Lipophilicity.csv",
                      "exp", "smiles", "regression"),
    "esol": ("https://deepchemdata.s3-us-west-1.amazonaws.com/datasets/delaney-processed.csv",
             "measured log solubility in mols per litre", "smiles", "regression"),
    "bace": ("https://deepchemdata.s3-us-west-1.amazonaws.com/datasets/bace.csv",
             "Class", "smiles", "classification"),
    "hiv": ("https://deepchemdata.s3-us-west-1.amazonaws.com/datasets/HIV.csv",
            "HIV_active", "smiles", "classification"),
}


class DatasetAdapter(Protocol):
    name: str
    task: str  # "regression" | "classification"

    def load(self) -> Iterator[tuple[Any, Any]]: ...


class MoleculeNetDataset:
    """CSV-backed MoleculeNet dataset with local caching."""

    def __init__(self, name: str, cache_dir: str | Path = ".data",
                 url: str | None = None, label_col: str = "exp",
                 smiles_col: str = "smiles", task: str = "regression",
                 limit: int | None = None):
        if name in MOLECULENET and url is None:
            url, label_col, smiles_col, task = MOLECULENET[name]
        self.name = name
        self.task = task
        self.label_col, self.smiles_col = label_col, smiles_col
        self.limit = limit
        self.path = Path(cache_dir) / f"{name}.csv"
        if not self.path.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            urllib.request.urlretrieve(url, self.path)  # noqa: S310

    def load(self) -> Iterator[tuple[str, float]]:
        n = 0
        with self.path.open() as f:
            for row in csv.DictReader(f):
                yield row[self.smiles_col], float(row[self.label_col])
                n += 1
                if self.limit and n >= self.limit:
                    return
