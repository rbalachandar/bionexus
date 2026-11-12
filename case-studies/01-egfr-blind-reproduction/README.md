# Case Study 01 — Blind Reproduction of the Original Tyrphostins Paper (Gazit et al., J. Med. Chem. 1989)

## Status: contaminated, illustrative — not evidence of agent skill

This study is kept as a **demonstration of the contamination problem and of the
harness's handling of it**, not as evidence that an agent can reproduce
science. The held-out paper is from 1989 and is in the model's training data
(the study's own probe confirms it), so the agent's identification of the
tyrphostin class is recognition, and its potency ranking cannot be separated
from memorized SAR. With 67 compounds every correlation here has a wide
interval (the RF baseline's 95% CI is +0.33…+0.75), so the agent-vs-model
comparison supports no ranking of the two. The post-cutoff studies (CS02,
CS04, CS08) are the ones designed to make a claim; read those for results.

## Summary

We asked an LLM agent to reproduce, blind, the core scientific contribution of
a landmark paper in EGFR inhibitor research — **without access to the paper or
its measurements**. The agent independently identified the same compound class,
named it with the same term the authors coined, and produced potency rankings
consistent with the published measurements.

**Verdict:** the quantitative reproduction check passed. The hypothesis check
passed on accuracy but is qualified by a confirmed pretraining-contamination
finding: the underlying model has prior knowledge of this specific literature,
so the correct attribution of Q1 is *recognition of a known compound class*
rather than *independent derivation*. See Contamination Analysis.

| Question | Result |
|---|---|
| Q1 — Does the agent, from structures alone, identify the paper's compound class and binding hypothesis? | **Identified correctly; qualified.** The agent named the compound class and pharmacophore accurately, but contamination analysis (below) confirmed prior model exposure to this literature; the result is therefore attributed to recognition rather than independent derivation |
| Q2 — Are blinded potency scores consistent with the published IC50s? | **PASS** — agent ranking ρ = +0.42…+0.58; trained model ρ = +0.56 (95% CI +0.33…+0.75; MAE 0.66 pIC50) — corrected, see below |

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
   26,255 unique published values across 2,573 assays (the held-out assay
   plus 2,572 others) — see the 2026-11-12 correction below.
2. **Held out.** The entire Gazit et al. 1989 assay (67 unique compounds after
   averaging repeats). Its values were excluded from all training and all
   prompts.
3. **Trained model.** Morgan fingerprints (2048-bit, radius 2) + Random Forest
   on the 26,255 deduplicated values from the 2,572 other assays.
4. **Blind agent task.** The agent (glm-5.1 via the Anthropic-compatible API)
   received the 45 structures and was asked for (a) the unifying binding
   hypothesis of the series and (b) a 0–100 potency score per compound. It saw
   **no values, no paper text, no ground truth**.
5. **Scoring.** Agent scores and model predictions were compared with the
   published IC50s (Spearman ρ; the paper's most potent compound's rank under
   each ranking). All steps recorded in the hash-chained provenance store.

## Results

### Q1 — Hypothesis identification: accurate, subject to a contamination qualification

The agent's top hypothesis (confidence 0.78), from structures alone:

> *"The series is a classic **tyrphostin**/erbstatin-like EGFR inhibitor set:
> arylidene-dicyanomalononitrile..."*

It independently used the same class name the authors coined in 1989, and
additionally proposed sub-hypotheses matching the paper's content: a
cyanoacrylate/thioamide subseries and a catechol-SAR pattern
(3,4-diOH optimal potency).

### Q2 — Result reproduction: passed

| Ranking source | Spearman ρ vs published pIC50 | Rank of the paper's most potent compound |
|---|---|---|
| Agent's blinded scores | +0.42 … +0.58 (varies by run — LLM nondeterminism) | 3–13 of 67 |
| Trained RF model | **+0.56** (95% CI +0.33…+0.75; MAE 0.66 pIC50 units) | 4 of 67 |

### Correction (2026-11-12): the training pool was duplicate-inflated

The original run reported "20,863 values across 126 papers" and RF ρ = +0.70
(MAE 0.67, most-potent compound rank 33 of 67). That pool was built with a
broken ChEMBL pagination cursor that returned the first pages repeatedly: of
the 20,863 rows, 19,080 were exact repeats (**1,783 unique**, 126 assays — a
small slice of EGFR's measured space). The held-out paper was also chosen as
"the largest assay", which only the duplication made it. The runner now names
the held-out assay (`CHEMBL674643`, Gazit et al. 1989) and the fixture is
the correctly fetched, deduplicated EGFR set. The RF comparator is recomputed
offline by `rf_baseline.py`:

| Training pool | RF ρ vs the paper | MAE | rank of most potent |
|---|---|---|---|
| original, as published | +0.70 | 0.67 | 33 of 67 |
| original pool re-run today (library versions differ) | +0.62 (CI +0.38…+0.79) | 0.76 | 39 of 67 |
| original pool, deduplicated (1,716 rows) | +0.55 (CI +0.30…+0.73) | 0.74 | 45 of 67 |
| **corrected: full EGFR fetch, deduplicated (26,255 rows)** | **+0.56** (CI +0.33…+0.75) | **0.66** | **4 of 67** |

Two things to take from this. The published +0.70 does not reproduce even on
its own pool (+0.62 now; the RF is not byte-stable across library versions),
and the corrected value is about +0.56 with a wide interval. The agent's
blinded ρ (+0.42…+0.58, LLM-dependent, not re-run) is therefore **comparable
to the trained model rather than clearly below it**; the Q2 PASS stands (both
rank the series well above chance) but the "calibrated model wins" contrast
drawn in case study 02 is withdrawn.

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

## Reproducibility (trust-audit label, Oct 10)

The corpus numbers above came from a live ChEMBL + LLM run; the
chain DB (case_study.db) is local-only and the run is not offline-
reproducible from the repo. Committed fixtures verify the INPUT bytes;
claims marked "qualified" in the table above reflect that limit honestly.
