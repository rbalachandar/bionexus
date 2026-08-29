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

## First results — `examples/run_benchmark.py`

Split: first 80% train / last 20% test. Baselines are deliberately weak floors;
the point is that real model adapters must beat them and the harness is honest.

**Lipophilicity (logD, n_test=840)**

| Policy | Spearman | RMSE |
|---|---|---|
| random | +0.044 | 1.225 |
| predict-mean | −0.043 | 1.200 |
| char3gram-ridge (stdlib) | **+0.545** | **0.993** |
| rdkit-desc-ridge | +0.476 | 1.067 |

**ESOL (solubility, n_test=226)**

| Policy | Spearman | RMSE |
|---|---|---|
| random | +0.027 | 2.029 |
| predict-mean | +0.040 | 2.027 |
| char3gram-ridge (stdlib) | +0.712 | 1.398 |
| rdkit-desc-ridge | **+0.873** | **1.051** |

Reference points from literature for context: published GNN/chemprop models
reach ~0.8–0.9 Spearman / ~0.6–0.8 RMSE on Lipophilicity — i.e. our floors leave
clear headroom, and an `fm_predict_property` adapter wired to a real model is
the next row of this table.

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
