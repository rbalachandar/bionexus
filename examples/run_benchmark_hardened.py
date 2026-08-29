"""Hardened benchmark: scaffold split, multi-seed variance, GNN row.

    .venv/bin/python examples/run_benchmark_hardened.py
"""
from __future__ import annotations

import json
import sys

sys.path.insert(0, "src")

from bionexus.adapters.data.moleculenet import MoleculeNetDataset
from bionexus.benchmark import (CharRidgePolicy, MeanPolicy, RandomPolicy,
                                run_benchmark)
from bionexus.adapters.models.sklearn_policy import MorganFingerprintRF

SEEDS = (0, 1, 2)
CACHE = ".data"
LIPO_URL = "https://deepchemdata.s3-us-west-1.amazonaws.com/datasets/Lipophilicity.csv"


def _print(res: dict) -> None:
    print(f"  split={res['split']} seeds={res['seeds']} test={res['n_test']}")
    for pname, m in res["policies"].items():
        if "roc_auc" in m:
            print(f"  {pname:20} roc_auc={m['roc_auc']}")
        else:
            print(f"  {pname:20} spearman={m['spearman']}  rmse={m['rmse']}")


def main() -> None:
    ds = MoleculeNetDataset("lipophilicity", cache_dir=CACHE, url=LIPO_URL)
    policies: list = [RandomPolicy(), MeanPolicy(), CharRidgePolicy(dim=256),
                      MorganFingerprintRF(n_estimators=300)]
    try:
        from bionexus.adapters.models.gnn_policy import GnnPolicy

        policies.append(GnnPolicy(epochs=40))
    except ImportError:
        print("torch unavailable — skipping GNN row")
    res = run_benchmark(ds, policies, split="scaffold", seeds=SEEDS,
                        out=f"{CACHE}/bench_lipo_hardened.json")
    print("=== Lipophilicity — scaffold split, 3 seeds ===")
    _print(res)

    all_results = {"lipophilicity_scaffold": res}
    with open(f"{CACHE}/benchmarks.json", "w") as f:
        json.dump(all_results, f, indent=1)
    print("\nresults: .data/benchmarks.json")


if __name__ == "__main__":
    main()
