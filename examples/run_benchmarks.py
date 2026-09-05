"""Consolidated benchmark runner.

    python examples/run_benchmarks.py              # default: scaffold split, 3 seeds
    python examples/run_benchmarks.py --llm        # + LLM ablation (needs env)
    python examples/run_benchmarks.py --fast       # skip RF (fast, no sklearn)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bionexus.adapters.data.chembl import ChemblDataset
from bionexus.benchmark import CharRidgePolicy, MeanPolicy, RandomPolicy, \
    run_benchmark
from bionexus.core.contracts import Envelope, ProtocolOp, ProtocolStep, \
    ProtocolSubmission, ReagentSpec, SampleKind, SampleSpec
from bionexus.core.interfaces import system_actor

CACHE = Path(__file__).parent / ".benchmark_cache"
SEEDS = (0, 1, 2)


def _policies(skip_sklearn: bool = False) -> list:
    policies: list = [RandomPolicy(), MeanPolicy(), CharRidgePolicy(dim=256)]
    try:
        from bionexus.adapters.models.sklearn_policy import MorganFingerprintRF
        policies.append(MorganFingerprintRF(n_estimators=300))
    except ImportError:
        print("  (sklearn unavailable — skipping RF)")
    return policies


def run_dataset(name: str, url: str, label_col: str, max_records: int = 20000) -> dict:
    ds = ChemblDataset(name, cache_dir=str(CACHE), url=url,
                       label_col=label_col, limit=max_records)
    res = run_benchmark(ds, _policies(), split="scaffold", seeds=SEEDS,
                        out=str(CACHE / f"bench_{name}.json"))
    print(f"\n=== {name} (scaffold split, {len(SEEDS)} seeds) ===")
    print(f"  train={res['n_train']}  test={res['n_test']}")
    for pname, m in res["policies"].items():
        metric = m.get("roc_auc") or m.get("spearman") or "?"
        print(f"  {pname:20} {metric}")
    return res


def main() -> None:
    results: dict[str, dict] = {}

    datasets = [
        ("lipophilicity", "https://deepchemdata.s3-us-west-1.amazonaws.com/datasets/Lipophilicity.csv", "exp"),
        ("esol", "https://deepchemdata.s3-us-west-1.amazonaws.com/datasets/delaney-processed.csv",
         "measured log solubility in mols per litre"),
        ("hiv_hts", "https://deepchemdata.s3-us-west-1.amazonaws.com/datasets/HIV.csv", "HIV_active"),
    ]
    for name, url, col in datasets:
        print(f"\n{'='*50}")
        print(f"  {name}")
        print(f"{'='*50}")
        results[name] = run_dataset(name, url, col)

    # LLM ablation (optional)
    if "--llm" in sys.argv:
        try:
            from bionexus.adapters.models.llm_policy import AnthropicLLMPolicy
            llm = AnthropicLLMPolicy()
            print(f"\n=== LLM ablation ({llm.model}) ===")
            ds = ChemblDataset("lipophilicity", cache_dir=str(CACHE),
                               url=datasets[0][1], label_col="exp")
            data = list(ds.load())
            split = int(len(data) * 0.8)
            test = data[split:split + 40]
            scores = [llm.predict(s) for s, _ in test]
            truth = [y for _, y in test]
            from bionexus.benchmark import spearman
            rho = spearman(scores, truth)
            results["llm_ablation"] = {"model": llm.model_version,
                                       "spearman": round(rho, 4), "n": len(test)}
            print(f"  LLM spearman: {rho:+.4f} (n={len(test)})")
        except Exception as exc:
            print(f"  LLM ablation skipped: {exc}")

    out = CACHE / "all_results.json"
    out.write_text(json.dumps(results, indent=1))
    print(f"\nall results: {out}")


if __name__ == "__main__":
    main()
