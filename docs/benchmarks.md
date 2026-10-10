# Benchmarks

The framework ships a benchmark harness (`bionexus/benchmark.py`) + dataset
adapters (`bionexus/adapters/data/`) so policies and model adapters can be
evaluated on public data. Datasets download-on-first-use to `.data/`; tests use
embedded fixtures (P8: CI stays offline).

## Candidate public datasets (landscape)

| Dataset | Task | Size | Use in BioNexus |
|---|---|---|---|
| **MoleculeNet Lipophilicity** | logD regression | 4,200 | ✅ wired — baseline harness |
| **MoleculeNet ESOL** | solubility regression | 1,128 | ✅ wired |
| **MoleculeNet BACE / BBBP / Tox21** | classification | 1.5k–7.8k | next: classification metrics |
| **Therapeutics Data Commons (TDC)** | ADME, HTS, DTI, drugcombo | 20+ benchmarks | adapter planned — the natural home for property/HTS benchmarks |
| **DOCKSTRING** | docking scores (58 targets) | 260k | virtual-screening benchmark for `e.sim.docking` tools |
| **PDBbind** | binding affinity (structures) | 19k complexes | structure-based policy benchmark |
| **ProteinGym** | protein mutation effect | 217 assays | Biology Agent / protein-FM benchmark |
| **FLIP / TAPE** | protein fitness/function | varies | protein-adapter benchmarks |

## First results — historical, from since-retired scripts (`run_benchmark.py`,
`run_benchmark_real.py`); the maintained equivalent is `examples/run_benchmarks.py`
plus the graded `bn eval` models tier

Split: first 80% train / last 20% test (HIV: stratified subsample, 3% actives).
Baselines are deliberately weak floors; the point is that real model adapters
must beat them and the harness is honest.

**Lipophilicity (logD regression, n_test=840)**

| Policy | Spearman | RMSE |
|---|---|---|
| random | +0.044 | 1.225 |
| predict-mean | −0.043 | 1.200 |
| char3gram-ridge (stdlib) | +0.545 | 0.993 |
| **morgan2048-rf** (rdkit+sklearn) | **+0.711** | **0.821** |
| LLM zero-shot (glm-5.1, n=40) | −0.143 | — |

**HIV (NCI high-throughput screen, classification, n_test=1,600)**

| Policy | ROC-AUC |
|---|---|
| random / predict-mean | 0.500 |
| char3gram-ridge (stdlib) | 0.757 |
| **morgan2048-rf** (rdkit+sklearn) | **0.855** |

**LLM ablation — Lipophilicity (n=40, glm-5.1; `run_llm_ablation.py` was retired —
table is a historical record, not reproducible from the repo)**

| Policy | Spearman |
|---|---|
| LLM zero-shot | −0.082 |
| LLM few-shot (k=8 similar exemplars) | +0.636 |
| **LLM + RDKit descriptor tool (k=5)** | **+0.709** |

Reading the table:

- **Morgan2048+RF at 0.855 AUC on HIV** matches the literature range for FP+RF
  (~0.83–0.85) — the harness reproduces known results, which is the point.
- **The tool-augmentation result is the headline**: the same LLM goes from
  *no signal* (−0.08) to *matching the trained RF baseline* (+0.71) once it is
  given (a) similar measured examples and (b) computed descriptors. LLMs should
  not be property oracles; they are good at interpreting tool outputs — which is
  exactly the agent-loop design of this framework.

Reference points from literature for context: published GNN/chemprop models
reach ~0.8–0.9 Spearman / ~0.6–0.8 RMSE on Lipophilicity — headroom remains
for a real `fm_predict_property` adapter.

## How to add a benchmark row

```python
from bionexus.adapters.data.moleculenet import MoleculeNetDataset
from bionexus.benchmark import run_benchmark
from my_models import MyPropertyPolicy

results = run_benchmark(MoleculeNetDataset("lipophilicity"),
                        policies=[MyPropertyPolicy()],
                        out=".data/bench_mine.json")
```

Policies implement `fit(data)` / `predict(smiles)` — the same shape as
`ModelProvider.predict`, so model adapters wrap into policies trivially.

## LLM evaluation setup

`AnthropicLLMPolicy` reads `BIONEXUS_LLM_BASE_URL` / `BIONEXUS_LLM_TOKEN` /
`BIONEXUS_LLM_MODEL` (falls back to `ANTHROPIC_BASE_URL` /
`ANTHROPIC_AUTH_TOKEN` / Anthropic model env vars). It speaks the Anthropic
Messages protocol over stdlib urllib and works with any compatible endpoint
(including LLM proxies). LLM calls are expensive — evaluate with `n_test`
caps, as the retired `run_benchmark_real.py` did (models tier of `bn eval`
covers this ground now).
