# Case Study 03 — Multi-Paper Flow Validation

## Purpose

Case Study 03 evaluates whether BioNexus can guide a bounded scientific
experiment cycle across several recent published datasets. The primary object
of evaluation is the **flow**, not the predictive quality of a particular
model:

```text
problem → hypotheses → experiment design → safety gate → test
         → observed result → assessment → iteration → final decision
```

The published measurements are exposed through a `PaperLab` adapter. This lets
the flow use real experimental values while retaining a deterministic,
replayable test environment. The model or search strategy chooses which
compounds to test; BioNexus is responsible for the lifecycle, controls,
provenance, and resource boundaries.

## Papers

The study uses recent 2025 ChEMBL-deposited papers selected by an automatic
screen for sufficient compound count and an available target data pool:

| ChEMBL document | Paper context | Compounds |
|---|---|---:|
| [CHEMBL6087407](https://www.ebi.ac.uk/chembl/document_report_card/CHEMBL6087407/) | 4-(4-methyl-1,2,4-triazolyl)piperidine derivatives | 67 |
| [CHEMBL6087417](https://www.ebi.ac.uk/chembl/document_report_card/CHEMBL6087417/) | 5-substituted thiazolyl urea derivatives | 53 |
| [CHEMBL6078657](https://www.ebi.ac.uk/chembl/document_report_card/CHEMBL6078657/) | Thiazolidinedione-based ergosterol-peroxide derivatives | 54 |

The screening utility is `screen_papers.py`. It is intentionally separate from
the flow runner so paper selection can be reviewed before execution.

## Method

For each paper and each strategy (`random` and `rf`):

1. Create and provenance-record a problem statement with an experiment budget.
2. Propose a hypothesis for each compound before testing it.
3. Select a bounded batch of compounds.
4. Submit a protocol through `LabGateway` and `SafetyEngine`.
5. Obtain the corresponding published value through `PaperLab`.
6. Record a validated or invalidated judgment against the declared activity
   threshold.
7. Repeat until the experiment budget is exhausted or the paper is covered.
8. Verify the provenance chain and report recovery of the paper's active set.

Model metrics are retained only as secondary context. They are not the claim
of this study.

## Results

Every completed campaign passed the **flow-integrity** checks: required
problem, hypothesis, lab-run, and judgment events were present; the hash chain
was intact; and no campaign exceeded the 30-experiment budget.

| Paper | Strategy | Tested | True actives | Active-set recall | Flow integrity |
|---|---|---:|---:|---:|---|
| CHEMBL6087407 | random | 30/67 | 5 | 0.80 | **PASS** |
| CHEMBL6087407 | RF | 30/67 | 5 | 0.40 | **PASS** |
| CHEMBL6087417 | random | 30/54 | 11 | 0.636 | **PASS** |
| CHEMBL6087417 | RF | 30/54 | 11 | 0.182 | **PASS** |
| CHEMBL6078657 | random | 30/54 | 0 | 1.00* | **PASS** |
| CHEMBL6078657 | RF | 30/54 | 0 | 1.00* | **PASS** |

`*` There were no compounds meeting the selected activity threshold in this
paper, so recall is vacuously 1.0 and is not evidence of search quality.

The differing recall values are secondary: the strategy can improve or degrade
compound selection, but **the lifecycle remains valid independently of the
strategy**. This is the property BioNexus is intended to provide.

### Statistical honesty pass (2026-09-10, frozen fixtures)

Re-run with bootstrap CIs, hypergeometric enrichment p-values, Benjamini–Hochberg
FDR across papers, and a scaffold-leakage control (retrain with every training
row sharing a Murcko scaffold with the paper removed):

| Paper | ρ (full) | ρ (scaffold-clean) | EF@10% | EF 95% CI | p | BH sig |
|---|---|---|---|---|---|---|
| CHEMBL6087414 | −0.193 | −0.189 (0 overlap) | n/a (no actives) | — | — | — |
| CHEMBL6087416 | +0.175 | +0.175 (0 overlap) | 1.09× | [1.0, 1.23] | 0.77 | no |
| CHEMBL6087417 | −0.554 | −0.554 (0 overlap) | 0.0× | [0.0, 0.0] | 1.00 | no |
| CHEMBL6087407 | +0.662 | **+0.696** (299 removed) | 2.23× | **[0.0, 6.98]** | 0.38 | no |

Three findings, stated plainly:

1. **No enrichment claim survives correction.** The best-looking EF (2.23×)
   has a bootstrap CI spanning 0.0–6.98 — at n=67 compounds the point estimate
   was noise wearing a conclusion's clothes. The flow-integrity claim stands;
   an EF-based "the model finds actives" claim would not.
2. **Scaffold leakage is ~absent** — these 2025 papers genuinely introduce
   novel scaffolds; removing overlapping training rows changes ρ by ≤0.03
   (and *improves* CHEMBL6087407, so its +0.66 was not scaffold memory).
3. Negative ρ on two papers is reported as negative, not re-rolled.

## Hypothesis reproduction status

The next pass uses `--llm` to repeat the Case Study 02 test for each paper:
the agent sees structures and the problem statement, but not measurements or
the reference conclusion. Its proposed core is compared with the
independently reviewed markers in [`reference_manifest.json`](reference_manifest.json),
and the agent's compound-selection path is run through the same `PaperLab`
flow. The API endpoint used for the agent pass was rate-limited during this
run (`HTTP 429`), so no hypothesis-match result is reported here. This is an
explicit pending experiment, not a failed or inferred result.

## What this demonstrates

- A published-value adapter can be substituted for a physical lab while
  preserving the same protocol and result contracts.
- Hypotheses are explicitly proposed before their corresponding tests.
- Real measurements become evidence for recorded judgments, not untracked
  numbers in a model evaluation script.
- Resource limits and safety gates remain active regardless of strategy.
- The flow can complete with all hypotheses invalidated; failure is a valid
  scientific outcome.

## What this does not demonstrate

- It does not prove that BioNexus discovers new drugs.
- It does not establish a state-of-the-art model result.
- `PaperLab` validates orchestration against published evidence; it is not a
  substitute for a physical laboratory.
- This runner simulates device completion through the adapter rather than
  exercising `DeviceMonitor`. The separate device-awareness demo covers the
  `device → event → noticed → analyzed` path; combining both is next.

## Reproduce

From this directory, after the ChEMBL cache has been populated:

```sh
python flow_check.py --docs CHEMBL6087407,CHEMBL6087417,CHEMBL6078657
```

The runner writes `flow_results.json` and uses no LLM. Add `--llm` only when
you specifically want to compare an agent's compound-selection strategy and
hypothesis against the reference manifest:

```sh
python flow_check.py --llm --docs CHEMBL6087407,CHEMBL6087417,CHEMBL6078657
```
