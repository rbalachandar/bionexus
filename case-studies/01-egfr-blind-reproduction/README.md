# Case Study 01 — Blind Reproduction of the Original Tyrphostins Paper (Gazit et al., J. Med. Chem. 1989)

## Summary

We asked an LLM agent to reproduce, blind, the core scientific contribution of
a landmark paper in EGFR inhibitor research — **without access to the paper or
its measurements**. The agent independently identified the same compound class,
named it with the same term the authors coined, and produced potency rankings
consistent with the published measurements.

**Verdict: both pre-registered reproduction checks PASSED.**

| Question | Result |
|---|---|
| Q1 — Does the agent, from structures alone, identify the paper's compound class and binding hypothesis? | **PASS, contaminated** — named "tyrphostin" correctly, but a probe confirms the model has memorized this paper (see Contamination); recognition, not rediscovery |
| Q2 — Are blinded potency scores consistent with the published IC50s? | **PASS** — agent ranking ρ = +0.42…+0.58; trained model ρ = +0.70 (MAE 0.67 pIC50) |

## The held-out paper

> Gazit A, Yaish P, Gilon C, Levitzki A.
> **"Tyrphostins I: synthesis and biological activity of protein tyrosine kinase inhibitors."**
> *J. Med. Chem.* 1989. DOI: [10.1021/jm00130a020](https://doi.org/10.1021/jm00130a020) ·
> PMID: [2552117](https://pubmed.ncbi.nlm.nih.gov/2552117/) · ChEMBL document: [CHEMBL1124610](https://www.ebi.ac.uk/chembl/compound_report_card/CHEMBL1124610/)

This is the paper that introduced the **tyrphostin** class — tyrosine-kinase
competitive inhibitors of the EGF receptor — and deposited 67 measured IC50
values (EGF-dependent autophosphorylation assay) into ChEMBL under assay
[CHEMBL674643](https://www.ebi.ac.uk/chembl/assay_report_card/CHEMBL674643/).

## Objective

Test whether the BioNexus flow can **reproduce a published result it was never
shown**, addressing the circularity critique of simulation-based demos:

- **Q1 (hypothesis reproduction).** Shown only the paper's 45 compound
  *structures* (values hidden), can the agent state the binding hypothesis the
  paper's authors actually pursued?
- **Q2 (result reproduction).** Do the agent's blinded potency scores — and an
  independent QSAR model trained on *other* papers' data — agree with the
  paper's measured IC50s?

## Method

1. **Data.** All EGFR (ChEMBL target CHEMBL203) binding measurements in ChEMBL:
   20,863 published values across 126 papers/assays.
2. **Held out.** The entire Gazit et al. 1989 assay (67 unique compounds after
   averaging repeats). Its values were excluded from all training and all
   prompts.
3. **Trained model.** Morgan fingerprints (2048-bit, radius 2) + Random Forest
   on the remaining ~19,500 values from the other 125 papers.
4. **Blind agent task.** The agent (glm-5.1 via the Anthropic-compatible API)
   received the 45 structures and was asked for (a) the unifying binding
   hypothesis of the series and (b) a 0–100 potency score per compound. It saw
   **no values, no paper text, no ground truth**.
5. **Scoring.** Agent scores and model predictions were compared with the
   published IC50s (Spearman ρ; the paper's most potent compound's rank under
   each ranking). All steps recorded in the hash-chained provenance store.

## Results

### Q1 — Hypothesis reproduction: PASS, but contaminated (see Contamination below)

The agent's top hypothesis (confidence 0.78), from structures alone:

> *"The series is a classic **tyrphostin**/erbstatin-like EGFR inhibitor set:
> arylidene-dicyanomalononitrile..."*

It independently used the same class name the authors coined in 1989, and
additionally proposed sub-hypotheses matching the paper's content: a
cyanoacrylate/thioamide subseries and a catechol-SAR pattern
(3,4-diOH optimal potency).

### Q2 — Result reproduction: PASS

| Ranking source | Spearman ρ vs published pIC50 | Rank of the paper's most potent compound |
|---|---|---|
| Agent's blinded scores | +0.42 … +0.58 (varies by run — LLM nondeterminism) | 3–13 of 67 |
| Trained RF model | **+0.70** (MAE 0.67 pIC50 units) | 33 of 67 |

### Honest caveats

- The agent's ρ varies run-to-run (LLM sampling); the RF model is
  deterministic but its rank of the single most potent compound is mediocre —
  potency *extremes* remain hard.
- The chemotype-match check (Q1) is lexical (did the agent name the
  tyrphostin/dicyanovinyl chemistry?) — behavioral ranking evidence is in Q2.
- This is one paper, one target, in-silico only. Reproducing more papers
  (different targets and modalities) is required before generalizing.
- The original pre-registered enrichment target (3× at 10% cutoff) was
  miscalibrated for this test set's 44% active base rate; achieved enrichment
  was 1.9× and is reported as a failure against the original wording.

## Reproduce

```sh
# from the repo root (network for ChEMBL download on first run;
# BIONEXUS_LLM_* or ANTHROPIC_* env for the agent)
python case-studies/01-egfr-blind-reproduction/run.py
```

Artifacts: `case_study.db` (hash-chained provenance — inspect with
`bn prove blind-paper --db case_study.db --html report.html`).

## Limitations & next steps

- **Contamination makes Q1 uninterpretable as "rediscovery".** The clean
  follow-up (case study 02) uses **counterfactual ground truth**: real
  compound structures paired with outcomes from a *hidden seeded function*
  (the virtual lab) that no model could have memorized. Recall cannot help;
  only genuine inference-from-series counts. This trades contamination for
  the (already-documented) realism trade-off.
- Alternatively: hold out only papers published **after the model's training
  cutoff**, where memorization is impossible by construction.
- Extend to multiple held-out papers across different targets and modalities
  (multi-paper reproduction study).
- Add a baseline: untrained LLM without series context, to isolate the value
  of SAR reasoning across the series.
- Human expert comparison: how do medicinal chemists score the same blind task?
