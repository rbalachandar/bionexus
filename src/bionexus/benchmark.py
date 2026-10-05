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
from typing import Callable
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
        from bionexus.ad import ApplicabilityDomain
        self.ad = ApplicabilityDomain.from_smiles([s for s, _ in data],
                                                  basis="char3")

    def predict(self, smiles: str) -> float:
        x = self._featurize(smiles)
        return self.mean + sum(w * v for w, v in zip(self.w, x) if v)

    def predict_with_ad(self, smiles: str) -> tuple[float, dict]:
        """predict() + nearest-neighbour Tanimoto applicability-domain
        stamp (char 3-gram basis): the number always comes back, but
        outside the training chemistry it carries `extrapolation` so
        abstention rules widen and cards chip — the local-model guard."""
        return self.predict(smiles), self.ad.check(smiles)


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
        # AVERAGE ranks over tie blocks: resolving ties by input order
        # smuggles an arbitrary ordering into rho (and tightens bootstrap
        # CIs falsely for coarse/integer predictions)
        order = sorted(range(len(v)), key=lambda i: (v[i], i))
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while (j + 1 < len(order)
                   and v[order[j + 1]] == v[order[i]]):
                j += 1
            avg = (i + j) / 2.0
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
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


def roc_auc(scores: list[float], labels: list[float]) -> float:
    """Mann-Whitney AUC with tie handling. Labels are 0/1."""
    pos = [s for s, l in zip(scores, labels) if l == 1]
    neg = [s for s, l in zip(scores, labels) if l != 1]
    if not pos or not neg:
        return 0.5
    allv = sorted(scores)
    # average ranks (1-based) over tie blocks
    rank: dict[float, float] = {}
    i = 0
    while i < len(allv):
        j = i
        while j < len(allv) and allv[j] == allv[i]:
            j += 1
        avg = (i + 1 + j) / 2  # mean of 1-based positions i+1..j
        rank[allv[i]] = avg
        i = j
    rsum = sum(rank[s] for s in pos)
    n, n1 = len(scores), len(pos)
    return (rsum - n1 * (n1 + 1) / 2) / (n1 * (n - n1))


SCAFFOLD_BACKEND = "rdkit"
try:  # probe once: a silent fallback would change what 'scaffold split' MEANS
    import rdkit  # noqa: F401
except ImportError:
    SCAFFOLD_BACKEND = "none"


def scaffold(smiles: str) -> str:
    """Bemis-Murcko scaffold (requires rdkit). WITHOUT rdkit the SMILES
    itself is returned — grouping then controls EXACT duplicates only,
    not scaffold neighbors. run_benchmark stamps that into the results
    so a leakage claim is never made on the wrong grouping."""
    if SCAFFOLD_BACKEND == "rdkit":
        from rdkit.Chem.Scaffolds import MurckoScaffold
        from rdkit import Chem
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return smiles
        return MurckoScaffold.MurckoScaffoldSmiles(mol=mol, includeChirality=False)
    return smiles


def scaffold_split(data: list[tuple[str, float]], train_frac: float = 0.8, seed: int = 0):
    """Group by scaffold, assign whole scaffolds to train/test. Prevents
    near-duplicate leakage between train and test molecules."""
    groups: dict[str, list] = {}
    for item in data:
        groups.setdefault(scaffold(item[0]), []).append(item)
    keys = sorted(groups, key=lambda k: (len(groups[k]), k))
    import random as _random

    _random.Random(seed).shuffle(keys)
    cut = int(len(data) * train_frac)
    train, test, n = [], [], 0
    for k in keys:
        (train if n < cut else test).extend(groups[k])
        n += len(groups[k])
    return train, test


def run_benchmark(dataset: Any, policies: list[Policy], train_frac: float = 0.8,
                  split: str = "index", seeds: tuple[int, ...] = (0,),
                  out: str | Path | None = None) -> dict[str, Any]:
    """Evaluate policies. `split`: "index" (temporal-ish) or "scaffold" (leak-safe).
    Multiple `seeds` -> per-policy mean±std for the primary metric."""
    data = list(dataset.load())
    classification = getattr(dataset, "task", "regression") == "classification"
    results: dict[str, Any] = {
        "dataset": getattr(dataset, "name", "unknown"),
        "task": dataset.task if hasattr(dataset, "task") else "regression",
        "split": split, "seeds": list(seeds),
        "split_note": ("scaffold grouping needs rdkit: exact-duplicate "
                       "grouping only — scaffold-neighbour leakage NOT "
                       "controlled"
                       if split == "scaffold" and SCAFFOLD_BACKEND != "rdkit"
                       else None),
        "n_train": int(len(data) * train_frac), "n_test": len(data) - int(len(data) * train_frac),
        "timestamp": time.time(),
        "policies": {},
    }
    for policy in policies:
        t0 = time.time()
        primary: list[float] = []
        last_entry: dict[str, Any] = {}
        for seed in seeds:
            policy_name = policy.name
            if split == "scaffold":
                train, test = scaffold_split(data, train_frac, seed)
            else:
                cut = int(len(data) * train_frac)
                train, test = data[:cut], data[cut:]
            policy.fit(train)
            preds = [policy.predict(s) for s, _ in test]
            truth = [y for _, y in test]
            entry: dict[str, Any] = {"fit_secs": round(time.time() - t0, 3)}
            if classification:
                entry["roc_auc"] = round(roc_auc(preds, truth), 4)
                primary.append(entry["roc_auc"])
            else:
                entry["spearman"] = round(spearman(preds, truth), 4)
                entry["rmse"] = round(rmse(preds, truth), 4)
                primary.append(entry["spearman"])
            last_entry = entry
        if len(seeds) > 1:
            mean = sum(primary) / len(primary)
            std = (sum((v - mean) ** 2 for v in primary) / len(primary)) ** 0.5
            metric = "roc_auc" if classification else "spearman"
            last_entry[metric] = f"{mean:.4f}±{std:.4f}"
            last_entry[f"{metric}_mean"] = round(mean, 4)
            last_entry[f"{metric}_std"] = round(std, 4)
        results["policies"][policy_name] = last_entry
    if out:
        Path(out).write_text(json.dumps(results, indent=1))
    return results


# ------------------------------------------------------------- statistics
# Small-n honesty toolkit: every headline number in reports and case studies
# should carry a bootstrap CI, and multi-test screens should be FDR-corrected.

def bootstrap_ci(values: list[float], stat: Callable[[list[float]], float] | None = None,
                 n_boot: int = 2000, seed: int = 7,
                 alpha: float = 0.05) -> tuple[float, float]:
    """Percentile bootstrap CI for a statistic over a sample (default mean)."""
    import random

    if not values:
        return (float("nan"), float("nan"))
    stat = stat or (lambda vs: sum(vs) / len(vs))
    rng = random.Random(seed)
    n = len(values)
    boots = sorted(stat([values[rng.randrange(n)] for _ in range(n)])
                   for _ in range(n_boot))
    lo = boots[int(alpha / 2 * n_boot)]
    hi = boots[min(n_boot - 1, int((1 - alpha / 2) * n_boot))]
    return round(lo, 4), round(hi, 4)


def spearman_ci(pred: list[float], true: list[float], n_boot: int = 1000,
                seed: int = 7) -> tuple[float, float, float]:
    """(rho, ci_low, ci_high) — bootstrap over paired observations."""
    import random

    rho = spearman(pred, true)
    if len(pred) < 4:
        return rho, float("nan"), float("nan")
    rng = random.Random(seed)
    n = len(pred)
    pairs = list(zip(pred, true))
    boots = []
    for _ in range(n_boot):
        sample = [pairs[rng.randrange(n)] for _ in range(n)]
        boots.append(spearman([p for p, _ in sample], [t for _, t in sample]))
    boots.sort()
    return rho, round(boots[int(0.025 * n_boot)], 4), \
        round(boots[min(n_boot - 1, int(0.975 * n_boot))], 4)


def benjamini_hochberg(pvals: list[float], fdr: float = 0.10) -> list[bool]:
    """BH significance flags: discoveries at the requested false-discovery
    rate. Empty input -> empty output."""
    n = len(pvals)
    if n == 0:
        return []
    order = sorted(range(n), key=lambda i: pvals[i])
    k_max = 0
    for rank, i in enumerate(order, start=1):
        if pvals[i] <= fdr * rank / n:
            k_max = rank
    flags = [False] * n
    if k_max:
        for i in order[:k_max]:
            flags[i] = True
    return flags


# ------------------------------------------- assay-selection metrics
# Shared vocabulary with assaybench (Genentech/AssayLoop): a method ranks or
# sequentially acquires from a universe; these score how early the hits show.

def fraction_of_hits(picked, hits) -> float:
    picked = set(picked)
    return len(picked & set(hits)) / len(hits) if hits else float("nan")


def percent_essential(picked, hits) -> float:
    """Fraction of what you spent budget on that actually was a hit."""
    return len(set(picked) & set(hits)) / len(picked) if picked else 0.0


def enrichment_factor(picked, universe, hits, budget: int | None = None) -> float:
    base = len(set(hits)) / len(set(universe))
    top = list(picked)[: budget or len(picked)]
    if not top or base <= 0:
        return float("nan")
    return (len(set(top) & set(hits)) / len(top)) / base


def shortfall(picked, hits) -> float:
    """Fraction of true hits still missing after the picks."""
    return 1.0 - fraction_of_hits(picked, hits)


def adjusted_nauc(rounds: list[list], universe, hits) -> float:
    """Cumulative hit-recall vs fraction-of-library assayed, rescaled so a
    random policy scores 0 and the oracle ordering (all hits first) scores 1.
    Same convention as assaybench's adjusted_nauc."""
    hits = set(hits)
    U = len(list(universe)) or 1
    if not hits:
        return float("nan")
    seen: set = set()
    xs, cum, found = [], [], 0
    for rnd in rounds:
        new = [g for g in rnd if g not in seen]
        seen.update(new)
        found += len(set(new) & hits)
        xs.append(len(seen) / U)
        cum.append(found / len(hits))
    if not xs or xs[-1] <= 0:
        return float("nan")

    def auc(xs_, ys_):
        a, px, py = 0.0, 0.0, 0.0
        for x, y in zip(xs_, ys_):
            a += (y + py) / 2 * (x - px)
            px, py = x, y
        return a

    xf = xs[-1]
    A = auc(xs, cum)
    xo = min(len(hits) / U, xf)
    oracle = xo / 2 + max(0.0, xf - xo)
    random_ = xf ** 2 / 2
    if oracle <= random_:
        return float("nan")
    return round((A - random_) / (oracle - random_), 4)
