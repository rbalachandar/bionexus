"""Benchmark harness (P2: policies vs datasets, all offline-capable).

A Policy maps a SMILES -> prediction. The harness scores policies on a
DatasetAdapter with standard metrics and records results as provenance-friendly
JSON. Built-in baselines:

- RandomPolicy            — sanity floor
- CharRidgePolicy         — pure-Python char n-gram + ridge regression (no deps)
- RDKitDescPolicy         — RDKit descriptors + ridge (requires [bio-rdkit])

These are deliberately weak baselines: their job is to validate the harness and
give a floor that real model adapters must beat.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from pathlib import Path
from typing import Any, Protocol


class Policy(Protocol):
    name: str

    def fit(self, data: list[tuple[str, float]]) -> None: ...

    def predict(self, smiles: str) -> float: ...


# ---------------------------------------------------------------- baselines

class RandomPolicy:
    name = "random"

    def fit(self, data):  # noqa: ARG002
        self.mean = sum(y for _, y in data) / len(data)

    def predict(self, smiles: str) -> float:  # noqa: ARG002
        h = int(hashlib.sha256(smiles.encode()).hexdigest()[:8], 16)
        return self.mean + (h % 100) / 100.0 - 0.5


class MeanPolicy:
    name = "predict-mean"

    def fit(self, data):
        self.mean = sum(y for _, y in data) / len(data)

    def predict(self, smiles: str) -> float:  # noqa: ARG002
        return self.mean


class CharRidgePolicy:
    """Hashed char 3-gram features + closed-form ridge regression. Stdlib only."""

    name = "char3gram-ridge"

    def __init__(self, ngram: int = 3, l2: float = 1.0, dim: int = 256):
        self.ngram, self.l2, self.dim = ngram, l2, dim

    def _featurize(self, smiles: str) -> list[float]:
        v = [0.0] * self.dim
        for i in range(len(smiles) - self.ngram + 1):
            g = smiles[i:i + self.ngram]
            h = int(hashlib.md5(g.encode()).hexdigest()[:8], 16)  # noqa: S324
            v[h % self.dim] += 1.0
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]

    def fit(self, data: list[tuple[str, float]]) -> None:
        X = [self._featurize(s) for s, _ in data]
        y = [label for _, label in data]
        self.mean = sum(y) / len(y)
        yc = [v - self.mean for v in y]
        d = self.dim
        ata = [[0.0] * d for _ in range(d)]
        aty = [0.0] * d
        for xi, yi in zip(X, yc):
            nz = [(j, v) for j, v in enumerate(xi) if v]
            for a, va in nz:
                aty[a] += va * yi
                for b, vb in nz:
                    ata[a][b] += va * vb
        for j in range(d):
            ata[j][j] += self.l2
        self.w = _solve(ata, aty)

    def predict(self, smiles: str) -> float:
        x = self._featurize(smiles)
        return self.mean + sum(w * v for w, v in zip(self.w, x) if v)


def _solve(a: list[list[float]], b: list[float]) -> list[float]:
    """Gaussian elimination with partial pivoting."""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(m[r][col]))
        m[col], m[piv] = m[piv], m[col]
        pv = m[col][col]
        if abs(pv) < 1e-12:
            continue
        m[col] = [v / pv for v in m[col]]
        for r in range(n):
            if r != col and m[r][col]:
                f = m[r][col]
                m[r] = [rv - f * cv for rv, cv in zip(m[r], m[col])]
    return [m[i][n] for i in range(n)]


class RDKitDescPolicy:
    """RDKit descriptors + ridge (optional extra [bio-rdkit])."""

    name = "rdkit-desc-ridge"

    def __init__(self, l2: float = 1.0):
        self.l2 = l2

    def _desc(self, smiles: str) -> list[float]:
        from rdkit import Chem
        from rdkit.Chem import Descriptors, rdMolDescriptors as rd

        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return [0.0] * 6
        return [
            Descriptors.MolWt(mol), Descriptors.MolLogP(mol), Descriptors.TPSA(mol),
            rd.CalcNumHBD(mol), rd.CalcNumHBA(mol), rd.CalcNumRotatableBonds(mol),
        ]

    def fit(self, data):
        X = [self._desc(s) for s, _ in data]
        y = [v for _, v in data]
        n = len(y)
        self.means = [sum(row[j] for row in X) / n for j in range(6)]
        self.stds = [math.sqrt(sum((row[j] - self.means[j]) ** 2 for row in X) / n) or 1.0
                     for j in range(6)]
        Xn = [[(row[j] - self.means[j]) / self.stds[j] for j in range(6)] for row in X]
        yc = [v for _, v in data]
        self.mean = sum(yc) / n
        yc = [v - self.mean for v in yc]
        ata = [[sum(Xn[i][a] * Xn[i][b] for i in range(n)) + (self.l2 if a == b else 0.0)
                for b in range(6)] for a in range(6)]
        aty = [sum(Xn[i][a] * yc[i] for i in range(n)) for a in range(6)]
        self.w = _solve(ata, aty)

    def predict(self, smiles: str) -> float:
        row = self._desc(smiles)
        xn = [(row[j] - self.means[j]) / self.stds[j] for j in range(6)]
        return self.mean + sum(w * v for w, v in zip(self.w, xn))


# ------------------------------------------------------------------ metrics

def spearman(pred: list[float], true: list[float]) -> float:
    def rank(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        for rank_pos, i in enumerate(order):
            r[i] = rank_pos
        return r
    n = len(pred)
    rp, rt = rank(pred), rank(true)
    mp, mt = sum(rp) / n, sum(rt) / n
    num = sum((rp[i] - mp) * (rt[i] - mt) for i in range(n))
    den = math.sqrt(sum((rp[i] - mp) ** 2 for i in range(n))
                    * sum((rt[i] - mt) ** 2 for i in range(n)))
    return num / den if den else 0.0


def rmse(pred: list[float], true: list[float]) -> float:
    return math.sqrt(sum((p - t) ** 2 for p, t in zip(pred, true)) / len(pred))


def run_benchmark(dataset: Any, policies: list[Policy], train_frac: float = 0.8,
                  out: str | Path | None = None) -> dict[str, Any]:
    data = list(dataset.load())
    split = int(len(data) * train_frac)
    train, test = data[:split], data[split:]
    results: dict[str, Any] = {
        "dataset": getattr(dataset, "name", "unknown"),
        "task": getattr(dataset, "task", "regression"),
        "n_train": len(train), "n_test": len(test),
        "timestamp": time.time(),
        "policies": {},
    }
    truth = [y for _, y in test]
    for policy in policies:
        t0 = time.time()
        policy.fit(train)
        preds = [policy.predict(s) for s, _ in test]
        results["policies"][policy.name] = {
            "spearman": round(spearman(preds, truth), 4),
            "rmse": round(rmse(preds, truth), 4),
            "fit_secs": round(time.time() - t0, 3),
        }
    if out:
        Path(out).write_text(json.dumps(results, indent=1))
    return results
