# Frontier-Review Roadmap (TODO plan)

Source: critical review (note: T# here = priority TIER; P# in docs/PLAN.md = design principle — different schemes) of BioNexus as a top-lab (DeepMind/Anthropic/Isomorphic)
reviewer would run it. Architecture survives scrutiny; **the statistics and the
epistemology of verdicts do not.** Work top-down — T0 first.

Status legend: `[ ]` open · `[~]` in progress · `[x]` done

## T0 — Uncertainty-aware verdicts (epistemic integrity)
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
- [x] Replicate variance propagates: exports write true replicate wells
  (seeded noise per well); the residual bootstrap widens CIs accordingly
- Done 2026-09-08: tests `test_success_criteria_ci_straddle_is_inconclusive`,
  `test_fit_ic50_ci_covers_true_value`; live campaign showed a CI-aware
  confirmation REFUTING a preliminary hit (the mechanism working). Remaining:
  rerun case-studies/02 to regenerate its verdict artifacts

## T0 — Small-n statistics
- [x] `benchmark.spearman_ci` / `bootstrap_ci` added; case-study 03 rows now
  carry `rf_spearman_ci95`; EF@10% bootstrap CIs + hypergeometric p +
  BH-across-papers added and CS03 artifacts REGENERATED from frozen
  fixtures (2026-09-10): no enrichment survives correction; scaffold
  leakage ~absent. See case-studies/03 README "Statistical honesty pass"
- [x] `benchmark.benjamini_hochberg` applied across the CS04 enrichment tests
- [x] Scaffold-leakage checks: CS02 + CS03 retrain Morgan+RF with every
  training row sharing a Murcko scaffold with the held-out paper removed,
  reporting the spearman gap (= scaffold memory). Runs on network day
- Verify: regenerated `results.json` files include CI columns

## T1 — Eval harness ("agentic science" as a measurable claim)
- [x] `python -m bionexus.cli eval` — offline task suite with ground truth:
  `hit-recovery` (calls vs seeded potency), `verdict-honesty` (bar placed on
  a compound's TRUE IC50 — abstention mandatory), `confirmation-coverage`
  (no CONFIRMED without recorded agreement). Writes evals/leaderboard.md +
  results.json. Harness caught 3 real bugs on first run (observed-max bias,
  per-run potency instability, scorer blind to abstentions).
- [x] Case-study data frozen: gzip checksummed fixtures + manifest per study,
  `materialize()` restores caches byte-identically, `bn fixtures verify` in
  CI (`fixtures` job). Pagination bug (offset-`next` mangled into a bogus
  cursor -> duplicate training rows) fixed in CS02/CS03 during freezing.
  [ ] CS02 training-pool freeze INCOMPLETE — EBI 500s on offset pages;
  re-warm + re-freeze when it recovers, then re-run CS02 artifacts (its
  published numbers were computed on the duplicate-inflated training set).
- [x] CS03 `--llm` sweep COMPLETED 2026-09-10 (reuse fast-path + glm-4.5-air):
  blind chemotype ID 4/4, variant probe flagged 1 leakage-suspect that the
  self-report missed, agent-vs-RF mixed rankings reported honestly.
  [ ] follow-up: chemist-judged core-match verdict (substring matcher is
  brittle: "benzimidazole" fails a "benzene" contains-test)
- [x] `src/bionexus/probes.py` — never-published single-token variants of
  held-out compounds are asked about blind; mapping a nonexistent near-twin
  to the paper = memorization. Wired into CS02 (provenance-recorded) and
  CS03 (`contamination_variants` row); stub-tested offline. [ ] results
  land when studies are re-run (network day)
- Verify: `make eval-suite` (new target) runs offline except LLM rows

## T1 — Mechanistic, falsifiable hypotheses
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
- [x] Decorative "template:"/"custom" rationales dropped (empty beats
  decorative); wizard step 2 gained the mechanism/refutation/citation panel
  that flows into provenance and agent handoff

## T2 — Adaptive experimentation (the result, not the feature)
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

## Follow-up: determinism of case-study models
- [ ] MorganFingerprintRF (sklearn) is unseeded — ρ drifted −0.200 → −0.193
      across two runs today. Pass `random_state` derived from the study seed.

## Follow-up: agent path from the CLI
- [x] `hypothesis_source: "agent"` in a `bn auto` config now auto-wires the
      Anthropic provider from env (live-validated: agent proposed → lab →
      CI-aware confirmation end to end from the CLI).

## T2 — Learn from refutations (close the flywheel)
- [x] `src/bionexus/flywheel.py` — every verdict submitted (tracker
  `on_verdict` hook, wired in `run_campaign`); family priors [0.5,1.5]
  discount failed mechanistic families in portfolio scoring; agent prompt
  gets an "ALREADY RULED OUT" block (don't re-propose dead mechanisms).
  Eval task `flywheel-memory`: a family invalidated in campaign 1 gets
  ZERO lab slots in campaign 2.
- [x] Negative-result summary surfaced in the workbench ("🚫 Ruled out")

## T3 — Honesty/ops polish
- [x] Personas removed from README flow table + UI (layers named by
  function); `agents.py` retained as toolset config for MCP consumers
- [x] `bn prove <branch> --eln out.csv` — flat ELN CSV (18 cols: verdict,
  observed + CI, run, instrument+version, record hash) + JSON sidecar
  (`bionexus/eln.py`)
- [x] `bn anchor` — Merkle root over all record hashes (`.data/anchors.json`
  history); `--publish-cmd` pipes the anchor JSON to any transparency channel
  (gist/repo/RFC3161); `bn anchor --verify` recomputes and compares.
  Tamper test proves appended records break verification
- [x] `instrument_version` on every lab_run decision (SimulatorLab = sim-v1)

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


## Trust Initiative — safety · reliability · mechanistic interpretability
Positioning bet: trustworthiness as architecture, not marketing. Priority order:

### Trust-T0 — credibility gates
- [x] **Citation verification** (`src/bionexus/citations.py`) — PMID/DOI
  resolved against PubMed E-utilities with a local cache; statuses
  verified/invalid/check-failed (offline ≠ fake). Enforced: verified +0.05,
  invalid −0.10 (below a bare hypothesis), unverified 0 — so a fabricated
  reference ranks worse than no reference. Wired into the agent generation
  path (batch check + warning), the wizard (toast + provenance decision),
  artifact metadata, pipeline cards (📚✓ / 📚⚠️ FABRICATED) and diary lines.
  Live-validated: PMID 35377565 → verified "2025 · J Med Chem"; fake DOI →
  invalid; k=1 portfolio picked the verified-citation hypothesis.
  [ ] next step: verify the CITED WORK actually supports the claim (title/
  abstract relevance check), not just existence
- [x] **Molecular safety gate** (`adapters/bio/tox_alerts.py`): 18 curated
  SMARTS toxicophore alerts in the SafetyEngine (hard: aromatic nitro,
  aziridine, mustard, azide, quinone…; medium: Michael acceptors, epoxides,
  acrylamides — downgraded ONLY when the hypothesis mechanism declares
  covalent intent). DURC screen at TWO levels: campaign refusal if the
  problem names a select agent (recorded, raises), per-protocol text rule.
  No-RDKit installs report "unverified" honestly instead of pretending.
  Verified live: nitrobenzene refused with machine-readable reason, declared
  warhead passed, aspirin clean; 57 tests.

### Trust-T1 — reproducibility & honesty under fault
- [x] `bn reproduce <branch>` — the execution ENVIRONMENT (lab adapter,
  version, seed, concentrations, k, dose design) is now recorded in
  problem_defined; reproduce replays it and diffs verdicts. Live: 2/2
  verdicts identical from seed 42. Legacy branches with no environment
  report `not-reproducible` honestly. Live labs: recording playback, not
  simulated replay. [ ] model/prompt version pinning for LLM paths
- [x] Fault suite (`tests/test_faults.py`): junk CSVs return error summaries
  with hypotheses untouched (agent.handle is now exception-safe); garbage
  SMILES are inert at the gate; empty/partial plates never invent fits
- [x] **Input trust boundary**: `labread.sanitize_label` (control chars
  stripped, capped) on every instrument-file label; proven by test that an
  injection-shaped sample name is inert dict-key data, never policy
- [x] Model-variance reporting: `reliability.verdict_spread` — same ground
  truth (one lab seed), N measurement-noise draws (`CampaignConfig.
  noise_variant`); flips = borderline evidence. Eval task
  `verdict-stability` (7-task suite, mean 0.970). [ ] surface spread on
  the pipeline card in the UI (currently eval-level only)

### Trust-T2 — mechanistic interpretability
- [ ] **Scalable safety (tiered)**: alerts/DURC lists move from code to
  versioned JSON data (ingest Benigni/Bosa + Toxtree/OpenAlerts rulebooks);
  AI tox reviewer joins as ADVISORY tier with the **tighten-only
  invariant** — model output may add flags or demand review, never clear a
  deterministic refusal; human adjudications feed flywheel → candidate
  rules (humans promote, not the model)
- [ ] Attribution panel per prediction: Morgan-RF → top contributing fingerprint
  features; CharRidge → top n-grams; rendered beside verdicts ("why").
- [ ] Retrieval traces in provenance: which flywheel negatives, skill blocks,
  and ChEMBL context entered each generation prompt (currently only sizes).
