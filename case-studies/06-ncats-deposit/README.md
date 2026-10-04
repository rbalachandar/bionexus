# Case Study 06 — The Deposit Pilot (a modern qHTS, and a negative result)

**Why.** CS05 proved the paper-pilot pattern on a 2013 MLPCN deposit. CS06
takes the NEWER dialect: NCATS (MLPCN's successor) deposited AID 2061307
on **2025-09-13** — post-training-cutoff, 2,427 retested compounds against
**ALDH3A1**, with their own AI-fit answer columns (Phenotype / GAC50 /
Fit_LogAC50 / ACTIVE-INACTIVE-INCONCLUSIVE). The claim under test is the
depositor's judgment; we never wrote it, never tuned to it.

## Registered protocol (fixed before scoring)

- gate: IC50 ≤ 1.0 µM (confirmatory probe bar)
- blind curve QC: ≥6 measured doses; concentration-dependence
  (Spearman trend ≥ 0.5); fit not pinned at the grid floor; in-sample 50%
  crossing — or, when every measured dose already passes 50%, a RANGE
  claim (IC50 ≤ lowest dose) only if that dose is below the gate
- CI veto: `SuccessCriteria.classify` — straddling ⇒ abstain
- answer keys (OUTCOME, Fit_*, Potency) read ONLY after verdicts lock
- engine: `bionexus.labread` native PubChem parser, dialect B
  (doses embedded in header names, %Activity inverted to the effect
  scale, flip DISCLOSED)

## Results — reproduction FAILED, informatively

`results.json`, run 2026-10-04, 81 s for all 2,427 curves.

| NCATS' call → | n | ours Active | ours Inactive | ours Abstain |
|---|---|---|---|---|
| Active | 541 | 502 | 0 | 39 |
| Inactive | 997 | **216** | 0 | 781 |
| Inconclusive | 889 | **639** | 0 | 250 |

- Potency correlation (where both fit): **Spearman ρ = 0.107** (n=1354) —
  vs CS05-style expectations, essentially none.
- We abstain 1,070; NCATS' own abstention (Inconclusive) is 889; only 23%
  of our abstentions fall in their set.
- We could not certify a single Inactive.

## Why it failed — the finding

NCATS reassay tables are **internally self-normalized**: "%Activity" is
relative to the FIRST MEASURED dose of that plate/column (and to fit
plateaus), not to an external DMSO/bottom-reference like Jacobs'
"%inhibition". Raw activity ≈ −8 at 1.5 nM for a compound whose own fit
says GAC50 = 0.32 µM is only consistent under self-normalization — the
scale's zero is the compound's own baseline, invisible to a fixed-50%-
crossing rule. Three consequences, all visible in the crosstab:

1. Their "Inactive" rows include full-plate autofluorescence curves
   (compound emits at resorufin wavelengths: apparent "inhibition" with a
   weak upward drift). Our trend rule catches most (781/997 abstained)
   but 216 slip past 0.5 as pseudo-monotone fluorescence rises — their AI
   rejects them via 4-param curve CLASSES (shape taxonomy), not
   thresholds.
2. Their Inconclusive is mostly "curve fitted but plateau unproven" —
   unresolvable from outside their normalization; 639 of them look
   fully-inhibiting in our fixed-frame view.
3. Their Active we mostly confirm (502/541) — the reproducible subset is
   exactly the one whose self-normalization is near the external frame.

**Epistemic verdict: a fixed-reference 50%-crossing rule does NOT port to
internally-normalized qHTS dialects. The deposit pilot found the real
thing a pilot is for — data friction that no amount of in-house simulation
shows.** We did not tune the rule toward their key after seeing the map
(the crosstab above IS the registered result); the CS04 "adaptive-dose
negative" precedent applies: the harness of honesty must also punish
our own optimism about portability.

## What CS06 discovered along the way (all fixed, tested)

- **Parser dialects** now two: meta-row doses (Jacobs) and header-embedded
  doses (NCATS), scale polarity by column family with **refusal** on
  ambiguous/mixed polarity (engine tests: `tests/test_labread_pubchem.py`,
  incl. sparse curves and anonymous-column refusal).
- **Degenerate-fit trap**: a 2-param Hill with KNOWN max "fits" a flat
  line at the grid floor → first version of our rules called 2,421/2,427
  actives. Caught immediately by the absurd crosstab — the pilot's own
  immune system. Registered QC (trend + crossing + range discipline) is
  the fix; the flat-ceiling mode is named in the rules.
- The Jacobs-side regression check ran **bit-identical** after parser v2.

## Next (not in this study)

Normalization-aware dialect registry: detect the reference frame from
plateau/first-dose structure and disclose it; per-dialect QC with curve-
class shape tests instead of a fixed 50% line. That is engine work with
its own tests — not more threshold tuning against this deposit.

## Status

**Concluded — negative result, fully reported.** Fixtures checksum-frozen
(`bn fixtures verify`), protocol pre-registered, crosstab published as
the finding.

**Encoded since (Oct 2026):** `bionexus.labread` now fingerprints the
normalization frame of every deposited percent table and REFUSES
dose-response assertions on frames not externally validated —
self-normalized qHTS deposits (this study's dialect) are refused by
default with the regime named in the output; `assert_regimes=False` is a
declared research bypass (this study's own `run.py` uses it, as the
published negative result predates the gate). The next unshipped piece is
curve-CLASS shape QC for re-admitting such tables honestly.
