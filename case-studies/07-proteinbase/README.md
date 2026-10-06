# Case Study 07 — Proteinbase: wet-lab binder data, third modality, zero GPU

**The question.** Small molecules were reproduced against a lab's own calls
(CS05/06). Adaptyv Bio's [Proteinbase](https://proteinbase.com) publishes
every tested protein design — binders AND misses — under identical
protocols (ODC-By). Can BioNexus's machinery (1) reproduce competition-level
measurements on this third modality, and (2) do anything USEFUL there —
specifically the question behind the competition-entry idea: *could our
selection machinery pick better test-slots than computed confidence does?*

## Setup
Source: `proteinbase_all_data_28_01_2026.csv` (40 MB, 5,253 proteins,
sha256 `51c467ed…` in `fixtures/MANIFEST.json`; kept in `.data/`, never
in git). Derived fixtures (proteins + (protein×target) experimental pairs,
gzipped, checksummed): 5,253 proteins, 2,630 pair rows. All CPU, offline.
Attribution: "This work used Proteinbase by Adaptyv Bio under ODC-By license".

## What reproduced (facts, `run.py` -> `results.json`)

| check | ours | published |
|---|---|---|
| Nipah-G hit rate | 10.0% (103/1,030) | 9.3% (111/1,200) ✓ |
| EGFR hit rate (both comps pooled) | 15.7% | 14.0% (comp 2) / 2.5% (comp 1) ✓ |
| expression-failure proteins | 276/5,253 = 5.3% all-protein; measurement-level 11.6% | 1,093/9,414 = 11.6% ✓ |
| method spread (Nipah) | rfdiffusion 17.6% · unlabeled 13.8% · bindcraft 7.4% · boltzgen 1.9% · dsm 0% | same ranking class ✓ |

## What FAILED to work — the two findings that matter

**1. Selection replay: computed confidence cannot pick test slots — it
picks them WORSE.** Top-quartile-by-signal vs pool hit rate:

| target | signal | baseline | top quartile | lift |
|---|---|---|---|---|
| Nipah | pLDDT | 10.1% | 7.4% | **−2.6pp** |
| Nipah | ProteinMPNN conf | 10.1% | 2.4% | **−7.7pp** |
| EGFR | pLDDT | 15.7% | 10.2% | **−5.5pp** |
| EGFR | ProteinMPNN conf | 15.7% | 15.0% | −0.7pp |

Four-for-four negative. Global fold confidence is not interface quality —
selecting on it spends scarce test slots *worse than random*. Any
competition entry must therefore NOT trust these scores as its ranker;
that is BindCraft/RFdiffusion's internal interface metrics' job, and an
open question, not a solved one. (Honest caveat: retrospective replay on
already-tested pools; the 405-slot Nipah allocation mixed comp ranks,
expert review and community vote.)

**2. Applicability-domain: calibration was the first-order problem — now
quantile floors are in (`bionexus.ad`, `floor="auto"`).** The fixed 0.5
Tanimoto floor flags 96.6% of cross-target (EGFR) sequences as
extrapolation… and would flag most of the domain's own members under a
leave-one-out test: designed binders against ONE target share only
~0.05–0.10 aa-3-gram Jaccard with their nearest sibling, so their LOO-NN
distribution lives far below 0.5. With the data-derived floor (p25 of the
domain's own LOO-NN distribution → 0.105), the false-alarm rate is
*declared* (25%, by construction) and cross-target flagging is 54% —
directionally right, about 2× the control. Remaining weakness is the
representation, not the constant: k-mer Jaccard is a coarse protein
similarity; a larger k or embedding-space domain (ESM2-class) is the next
ticket. This is CS06's lesson repeating: mechanisms transfer across
modalities only when their calibration is data-derived, not inherited.

## Verdict for the competition question
CS07 strengthens the reproduction claim (third modality, published numbers
reproduced from raw rows, offline, deterministic) and weakens the
"we could win with better selection" hypothesis as currently buildable:
the easy rankers are worse-than-random, and the domain tool needs its
protein-calibration ticket first. A future entry must ride a real
structure-based design/screening model (BindCraft-class) — the loop's value
here is gates + provenance + honest reporting, not slot-picking magic.

## Limitations
- Methods unlabeled on 2,212 proteins; "unlabeled" spread mixes entries
  and controls.
- bound/strength/kd are experimental-only views; computational columns come
  from the DB's own predictors, not ours.
- pair semantics = (protein, target); proteins measured against multiple
  targets appear once per pair.
