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
- Single-replicate CRCs mean our CIs come from residual bootstrap, not
  well-to-well variance (stated per T0 conventions).
- The nM dose ladder caps at ~736 nM, so a compound active at 10 µM by the
  paper's criterion can be *undetectable* at their top dose — a real
  range-censoring case our verdict must refuse to number.
- We do not have the primary's 290k wells in-repo (opt-in fetch).

## Status

**WIP** — data frozen & checksummed (2026-10-04); the reproduction engine
(PubChem-format ingestion + blind refit + scoring) lands in the next
installments. Results will be written to `results.json` and summarized here
with the same "what the study found in our own machinery" honesty as CS04.
