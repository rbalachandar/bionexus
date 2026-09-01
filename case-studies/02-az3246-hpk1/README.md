# Case Study 02 — Blind Prospective Reproduction: AZ3246, a Selective HPK1 Inhibitor (J. Med. Chem. 2025)

## Summary

A contamination-free blind reproduction. The held-out paper —
*"Discovery and Optimization of Pyrazine Carboxamide AZ3246, a Selective HPK1
Inhibitor"* (J. Med. Chem., 2025,
DOI: [10.1021/acs.jmedchem.4c02631](https://doi.org/10.1021/acs.jmedchem.4c02631)) —
was published **after the agent model's training cutoff**. Probes recorded in
provenance (step 0) confirm the model has no knowledge of the paper or of
AZ3246. The agent nevertheless derived the paper's optimization hypothesis from
45 structures alone, and its blinded potency ranking agreed with the paper's
measurements — **outperforming a Random Forest trained on ~25,600 other HPK1
measurements**.

**Verdict: both pre-registered reproduction checks PASSED, contamination-free.**

| Question | Result |
|---|---|
| Q1 — Does the agent derive the paper's optimization hypothesis (pyrazine-carboxamide core) from structures alone? | **PASS** — agent named the carboxamide core and the aminopyrimidine/pyrazine hinge-binder family; the paper series was confirmed to contain the pyrazine ring by substructure search |
| Q2 — Are blinded potency scores consistent with the published values? | **PASS** — agent ranking ρ = +0.42 (best compound rank 2/21); trained RF ρ = +0.08 |

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
2. **Trained model:** Morgan fingerprints + Random Forest on **25,637 other
   HPK1 binding measurements** from ChEMBL (excluding the paper's document).
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

### Q2 — Result reproduction: PASS, and a notable finding

| Ranking source | Spearman ρ vs published pIC50 | Rank of the paper's most potent compound |
|---|---|---|
| Agent's blinded scores | **+0.42** | 2 of 21 |
| Trained RF (25.6k HPK1 values) | +0.08 | 1 of 21 |

**The LLM agent's transferable reasoning outperformed the trained model's
calibrated predictions on this paper** — a measured finding the BioNexus
harness surfaced. The RF's poor transfer reflects a real phenomenon: the
paper's assay (cellular autophosphorylation readout) differs from the training
assays (biochemical), so its potency calibration does not transfer, while the
agent's structure-based comparative reasoning was more robust across the
assay shift. Case study 01 showed the complementary regime (calibrated model
ρ +0.70 vs agent +0.42…0.58). Neither intelligence dominates; the campaign
harness runs both, scores them against pre-registered criteria, and lets the
data decide — which is precisely the role BioNexus claims.

## Honest caveats

- The agent's hypothesis wording and scores vary between runs (LLM sampling);
  both executed runs identified the carboxamide core, but per-run ρ ranged
  +0.42…+0.57.
- n = 21 unique compounds (109 measurements include repeats); the ranked
  subset shown to the agent was 45 of the deposited rows sampled before
  deduplication.
- "Agent beat the model" is one paper, one assay shift; it motivates a
  systematic study of cross-assay transfer, not a general conclusion.
- Q1 is lexical + substructure-based; a human medicinal chemist should review
  the agent's full hypothesis text.

## Reproduce

```sh
python run.py   # from this directory
```

Requires network (ChEMBL) and `BIONEXUS_LLM_*` / `ANTHROPIC_*` env for the
agent. Artifacts: `case_study.db` — inspect with
`bn prove case-study-02 --db case_study.db --html report.html`.
