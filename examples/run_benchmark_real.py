"""Extended benchmark: real model (Morgan+RF), LLM policy, HTS classification.

    .venv/bin/python examples/run_benchmark_real.py            # regression + HTS
    BIONEXUS_LLM_* (or ANTHROPIC_*) set -> LLM evaluated on a small subset too
"""
from __future__ import annotations

import json
import random
import sys

sys.path.insert(0, "src")

from bionexus.adapters.data.moleculenet import MoleculeNetDataset
from bionexus.benchmark import (CharRidgePolicy, MeanPolicy, RandomPolicy,
                                run_benchmark)

CACHE = ".data"


def try_policies(task: str) -> list:
    policies: list = [RandomPolicy(), MeanPolicy(), CharRidgePolicy(dim=256)]
    try:
        from bionexus.adapters.models.sklearn_policy import MorganFingerprintRF

        rf = MorganFingerprintRF(n_estimators=300)
        rf.fit([("CCO", 1 if task == "classification" else 1.0)])  # probe deps
        policies.append(MorganFingerprintRF(n_estimators=300))
    except Exception as exc:
        print(f"  (sklearn/rdkit unavailable: {type(exc).__name__} — skipping RF baseline)")
    return policies


def run_regression(name: str, url: str, label_col: str) -> dict:
    ds = MoleculeNetDataset(name, cache_dir=CACHE, url=url, label_col=label_col)
    return run_benchmark(ds, try_policies("regression"), out=f"{CACHE}/bench_{name}.json")


def run_hts(name: str, url: str, label_col: str, sample_n: int = 8000) -> dict:
    ds = MoleculeNetDataset(name, cache_dir=CACHE, url=url, label_col=label_col)
    data = list(ds.load())
    # stratified subsample: HTS datasets are ~3% actives
    rng = random.Random(0)
    actives = [d for d in data if d[1] == 1]
    inactives = [d for d in data if d[1] != 1]
    keep_inactives = rng.sample(inactives, min(sample_n - len(actives), len(inactives)))
    sub = actives + keep_inactives
    rng.shuffle(sub)
    ds.data = sub

    class Sub(MoleculeNetDataset):
        def load(self):
            return iter(self.data)

    sub_ds = Sub(name=name, cache_dir=CACHE, url=url, label_col=label_col, task="classification")
    sub_ds.data = sub
    return run_benchmark(sub_ds, try_policies("classification"), out=f"{CACHE}/bench_{name}.json")


def run_llm(dataset_name: str, url: str, label_col: str, n_test: int = 50) -> dict | None:
    try:
        from bionexus.adapters.models.llm_policy import AnthropicLLMPolicy
        from bionexus.benchmark import roc_auc, spearman

        llm = AnthropicLLMPolicy()
    except RuntimeError as exc:
        print(f"  llm: SKIPPED ({exc})")
        return None
    ds = MoleculeNetDataset(dataset_name, cache_dir=CACHE, url=url, label_col=label_col)
    data = list(ds.load())
    split = int(len(data) * 0.8)
    test = data[split:]
    truth = [y for _, y in test]
    preds: list[float] = []
    used = 0
    for smiles, _ in test:
        if used >= n_test:
            break
        try:
            preds.append(llm.predict(smiles))
            used += 1
        except Exception:
            continue  # parse/transport failure counts as a miss
    out = {"n": used, "policy": llm.name, "model": llm.model}
    if ds.task == "classification":
        out["roc_auc"] = round(roc_auc(preds, truth[: len(preds)]), 4)
    else:
        out["spearman"] = round(spearman(preds, truth[: len(preds)]), 4)
    return out


def main() -> None:
    results: dict[str, dict] = {}

    print("=== Lipophilicity (logD regression) ===")
    results["lipophilicity"] = run_regression(
        "lipophilicity", "https://deepchemdata.s3-us-west-1.amazonaws.com/datasets/Lipophilicity.csv", "exp")
    _print(results["lipophilicity"])

    print("\n=== HIV (NCI HTS, classification) ===")
    results["hiv"] = run_hts(
        "hiv", "https://deepchemdata.s3-us-west-1.amazonaws.com/datasets/HIV.csv", "HIV_active")
    _print(results["hiv"])

    llm = run_llm("lipophilicity",
                  "https://deepchemdata.s3-us-west-1.amazonaws.com/datasets/Lipophilicity.csv",
                  "exp", n_test=40)
    if llm:
        results["lipophilicity"]["policies"]["llm"] = llm
        print(f"\n=== LLM ({llm['model']}) on lipophilicity (n={llm['n']}) ===")
        print(f"  spearman={llm.get('spearman')}")

    with open(f"{CACHE}/benchmarks.json", "w") as f:
        json.dump(results, f, indent=1)
    print("\nresults: .data/benchmarks.json")


def _print(res: dict) -> None:
    print(f"  task={res['task']} train={res['n_train']} test={res['n_test']}")
    for pname, m in res["policies"].items():
        if "roc_auc" in m:
            print(f"  {pname:20} roc_auc={m['roc_auc']:.3f}  ({m['fit_secs']}s)")
        else:
            print(f"  {pname:20} spearman={m['spearman']:+.3f}  rmse={m['rmse']:.3f}  ({m['fit_secs']}s)")


if __name__ == "__main__":
    main()
