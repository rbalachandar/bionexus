"""Run the first real benchmark: MoleculeNet Lipophilicity (4,200 molecules).

    .venv/bin/python -m examples.run_benchmark
"""
from __future__ import annotations

import json
import sys

sys.path.insert(0, "src")

from bionexus.adapters.data.moleculenet import MoleculeNetDataset
from bionexus.benchmark import (CharRidgePolicy, MeanPolicy, RandomPolicy,
                                RDKitDescPolicy, run_benchmark)

DATASETS = {
    "lipophilicity": "https://deepchemdata.s3-us-west-1.amazonaws.com/datasets/Lipophilicity.csv",
    "esol": "https://deepchemdata.s3-us-west-1.amazonaws.com/datasets/delaney-processed.csv",
}


def main() -> None:
    all_results: dict[str, dict] = {}
    for name, url in DATASETS.items():
        try:
            ds = MoleculeNetDataset(name, url=url,
                                    label_col="exp" if name == "lipophilicity"
                                    else "measured log solubility in mols per litre")
            data = list(ds.load())
        except Exception as exc:  # offline: skip with note
            print(f"{name}: SKIPPED ({exc})")
            continue
        policies: list = [RandomPolicy(), MeanPolicy(), CharRidgePolicy(dim=256)]
        try:
            RDKitDescPolicy().fit([("CCO", 1.0)])  # probe rdkit
            policies.append(RDKitDescPolicy())
        except Exception:
            print(f"{name}: rdkit not available — skipping descriptor baseline")
        res = run_benchmark(ds, policies, out=f".data/bench_{name}.json")
        all_results[name] = res
        print(f"\n=== {name} ({res['task']}, train={res['n_train']}, test={res['n_test']}) ===")
        for pname, m in res["policies"].items():
            print(f"  {pname:20} spearman={m['spearman']:+.3f}  rmse={m['rmse']:.3f}  "
                  f"({m['fit_secs']}s)")
    with open(".data/benchmarks.json", "w") as f:
        json.dump(all_results, f, indent=1)
    print("\nresults: .data/benchmarks.json")


if __name__ == "__main__":
    main()
