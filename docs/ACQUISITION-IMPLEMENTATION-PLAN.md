# Bayesian Experiment Selection (acquisition policies) — Plan & Status

**Status:** Implemented + graded + replayed (Oct 2026): `bo-ei` selectable in
config/CLI, `bn select` what-would-run preview, "why this plate" on the
Experiment page, eval task `acquisition-policy` (0.875, strict dominance +
AD-honest), and the **CS04 offline replay** (below) delivered the honest
verdict: **EI ties naive greedy — it stays opt-in, not the default.**  
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

## Eval definition (what "better" means) — shipped as `acquisition-policy`

- Pools: 3 seeded 24-compound pools (seeds 11/42/7), truth from
  `SimulatorLab`; surrogate mean = truth × (1 ± 35%) deterministic hash
  noise, sd = 0.15 on log10, and 3 hash-selected AD-outsiders per pool.
- Budget: k=8, one batch, matched for both arms (EI vs gates+randomize).
- Metrics: hits-per-well (actives among the 8 / 8), recall of the pool's
  actives, and `ad_violations` = AD-outside compounds picked (hard fail for
  bo-ei if > 0).
- Score: bo-ei mean hits-per-well (0.875). **Pass = score ≥ 0.7 AND bo-ei
  strictly dominates random on EVERY pool AND zero AD violations** — a
  tie or a leaked AD pick fails. This task tests the *mechanics* on a
  correlated surrogate; it does NOT compare against greedy (that is the
  CS04 replay below, which is the harsher test).

## Non-goals (now)

- GP-BO libraries / kernels over fingerprints (the posterior is declared,
  not fitted here); multi-objective Pareto selection; plate-layout
  optimization; making the program card edit acquisition (launch plumbing
  only — recorded as remaining).
- Changing default selection behaviour for any existing command.

## CS04 replay verdict (ran offline on the frozen EGFR corpus)

`case-studies/04-prospective-hit2lead/acq_replay.py` reuses CS04's exact
blinding + Morgan-RF surrogate, then runs three budget-matched arms on the
36-candidate blinded library (22 true actives → **base rate 0.61/well**;
only 1 candidate falls outside the AD). The surrogate sd is real (RF
forest-std on the log axis), not invented.

| budget k | bo-ei | greedy (best-predicted-first) | random |
|---|---|---|---|
| 6 (correlated) | 6/6 hits | **6/6** hits | 3.59/6 |
| 12 (correlated) | 12/12 hits | **12/12** hits | 7.23/12 |
| 12 (FLAT surrogate, can't rank) | 7.41 [5–10] | — | 7.23 [5–10] |

Three findings, reported honestly:

1. **bo-ei beats random hugely — but that win is not EI's.** It comes from
   *using the surrogate at all* + respecting the AD gate. Naive greedy
   (rank by predicted potency, ignore uncertainty) **ties** EI at every
   budget. The uncertainty-bonus added nothing on CS04.
2. **The falsification control passes:** on a FLAT surrogate (predictions
   permuted against truth) bo-ei **ties random** (7.41 vs 7.23, overlapping
   CIs) — it does not manufacture an edge from noise. If it had *beaten*
   random here, that would be leakage; it didn't.
3. **AD discipline held:** zero wells spent outside the domain in every
   correlated run (`ad_wells=0`).

**Decision: bo-ei does NOT earn promotion to the default.** The plan's bar
was "ties-or-beats greedy to become default"; it ties, never beats, so the
cheaper greedy-surrogate ranking stays the sensible default when a working
surrogate exists, and `bo-ei` stays **opt-in**. CS04's pool is *too easy*
(61% actives, strong surrogate) to stress the one situation where EI should
shine — a sparse-actives pool where greedy over-commits to a confident-but-
wrong region. That hard case is not constructible offline here, so the
honest line is: **EI is proven safe (no leakage, AD-honesty) and proven
>= random, but NOT proven > greedy on available real data.**

## Status / remaining

- [x] CS04 replay — done, offline, negative-leaning (above).
- [x] `bn select` standalone what-would-run preview (same policy path, in-
      memory store, submits nothing; test-pinned to write no provenance).
- [ ] A hard pool (sparse actives, surrogate uncertain near the gate) is
      the only thing that could show EI > greedy — needs data we don't have
      frozen; recorded, not chased.
- [ ] Program-form picker: deferred indefinitely until a > greedy result
      exists; making `bo-ei` a UI default would oversell it.
