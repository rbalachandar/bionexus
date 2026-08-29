# Domain Review — BioNexus Flow vs. Real Drug Discovery

Thorough comparison of the framework/campaign flow against the actual drug
discovery & development cycle, with gaps and the fixes applied.

## The real cycle (small-molecule, abbreviated)

| Phase | What actually happens | Go/No-Go criteria |
|---|---|---|
| 0. Target ID | Disease association (genetics, literature, omics), target validation (is the target causal?), druggability assessment (pocket, family tractability) | Genetic validation strength, safety liability of target |
| 1. Hit discovery | HTS / DEL / virtual screening / structure-based design → raw hits | Hit rate, tractable chemistry |
| 2. Hit validation | Confirm activity (resupply/resynthesis), **counterscreens** (assay interference, PAINS/aggregators), **dose–response** (IC50/Ki, Hill slope), orthogonal assay, replicates (n≥3) with QC (Z' factor) | Confirmed, non-artifact, dose-dependent potency |
| 3. Hit-to-lead | **DMTA cycles** (Design-Make-Test-Analyze): SAR exploration, multiparameter optimization | Potency + early ADME improving round-over-round |
| 4. Lead optimization | MPO across potency, **selectivity** (off-target panel), ADME/DMPK (solubility, permeability, microsomal stability, CYP inhibition), physchem (Lipinski/Veber), **hERG/Ames** early tox; kill criteria drop series | Predefined MPO thresholds, no series-level liability |
| 5. Preclinical | GLP tox, safety pharm (NOAEL), formulation, PK/PD, in vivo efficacy | NOAEL ≥ efficacious exposure, IND package |
| 6. Clinical | Ph I safety/PK → Ph II PoC/dosing → Ph III confirmatory → MAA/NDA | futility/efficacy boundaries per phase |
| Throughout | Hypothesis records, ELN, decision gates, reps & backups | — |

## Review of what BioNexus had — and what was wrong

| Area | Before | Problem | Fix |
|---|---|---|---|
| Target ID | dossier only | No target *validation* or druggability step | `validate_target()`: evidence scoring + druggability gate |
| Hit gen → Lead opt | jumped straight to optimization | **No hit-validation stage** — real campaigns never optimize unconfirmed hits | Stage 2.5: counterscreen + dose–response + replicates |
| Assays | single-well measurement | Real potency = dose–response curve (IC50), single points are meaningless; no assay-interference control | Simulator supports concentrations → Hill curve → IC50; `counterscreen` assay flags interferers |
| Replicates | n=1 | Real assays run n≥3 with controls | `replicates` param; median reported, QC flags on spread |
| Lead-opt scoring | naive composite of raw assay values | Real optimization is **MPO** with kill criteria and selectivity, not a raw average | `mpo_score()`: potency (IC50), selectivity (panel spread), ADME, physchem; per-round **kill list** |
| Preclinical | one tox stub | Real preclinical = tox panel (hERG, Ames, microsomal stability) + DMPK, each a kill criterion | `tox_panel()` per-candidate, failures recorded, campaign halts on lead failure |
| Trial design | single "phase 1" line | Real dev is Ph I/II/III with go/no-go | three-phase plan with per-phase criteria + futility check |
| Hypotheses | lifecycle existed but predictions were arbitrary | Predictions must carry **uncertainty** and be tracked per candidate/assay | predictions come from the in-silico profile with predicted-vs-measured recorded (unchanged lifecycle, better inputs) |
| Portfolio | no backups | Real campaigns carry a lead + backups | campaign tracks ranked backups through the same gates |

## What the platform deliberately does NOT model (yet)

- Make step of DMTA (synthesis feasibility/retrosynthesis) — needs a cheminformatics adapter
- In vivo PK/PD and GLP tox — simulator-level only; real data needs partner labs
- Biomarker strategy, IP, formulation
- Human-in-the-loop is scripted — real deployments wire the same gates to reviewers

## Verdict

After the fixes, the simulated flow matches the real cycle *structurally*:
every real phase has a corresponding stage, every stage has go/no-go criteria
and recorded decisions, and every quantitative claim (potency, tox) is
hypothesis-driven, tested, and evidence-recorded. Remaining gaps are data/model
depth, not flow structure.
