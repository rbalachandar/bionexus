# Case Study 04 — Prospective Hit-to-Lead on Real Published EGFR Data

**The question (S-T0 of the current roadmap):** the earlier studies proved the
loop can *reproduce* published results blind. This one asks the harder,
forward-looking question: run the real gated DMTA machinery over a real
ChEMBL-deposited target world with the field's actual futures removed, and
score every claim the loop makes against measurements it could not have
known. No simulator carries the load here — the potency truths are published
experimental values.

## The setup

- **Corpus:** EGFR (CHEMBL203) binding activities from ChEMBL — 26,322
  published measurement rows → 13,667 unique canonical compounds
  (frozen in `fixtures/`, checksum-gated; fetch pagination bug found and fixed
  along the way — see "What the study found in our own machinery").
- **Held out (the known future):** the seven documented successor drugs —
  gefitinib, erlotinib, lapatinib (1st-gen reversible); afatinib, dacomitinib,
  neratinib (2nd-gen covalent); osimertinib (3rd-gen covalent, mutant-selective).
  **All seven were verified present in the corpus** (e.g. gefitinib n=302
  measurements, afatinib n=146) before removal — the blinding removed real
  data, not empty space. Their published medians are used ONLY in scoring.
- **Surrogate:** Morgan-RF (seeded) trained on a blinded 70% split; the 30%
  test side is the universe the loop may touch — **the model never saw their
  values**.
- **Library:** 36 candidates stratified across the surrogate's predicted-
  potency range around the gate, measured ≥3x (stable truth), opaque IDs
  EG-01…36 with chemistry carried as provenance metadata.
- **Pre-registered gate:** IC50 ≤ 1 µM (HTS hit bar). Truth label: published
  median pIC50 ≥ 6.0. Dose ladder 1 nM – 10 µM × 3 replicates.
- **Lab:** `ReplayLab` (`replay-published`, `replay-v1`): the IC50 truth of
  every well is the compound's published median; the curve SHAPE around it
  and the well noise are a declared, seeded replay model. Unknown candidates
  raise — the adapter cannot invent a number.
- **Campaign A:** autonomy `act`, k-schedule (18, 12), every hypothesis
  declaring "reversible ATP-site competitive antagonist". The SafetyEngine
  screens the real molecules (toxicophore SMARTS, safety-rules-v1).
- **Campaign B (re-design loop):** candidates A's gate refused are
  re-proposed once with an honest DECLARED covalent mechanism
  ("Michael-acceptor warhead engaging the reactive cysteine"), which is the
  only downgrade path the medium-alert rule allows.

## Results (from `results.json`, reproducible offline)

### Campaign A — reversible-declared screen

| stage | count | note |
|---|---|---|
| selected for testing | 30 | 18 + 12 by surrogate-prior ranking |
| refused by Make (QC) | 6 | both synthesis attempts < spec — never reached Test |
| refused by Safety gate | 18 | acrylamide ×10, hydroquinone ×6, quinone ×6, vic-aryl-amine ×4 (compounds carry several) |
| measured | 6 | plate → Hill+bootstrap CI → verdict → orthogonal confirmation |
| **claims against published truth** | | **1 confirmed (true active), 5 refuted (all true inactives), 0 false claims, 0 wrongly-killed actives, 0 unexplained** |

### Campaign B — the refused warheads, honestly re-declared

All 6 re-proposed candidates passed the gate once the mechanism was declared
(intent-declared downgrades apply only to medium alerts; hard alerts would
have stayed refused) — and the machine then judged them:

- **4 confirmed** — published medians 6.53 / 8.35 / 9.00 / 8.75 pIC50: **every
  one a true active**, each with a recorded orthogonal agreement
- **2 explicitly abstained** — published medians 9.47 / 9.59 (sub-350 pM):
  their transitions sit BELOW the 1 nM ladder floor; the fit pins at the grid
  edge and the system now refuses to dress that as an IC50 — recorded as
  `left-censored … range statement, not an IC50`, verdict `inconclusive`.
  The two most potent compounds in the study are the two the loop honestly
  declined to number.

**Reviewer pass (deterministic independent audit):** 0 critical / 0 warnings
across both campaigns; 12 verdicts, 12 audited. Full hash-chained provenance
in `study.db` (209 records), verifiable with
`bn prove problem/cs04-hit2lead --db case-studies/04-prospective-hit2lead/study.db`.

### The prospective reveal — did it converge on the field's future?

- The **surrogate's own top-6-ranked (blinded) candidates were all
  Michael-acceptor / redox-active warhead chemistry** — the mechanism class
  the field ultimately picked in 2013–2016. The loop independently ranked the
  covalent class first, using only published data minus the drugs themselves;
  it could not test that chemistry under an honest "reversible" declaration,
  and the safety gate made that cost explicit and auditable.
- Strict Murcko-scaffold overlap with the seven drugs: **0**; nearest
  confirmed-neighbor Tanimoto 0.12–0.19, and the nearest neighbor of every
  drug was a **true active** in every case. Honest reading: the loop
  rediscovered the *mechanism class and potency bar*, not the exact series —
  which is what a WT-potency-only world can support.

## What this study found in our own machinery (all fixed, tested)

1. **ChEMBL adapter pagination bug:** the shared cursor logic re-sliced
   `page_meta.next` into a bogus cursor; an 80k fetch contained ~1.8k unique
   rows. Fixed (raw-next following + content dedup) — 26,322 real rows now;
  `bn fixtures verify` proves it byte-for-byte.
2. **Make's simulated QC had drifted from its own comment:** "≈30% of
   structures fail" was actually 66–77% under purity U[60,99.5] vs an 85
   gate — a stub was dominating a real-data study. Distribution recalibrated
   to the claim, and the campaign loop gained a **recorded re-synthesis
   attempt** (real labs re-run failed batches; each attempt is its own lot,
   its own provenance record).
3. **Left-censoring was a silent gap:** super-potent plateaus rounded the fit
   to `0.0` and fell through every verdict branch — hypotheses sat as
   `tested` forever. Now: labread flags `left_censored`, and the agent records
   an explicit `inconclusive` with the censoring as the stated reason
   (`tests/test_censoring.py`).
4. **Reviewer crash on honest abstentions:** `observed > gate` evaluated
   before the None-guard — any no-number verdict killed the campaign-end
   audit. Fixed, caught by this study running the real path.

## Limitations, stated plainly

- **Wild-type potency only.** Osimertinib's actual future was T790M
  selectivity and lapatinib's was HER2 — axes this target slice cannot see.
  This study scores the potency claim, not the clinical judgment.
- **Replay, not wet lab.** Published IC50s are truth; curve shape and wells
  are a declared synthetic replay around that truth (instrument
  `replay-published/replay-v1`). A real plate-reader pilot is S-T0.2.
- No date-splitting of the corpus: structure blinding, not time travel.
- 6 compounds died in simulated Make and never faced Test at all — honest
  funnel accounting, but a coverage cost the retry only partly heals.
- The stratified library deliberately spans chemotypes; scaffold-exact
  rediscovery was never the likely outcome and was not the claim.

## Reproduce

```sh
.venv/bin/python case-studies/04-prospective-hit2lead/run.py   # offline: restores fixtures, refetches only if absent
```

Inputs frozen under `fixtures/` (manifest checksums; `bn fixtures verify
case-studies/04-prospective-hit2lead`). Outputs regenerate deterministically:
`results.json` and `study.db` (provenance branches) are written per run and
not committed. Seeds fixed; no LLM call — fully offline and deterministic.
