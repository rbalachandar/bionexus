# Bayesian Experiment Selection (acquisition policies) — Plan & Status

**Status:** Implemented incl. the workbench panel (Oct 2026, this doc shipped
with the code): `bo-ei` selectable in config/CLI, graded by the
`acquisition-policy` eval task, "why this plate" rendered on the Experiment
page. Program-form picker + CS04 real-data replay remain (see below).  
**One-liner:** turn "which experiments run" from a heuristic ordering into a
deterministic, applicability-domain-gated acquisition policy — and PROVE it
beats the interim champion ("gates + randomize") in a graded eval task, not
in prose.

## Decision

`CampaignConfig.acquisition` selects the batch policy:

| value | behaviour |
|---|---|
| `""` (default) | today's behaviour: score/flywheel round 1, policy slot round 2+. Nothing changes for existing users. |
| `bo-ei` | expected-improvement acquisition over candidate posteriors, AD-gated, batch = `k` with the family-diversity cap. Every pick/refusal is a provenance record. |

Non-negotiables (the repo's own evidence):

- **AD gate cuts BOTH ways.** A candidate stamped extrapolation is NEVER
  picked by `bo-ei` — exploration outside the model's domain is exactly the
  infinite-exploration failure the applicability-domain module exists to
  refuse. Refusals are recorded with the reason.
- **No fabricated uncertainty.** EI needs a posterior sd. It comes from the
  hypothesis (`predicted_sd` in the spec/metadata) or an explicit surrogate
  declaration — never invented by the policy. A mean without sd is flagged
  `point-posterior` in the reason (exploit-only, honest label).
- **The gate layer is unchanged.** Safety, budget, approval, and
  diversity caps still veto every acquisition pick; the policy recommends,
  the harness decides.
- **The claim is the eval, not the feature.** `acquisition-policy` must beat
  seeded gates+randomize on the same pools or the leaderboard says so.
  CS07/CS08 taught us that plausible rankers can lose to random.

## Modules

- `src/bionexus/acquisition.py` — pure, deterministic policy.
  `Posterior` (candidate, mean, sd?, family, in_domain, source),
  `expected_improvement(mean, sd, target, direction)` closed-form on the
  log scale for min-direction metrics (IC50-style), `select_batch(...)` →
  `Selection` (picks with acquisition value + reason, refusals with reason),
  `randomize_batch(...)` — the baseline.
- `autoloop.py` — wiring: posteriors built from the portfolio
  (`predicted_value` + `predicted_sd` metadata + AD stamp), `round_start`
  provenance gains the `acquisition_selection` decision, `say` prints
  picks/refusals (the CLI dry-run is this in `observe` autonomy).
- `evals/tasks.py` — `acquisition-policy` task (pure-policy simulation,
  hermetic and fast, no lab run needed): same 24-compound seeded pools as
  `method-recall`, deterministic surrogate + observation models; bo-ei vs
  gates-randomize, budget-matched, 2 rounds; scores hits-per-well +
  recall; structural assert that the three AD-outside compounds are never
  picked.
- `views.py` + `web/src/routes/Experiment.tsx` — round chips carry
  `selection`; the DMTA panel grows a "why this plate" expansion: per pick
  the acquisition value + reason, per refusal the named gate (AD,
  diversity, no-posterior), never color-only.

## Eval definition (what "better" means)

- Pools: 4 seeded 24-compound pools (deterministic hash noise, ±35%
  surrogate, multiplicative; sd = 0.15 on log10, in-domain except 3
  hash-selected AD-outsiders per pool).
- Budget: k=4 × 2 rounds (8 wells), matched for both policies.
- After each selection, both policies "observe" the SAME deterministic
  pseudo-measurement (truth × ±10%) and update their posteriors
  identically.
- Metrics per policy: fraction of truly active among tested (`hits-per-well`),
  fraction of actives recalled, wells spent; `false picks` = AD-outside
  compounds selected (hard fail for bo-ei if > 0).
- Score: `bo_hits_per_well / max(rand_hits_per_well, 1)` capped at 1.0,
  pass bar 0.7 → bo-ei must strictly beat random to pass on average. If
  the seeded evidence says it does not, the task reports the honest
  sub-1.0 with both numbers — same treatment as adaptive-dose's 0.875.

## Non-goals (now)

- GP-BO libraries / kernels over fingerprints (the posterior is declared,
  not fitted here); multi-objective Pareto selection; plate-layout
  optimization; making the program card edit acquisition (launch plumbing
  only — recorded as remaining).
- Changing default selection behaviour for any existing command.

## Remaining after this slice

- Replay the policy on CS04's 26k-row EGFR corpus vs the RF surrogate
  (network-day study) — the seeded pools prove mechanics, that proves it on
  real distributions.
- Program-form picker + `_spawn_plan` forwarding once the eval is green.
- `bn select` as a standalone dry-run command.
