# Frontier-Review Roadmap (TODO plan)

Source: critical review of BioNexus as a top-lab (DeepMind/Anthropic/Isomorphic)
reviewer would run it. Architecture survives scrutiny; **the statistics and the
epistemology of verdicts do not.** Work top-down — P0 first.

Status legend: `[ ]` open · `[~]` in progress · `[x]` done

## P0 — Uncertainty-aware verdicts (epistemic integrity)
- [x] Fit IC50 with a confidence interval — Hill grid fit + residual bootstrap
  (deterministic seed), `labread.fit_ic50_ci`; CI stored on compounds as
  `ic50_ci` and in verdict provenance as `observed_ci`
- [x] Verdict rule: `SuccessCriteria.classify(value, ci)` — CI straddling the
  threshold → `inconclusive`; wired in `verdict()` and `watch.handle`.
  [x] `_handle_confirmation` now prefers CI-overlap agreement (falls back to
  3x ratio when a CI is missing); rule used is recorded in provenance
- [x] CI shown in pipeline cards, diary verdict lines, instrument output
  blocks, wizard step 6 table; `dose_response_svg(ci=...)` draws the shaded
  95% band behind the curve
- [ ] Propagate replicate variance through to the fit (currently median-of-
  replicates hides spread) — `adapters/lab/simulator.py` + labread
- Done 2026-09-08: tests `test_success_criteria_ci_straddle_is_inconclusive`,
  `test_fit_ic50_ci_covers_true_value`; live campaign showed a CI-aware
  confirmation REFUTING a preliminary hit (the mechanism working). Remaining:
  rerun case-studies/02 to regenerate its verdict artifacts

## P0 — Small-n statistics
- [x] `benchmark.spearman_ci` / `bootstrap_ci` added; case-study 03 rows now
  carry `rf_spearman_ci95`. [ ] remaining: EF@10% CI + regenerate the
  results.json artifacts (needs network day)
- [x] `benchmark.benjamini_hochberg` available. [ ] remaining: apply across
  the 30-paper screen_papers output when regenerated
- [ ] Scaffold-split CV for the Morgan+RF baselines (leakage check)
- Verify: regenerated `results.json` files include CI columns

## P1 — Eval harness ("agentic science" as a measurable claim)
- [x] `python -m bionexus.cli eval` — offline task suite with ground truth:
  `hit-recovery` (calls vs seeded potency), `verdict-honesty` (bar placed on
  a compound's TRUE IC50 — abstention mandatory), `confirmation-coverage`
  (no CONFIRMED without recorded agreement). Writes evals/leaderboard.md +
  results.json. Harness caught 3 real bugs on first run (observed-max bias,
  per-run potency instability, scorer blind to abstentions).
- [ ] Make case-studies/01–03 the flagship benchmark suite, not a folder:
  versioned fixtures + leaderboard integration (leaderboard exists now)
- [ ] Strengthen the contamination probe: synthetic-variant test (perturb
  SMILES of held-out compounds; if model "recognizes" altered structures,
  the paper is memorized) — `case-studies/*/run.py`
- Verify: `make eval-suite` (new target) runs offline except LLM rows

## P1 — Mechanistic, falsifiable hypotheses
- [x] Hypothesis fields: `mechanism`, `refutation_condition`,
  `predicted_observables`, `citation` (PMID/DOI) — carried through
  propose/propose_portfolio/propose_families, provenance decisions, and
  artifact metadata; UI shows "⚙️ mechanism / ☠️ refuted if" on cards + diary
- [x] `explanatory_bonus` (cap 0.2): portfolio ties break toward
  mechanistic+cited hypotheses; reason recorded. Eval task
  `falsifiability-tiebreak` proves it (all-k-picks-must-be-falsifiable)
- [x] Hypothesis-agent prompt demands mechanism/refutation/citation —
  LIVE-validated 2026-09-09 (glm proxy): two real families (type-I ATP vs
  type-II DFG-out), causal mechanisms, proper refutation conditions, and a
  REAL citation (PMID 35377565) on one family with honest "—" on the other
  (never-invent clause held). Full loop: agent hypotheses -> lab -> CI-aware
  invalidated verdicts -> auto-confirmations.
- [ ] Templates: drop decorative "template:" rationale strings (empty beats
  decorative); wizard step 2 could collect mechanism/refutation too

## P2 — Adaptive experimentation (the result, not the feature)
- [x] `src/bionexus/adaptive.py` — grid posterior over log-IC50 under the
  Hill model; `next_dose()` maximizes posterior predictive spread (most
  informative well); median + 95% credible interval readout
- [x] Eval task `adaptive-dose-design`: 3-well adaptive vs 4-point fixed
  (labread) on 16 log-uniform compounds → wins 14/16, mean |log10 err|
  0.024 vs 0.090, CI coverage 15/16 at nominal 15.2. Measured, not claimed.
- [x] Wired into `autoloop.py`: `dose_design: "adaptive"` / `bn auto
  --dose-design adaptive` — screen well, then up to 2 Bayesian follow-up
  wells per compound with live posterior updates in the log; verdicts from
  posterior median + credible interval (CI-aware classify reused).
  Regression caught by eval: `validated` must stay non-terminal in the
  monitor loop (fixed mode awaits confirmation).
- [ ] Negative lesson recorded: giving the fixed baseline the SAME
  posterior estimator erases most of the advantage (0.038 vs 0.043) — the
  win is against the real pipeline (linear/Hill point fits), and the eval
  says so explicitly

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
