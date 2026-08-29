"""LLM ablation on Lipophilicity: zero-shot vs few-shot vs tool-augmented.

    BIONEXUS_LLM_* (or ANTHROPIC_*) env required. n per policy kept small.
    .venv/bin/python examples/run_llm_ablation.py
"""
from __future__ import annotations

import json
import sys

sys.path.insert(0, "src")

from bionexus.adapters.data.moleculenet import MoleculeNetDataset
from bionexus.benchmark import spearman
from bionexus.adapters.models.llm_policy import (
    AnthropicLLMPolicy, FewShotLLMPolicy, ToolAugmentedLLMPolicy)

N_TEST = 40


def evaluate(policy, test):
    preds, truth = [], []
    for s, y in test:
        try:
            preds.append(policy.predict(s))
            truth.append(y)
        except Exception:
            continue
        if len(preds) >= N_TEST:
            break
    return {"n": len(preds), "spearman": round(spearman(preds, truth), 4)}


def main() -> None:
    ds = MoleculeNetDataset("lipophilicity", cache_dir=".data",
                            url="https://deepchemdata.s3-us-west-1.amazonaws.com/datasets/Lipophilicity.csv")
    data = list(ds.load())
    split = int(len(data) * 0.8)
    train, test = data[:split], data[split:split + N_TEST * 3]

    results = {}
    policies = [
        ("llm zero-shot", AnthropicLLMPolicy()),
        ("llm-fewshot (k=8)", FewShotLLMPolicy(k=8)),
        ("llm+descriptors (k=5)", ToolAugmentedLLMPolicy(k=5)),
    ]
    for label, pol in policies:
        pol.fit(train)  # exemplar retrieval setup (no training calls)
        r = evaluate(pol, test)
        results[label] = r
        print(f"{label:26} spearman={r['spearman']:+.4f} (n={r['n']})")
    with open(".data/bench_llm_ablation.json", "w") as f:
        json.dump(results, f, indent=1)


if __name__ == "__main__":
    main()
