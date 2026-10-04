# Case Study 05 — The Paper Pilot (a proxy lab)

**Why this exists.** The roadmap's S-T2 "one lab pilot" needs a named
scientist with real plates and real workflow friction — something we cannot
manufacture, because this project has no lab access. A published paper with
its **raw deposited screening data** is the closest honest stand-in: we
install BioNexus on *their* data, exactly as we would a pilot lab's —
someone else's upload files, someone else's naming, someone else's claims —
and score our verdicts against theirs. This is the pilot rehearsal; the
feedback that only a human scientist gives (where they stop reading, which
two columns their layout lives in) is explicitly out of scope here and is
stated as such.

## The paper

Jacobs, Tokars, Zhou, Turlington, et al., *J. Med. Chem.* **56**(2):691–701
(2013) — PMID [23231439](https://pubmed.ncbi.nlm.nih.gov/23231439/),
PMC3569073. NIH MLPCN high-throughput screen of the molecular libraries
collection against **SARS-CoV 3CLpro (Mpro)**, leading to the non-covalent
dipeptide-like probe **ML188** with an X-ray structure.

The cascade, as deposited in PubChem (the submitters' own uploaded tables):

| stage | AID | tested | called active |
|---|---|---|---|
| primary, single point | 1706 | 290,893 | 405 |
| secondary, triplicate @ 6 µM | 1879 | 380 | **136** |
| confirmatory dose–response (nM ladder) | 1890 | 101 | **44** (57 inactive) |

The published claim we reproduce: the 101 confirmatory compounds resolve to
44 dose-response actives (paper text: IC50 < 10 µM), with the deposited
per-compound %inhibition curves as the raw evidence.

## Frozen data & provenance

- `fixtures/aid_1890.csv.gz`, `fixtures/aid_1879.csv.gz` — PubChem REST
  exports of the deposited submitter data tables, unmodified, checksummed
  (`bn fixtures verify case-studies/05-paper-pilot`). AID 1706 (290k rows)
  is opt-in via `scripts/fetch_raw_data.sh --primary` (repo hygiene).
- `sources.json` — paper metadata, cascade counts, fetch date.
- The vendor dirt we must survive is authentic: header/data column-count
  mismatch (10 inhibition values per row, 6 named in the header — the
  concentrations live in the `RESULT_*` meta rows), `=` qualifier columns,
  PubChem's `PUBCHEM_*` schema, trailing blank lines.

## Blinding rules (what we may NOT read)

Before producing our verdicts, the engine may use only:
1. SMILES (`PUBCHEM_EXT_DATASOURCE_SMILES`),
2. the per-concentration %inhibition values + their concentrations
   (parsed from the `RESULT_ATTR_CONC_*` meta rows),
3. for the secondary: mean %inhibition, SD, and the single test
   concentration.

The submitters' own **IC50 / LogIC50 / Hill columns, QUALIFIER, and
PUBCHEM_ACTIVITY_OUTCOME are the answer key** — read only at scoring time.
The authors' manuscript numbers likewise. This is the CS04 discipline
applied to a wet-lab cascade.

## Protocol

1. **Ingest** — extend `bionexus.labread` to parse the PubChem deposited
   table natively (new "vendor": schema-dense meta preamble + multi-point
   CRC rows). No hand-transformation of the upload: if `bn read` needs an
   edit to consume a real deposition, that is a finding, not a workaround.
2. **Refit blind** — per compound, Hill fit with CI (`fit_ic50_ci`,
   residual bootstrap) from the raw inhibition columns only.
3. **Verdict** — apply the registered gate (their claim: < 10 µM active)
   through `SuccessCriteria.classify`: CI straddling ⇒ abstain, and record
   every abstention loudly.
4. **Score vs the answer key** — confusion matrix against the deposited
   ACTIVE/INACTIVE calls; per-compound table for every disagreement or
   abstention, with the reason (curve shape, single bad point, plateau
   absence).
5. **Series view** — group the 44 actives' chemistry (chemotype rollup via
   `bionexus.series`) — does our independent grouping match the paper's
   scaffold story (furyl amide / dipeptide-like series → ML188)?

## What we expect to be honest about

- The deposited "Active/Inactive" is itself an expert call, not ground
  truth — our score is *agreement with the lab*, not with nature.
- Single-replicate curves (30 read = 10 doses × 3 technical) mean our CIs
  come from residual bootstrap, not independent-well variance (stated per
  the repo's small-n conventions).
- The dose ladder runs 0.003 → 59.6 µM across ten points. An early draft of
  this README misread it as capped at 736 nM — because **the REST export
  header names only the first six dose columns** (the real ladder lives in
  the `RESULT_ATTR_CONC_MICROMOL` meta row). The parser reads the meta row;
  the header is not trusted. This is exactly the deposition dirt CS05
  exists to test.
- Compounds that never cross 50% inside the window are a *range* statement
  (no active fit below ~300 µM / never reached), never a hard "IC50 = X".
- We do not have the primary's 290k wells in-repo (opt-in fetch).

## Results (run 2026-10-04)

Engine: `bionexus.labread` now parses PubChem deposited tables natively
(format `pubchem`, structurally blind — see `tests/test_labread_pubchem.py`
for the contract), and `run.py` scores the locked verdicts against the
answer key (`results.json`).

| | deposited (their call) Active | deposited Inactive |
|---|---|---|
| **ours Active** | 32 (TP) | **0 (FP)** |
| **ours Inactive** | 1 (FN) | 54 (TN) |
| **ours Abstain** | 11 | 3 |

- **Agreement on decisive verdicts: 98.9% (86/87). Zero false actives** —
  we never claimed a compound active that the lab called inactive.
- **Abstain rate 13.9%** — and almost all abstentions sit exactly where
  honesty demands: the lab's own IC50s for them run 4.6–9.9 µM, i.e. their
  *point estimates* clear the 10 µM gate by a hair, while our bootstrap CIs
  straddle it (e.g. 9.7 [9.5–10.5] µM). A single-replicate ladder cannot
  separate "potent enough" from "borderline" there; the paper drew a hard
  line and got a number; we drew the line and refused the number. That is
  the honest answer to "same or better": the same decisive chemistry, and
  14 claims we will not counterfeit.
- **The one disagreement is disclosed in full**: SID17412961 (CID 5734490) —
  their IC50 8.94 µM (Active); our fit 11.69 µM with CI [10.24–16.04],
  entirely *above* the gate → Inactive. Curve-level max inhibition 73%, so
  it is a shallow partial: a judgment call, precisely the profile our CI
  rule exists to expose rather than hide. We do not get to keep the paper's
  number — we keep the argument.
- **Cross-plate audit of their own cascade**: 5 compounds whose secondary
  single-point %inhibition at 6 µM deviates >25 points from what their own
  deposited dose-response curve predicts (Hill-1 at 6 µM) — reported, not
  adjudicated; plate-to-plate variance is real, and the direction splits
  both ways (their earlier weak ones, their later strong ones). An
  originally naively-flagged set of 23 "conflicts" was mostly consistent
  once we predicted from their curve instead of demanding >50% at 6 µM —
  a scoring-logic bug our audit caught, and fixed the same day.
- **Series view**: confirmed actives spread across small chemotypes (top:
  3× thienyl-pyrazoline, 3× quinolone-carboxamide, 2× cyclopropyl-amide
  pyridyl series, 2× coumarin carbonate), consistent with the paper's story
  of diverse initial hits consolidated into one dipeptide-like series
  (tert-butyl-phenyl amides) during optimization — 2 of our confirmed
  actives carry the tert-butyl handle of the ML188 lineage.

**Reproducible**: `.venv/bin/python case-studies/05-paper-pilot/run.py`
(fixtures verified by checksum first; any drift aborts). Engine tests:
`tests/test_labread_pubchem.py`.

## Status

**Reproduced** — protocol + frozen data + blind engine + scoring shipped;
`results.json` carries every per-compound verdict with its CI, every
disagreement, and the cross-plate audit. The human half of the pilot (a
named scientist feeling the workflow) remains open by honest definition.
