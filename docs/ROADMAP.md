# Frontier-Review Roadmap (TODO plan)

Source: critical review of BioNexus as a top-lab (DeepMind/Anthropic/Isomorphic)
reviewer would run it. Architecture survives scrutiny; **the statistics and the
epistemology of verdicts do not.** Work top-down — P0 first.

Status legend: `[ ]` open · `[~]` in progress · `[x]` done

## P0 — Uncertainty-aware verdicts (epistemic integrity)
- [ ] Fit IC50 with a confidence interval (4-param Hill + bootstrap or delta
  method) — `src/bionexus/labread.py`, `src/bionexus/plots.py`
- [ ] Verdict rule: if the 95% CI straddles the success-criteria threshold →
  `inconclusive`, not validated/invalidated — `src/bionexus/core/hypothesis.py`
  (`SuccessCriteria.met`, `verdict`), `src/bionexus/watch.py`
  (`_handle_confirmation` agreement check should use CIs too)
- [ ] Show CI everywhere a number appears: pipeline cards (`webview.py`),
  diary entries (`diary.py`), wizard step 6 (`Overview.py`)
- [ ] Propagate replicate variance through to the fit (currently median-of-
  replicates hides spread) — `adapters/lab/simulator.py` + labread
- Verify: new tests in `tests/test_core.py` / `test_adapters_ext.py`; rerun
  `case-studies/02-az3246-hpk1` and confirm verdicts state CIs

## P0 — Small-n statistics
- [ ] Bootstrap CIs on Spearman/EF@10% in case-study tables
  (`case-studies/*/run.py`, `bionexus/benchmark.py`)
- [ ] Multiple-comparison correction across the 30-paper screen (BH/FDR)
- [ ] Scaffold-split CV for the Morgan+RF baselines (leakage check)
- Verify: regenerated `results.json` files include CI columns

## P1 — Eval harness ("agentic science" as a measurable claim)
- [ ] Fixed task suite with ground truth (BixBench/LAB-Bench style):
  blind reproduction tasks + contamination probes, one command → score
- [ ] Make case-studies/01–03 the flagship benchmark suite, not a folder:
  leaderboard.md, versioned fixtures, seeded simulator ground truth
  (pin `SimulatorLab` seed + version tag so numbers repro across releases)
- [ ] Strengthen the contamination probe: synthetic-variant test (perturb
  SMILES of held-out compounds; if model "recognizes" altered structures,
  the paper is memorized) — `case-studies/*/run.py`
- Verify: `make eval-suite` (new target) runs offline except LLM rows

## P1 — Mechanistic, falsifiable hypotheses
- [ ] Required fields on Hypothesis: mechanism, predicted_observables,
  refutation_condition — `core/hypothesis.py` + contracts; migrate existing
  templates (drop "template:" rationale strings — empty beats decorative)
- [ ] Portfolio scoring should weight explanatory power, not just threshold
  pass — `core/hypothesis.py` `select_portfolio`
- [ ] Hypothesis agent prompt: demand mechanism + citation (PubMed adapter
  exists at `adapters/databases/pubmed.py`); record citation in provenance
  artifact metadata

## P2 — Adaptive experimentation (the result, not the feature)
- [ ] Bayesian dose-series design: choose next concentrations from posterior
  over IC50; target same accuracy in ~half the wells — new
  `src/bionexus/adaptive.py` + use in `autoloop.py`
- [ ] Demo: fixed 4-point vs adaptive on the simulator, report wells saved

## P2 — Learn from refutations (close the flywheel)
- [ ] Feed invalidated hypotheses + their evidence back into scoring/
  proposal (the `c.flywheel.*` tool names exist; nothing implements them)
- [ ] Negative-result summary per program: what we ruled out, with evidence

## P3 — Honesty/ops polish
- [ ] Remove agent personas from UI + docs (keep toolsets, drop characters)
  — `src/bionexus/agents.py`, `Overview.py`, README
- [ ] ELN export (Benchling/SISSYO-shaped CSV/JSON) from provenance branch
- [ ] Daily Merkle root of the provenance store published to a transparency
  log (tamper-evidence others can verify)
- [ ] Simulator version tag in every provenance record that used it

## Do NOT (decided)
- Multi-user/auth on the workbench — local-first is the point
- Replacing Streamlit — graduate to FastAPI+React only if multi-user arrives
- Making `bn serve` the primary surface — it's the headless fallback

## Session bootstrap
```sh
make test-unit                      # 31 tests green as of this writing
streamlit run Overview.py           # workbench (:8501)
git log --oneline -10               # recent context
```
Key files: `Overview.py` (router UI), `src/bionexus/webview.py` (shared
rendering), `core/hypothesis.py` (verdict logic), `watch.py` (agent loop),
`autoloop.py` (campaign flow), `diary.py` (narrative), `program.py` (TPP),
`adapters/databases/chembl_gates.py` (evidence-based gates).
