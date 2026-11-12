# Case Study 02 — Blind Prospective Reproduction: AZ3246, a Selective HPK1 Inhibitor (J. Med. Chem. 2025)

## Summary

A contamination-free blind reproduction. The held-out paper —
*"Discovery and Optimization of Pyrazine Carboxamide AZ3246, a Selective HPK1
Inhibitor"* (J. Med. Chem., 2025,
DOI: [10.1021/acs.jmedchem.4c02631](https://doi.org/10.1021/acs.jmedchem.4c02631)) —
was published **after the agent model's training cutoff**. Probes recorded in
provenance (step 0) confirm the model has no knowledge of the paper or of
AZ3246. The agent nevertheless derived the paper's optimization hypothesis from
structures alone, and its blinded potency ranking was positively correlated with
the paper's measurements: ρ = +0.42 and +0.34 in the two original sealed runs, and
a mean of +0.48 (run-averaged ρ = +0.52, 95% CI [+0.14, +0.78]) over five repeated
runs with a second model (`gpt-6-luna`). That is above chance and above every
non-LLM baseline's point estimate (all about +0.1), **but with only 21 compounds
the intervals still overlap, so it is not a significant difference** (see below).

**Verdict: Q1 (hypothesis) passed, contamination-free; Q2 (ranking) is positive but not statistically distinguishable from the baselines at n = 21.**

| Question | Result |
|---|---|
| Q1 — Does the agent derive the paper's optimization hypothesis (pyrazine-carboxamide core) from structures alone? | **PASS** — agent named the carboxamide core and the aminopyrimidine/pyrazine hinge-binder family; the paper series was confirmed to contain the pyrazine ring by substructure search |
| Q2 — Are blinded potency scores consistent with the published values? | **PASS** — agent ranking ρ = +0.42 (best compound rank 2/21); trained RF ρ = +0.125 (deduplicated pool; was +0.08) |

## The held-out paper

> *"Discovery and Optimization of Pyrazine Carboxamide AZ3246, a Selective
> HPK1 Inhibitor."* J. Med. Chem. 2025.
> DOI: [10.1021/acs.jmedchem.4c02631](https://doi.org/10.1021/acs.jmedchem.4c02631)
> ChEMBL document CHEMBL6103590, assay [CHEMBL6105768](https://www.ebi.ac.uk/chembl/assay_report_card/CHEMBL6105768/)
> (HPK1 / MAP4K1, target CHEMBL5749; 21 unique compounds, 109 measured values).

## Why this design is contamination-free

Unlike [case study 01](../01-egfr-blind-reproduction/), where the model had
memorized the 1989 tyrphostins literature, this paper post-dates the model's
training cutoff. Two probes (run before the task and recorded as provenance):

1. *"Do you have specific knowledge of [the paper]?"* → **"No. My training data
   has a cutoff..."**
2. *"What do you know about the compound AZ3246?"* → **no specific knowledge;
   only generic HPK1 background**

Both answers are stored in the provenance chain — the no-knowledge claim is
part of the audit trail, not an assertion.

## Method

1. **Held out:** all 109 measured values from the paper (21 unique compounds).
2. **Trained model:** Morgan fingerprints + Random Forest on **7,078 other
   (deduplicated) HPK1 binding measurements** from ChEMBL (excluding the paper's document).
3. **Blind agent task:** 45 structures sampled across the potency range;
   the agent stated binding-hypothesis families and scored every compound
   0–100. It saw no values.
4. **Q1:** agent hypothesis checked against the paper's optimization core
   (pyrazine-carboxamide), verified chemically by substructure search over the
   paper's compounds.
5. **Q2:** agent scores and RF predictions compared with the paper's measured
   pIC50s (Spearman ρ; rank of the most potent compound).

## Results

### Q1 — Hypothesis derivation: PASS

The agent's top hypothesis (confidence 0.8):

> *"An aminopyrimidine(or aminopyrazine)-carboxamide core bearing an N-methyl
> ...pyrazolyl group..."* — correctly identifying the carboxamide hinge-binder
> core, the morpholine aryl substitution, and a pyrazolyl regioisomer subseries,
> plus flagging indole/indazole outliers as deviating from the core.

### Q2 — Result reproduction: positive, but within noise at n = 21

Spearman ρ against the paper's 21 published pIC50s. The non-LLM rows are
recomputed offline by `rf_baseline.py` with bootstrap 95% intervals. The agent
rows are the two original sealed runs (raw scores not kept) and five repeated
runs of `agent_runs.py` with `gpt-6-luna` (raw scores in
`agent_runs_gpt-6-luna.json`).

| Ranking source | Spearman ρ | 95% interval |
|---|---|---|
| Agent, original runs 1 and 2 (earlier model) | +0.42, +0.34 | ≈ [−0.02, +0.73] (Fisher-z, run 1) |
| Agent, 5 runs with `gpt-6-luna` | +0.15, +0.69, +0.57, +0.46, +0.54 (mean +0.48, SD 0.18) | — |
| Agent, `gpt-6-luna` run-averaged scores | **+0.52** | [+0.14, +0.78] |
| Morgan + RF (7,078 deduplicated HPK1 values) | +0.125 | [−0.38, +0.52] |
| Nearest neighbour (top-1 Tanimoto) | +0.146 | [−0.37, +0.73] |
| Similarity-weighted 5-NN | +0.153 | [−0.33, +0.68] |
| Crippen logP (a trivial ordering) | +0.095 | [−0.50, +0.54] |

The agent's point estimates sit above every baseline, and with `gpt-6-luna`
the interval excludes zero. But the baselines' intervals reach +0.5 to +0.7
and overlap the agent's, so **we cannot claim the agent beats the trained
models** at n = 21. A single run is noisy (+0.15 to +0.69 across five), which
is why one number should not be trusted. The two agent models differ, and
`gpt-6-luna`'s probes found no evidence of leakage (variant probe clean, 0/3;
it recognised only the title given in the probe), which is not proof of none.
A plausible reason the trained models do poorly is assay shift (the paper's
cellular readout vs biochemical training assays), but that is a hypothesis.
A decisive test needs more compounds, or the same protocol on a second
post-cutoff paper.

## Correction (2026-11-11): RF baseline recomputed on the deduplicated pool

The original figures (RF ρ = +0.08, rank 1 of 21, "25,637 measurements") were
computed on a training pool inflated by an offset-pagination bug: the cursor
was mangled, repeated pages returned the same rows, and duplicates were
counted as independent measurements. The pool is now fetched correctly
(30 pages, **7,078 unique measurements**), frozen in `fixtures/`, and the RF
comparator is recomputed offline by `rf_baseline.py`:

| | original (duplicate-inflated) | corrected |
|---|---|---|
| training rows | 25,637 | **7,078** |
| RF Spearman ρ vs the paper | +0.08 | **+0.125** |
| rank of the most potent compound | 1 of 21 | **6 of 21** |
| RF after removing training rows that share a Murcko scaffold with the paper series | — | +0.03 |

The agent's numbers (ρ = +0.42, best compound rank 2/21) are **unchanged**:
the agent never sees the training pool, and the LLM run was not repeated (it
needs a network and an API key). The qualitative result holds — the agent's
blinded ranking is better than the RF's — but the RF is a little better and
the margin smaller than first reported (+0.42 vs +0.125, not +0.42 vs +0.08).

## Reproducibility (trust-audit label, Oct 10; updated Nov 11)

The RF comparator is now reproducible offline from the frozen fixtures
(`python case-studies/02-az3246-hpk1/rf_baseline.py`). The agent half is a
post-cutoff study that needs network + an LLM; the sealed chain
(`case_study.db`, local-only) carries the contamination probes and verdicts.
Treat the agent's ρ as recorded, not reproducible.
