# CS08 — Competition Entry Attempt (two steps: discipline layer, then a real prospective GPU run)

Goal: a serious, honest entry into a Proteinbase/Adaptyv binder-design
competition (Anthropic×Adaptyv live until Dec 2026). Step 1 builds and
PROVES the parts that need no GPU: eligibility gates, near-copy rule,
diversity selection, and a replay harness that scores selection POLICIES
against real wet-lab outcomes. Step 2 rents a GPU, generates real designs
with the real models, and tests the screening score against self-run
random-looking controls — prospectively, on data nobody has seen before.

## How BioNexus is in the loop (and where the LLM is — it isn't)

This pipeline runs on three BioNexus pieces, all deterministic:

- `entry_gates.py` — refuse-and-explain eligibility (the gateway doctrine
  applied to sequences)
- `ProteinDesignLabAdapter` (`src/bionexus/adapters/lab/protein_design.py`)
  — the architecture: generate → quality floor → EVERY survivor becomes a
  hypothesis → prioritize for screening budget → verdict with an
  abstention band around the gate
- the proxy-evidence discipline (S-T1.2/P8): every ipTM verdict is stamped
  `predicted_by: {source: boltz2, policy: ...}` — it is PROXY evidence
  about a model's opinion, never a binding measurement

**No LLM was used anywhere in the science.** No API key, no prompts, no
verdicts delegated to a model. The LLM slots in only at the edges
(hypothesis-agent ideation, workbench narrative) — this case study is the
proof that the epistemic spine works keyless and reproducible.

## Step 1 — what the replay on real data proved (`replay.py` -> `replay_results.json`)

Policies evaluated on the frozen tested corpora (slots = 25% of pool):

| policy | Nipah (baseline 10.0%) | EGFR (baseline 15.7%) |
|---|---|---|
| random without gates | 8.6% | 12.6% |
| pLDDT top-quartile | **7.4%** | **10.2%** |
| gates-only random | 10.1% | 16.5% |
| naive farthest-first diversity | 8.6% | **5.3%** |

Three findings, each uncomfortable and each publishable:

1. **Eligibility gating is FREE** (~90% of pool passes the competition
   rules; pass-through hit rate = baseline, ±1.5pp). Rules cost nothing;
   rejecting non-compliant designs is not a selection sacrifice.
2. **Every available score ranks WORSE than random** (confirms CS07).
   Until an interface-aware scorer exists, the correct policy is
   **gate + randomize — do not rank.**
3. **Naive diversity selection is actively harmful** (EGFR 5.3%):
   farthest-first in sequence space picks OUTLIERS, and outliers are
   disproportionately failed designs, not bold ones. Diversity must be a
   constraint *within* a quality-filtered set, never the objective.
    The naive version is kept in the harness as a documented footgun.

## Step 2 — the prospective GPU run (executed Oct 2026, RTX A5000, ~$5)

The real stack, on a rented pod, end to end:

- **Generate**: BindCraft (AF2-backprop against PD-L1 hotspot-56,
  115-residue ECD from ATOM records) → MPNN → **82 binder sequences**
  (from a 138-sequence pool after the run finished)
- **Screen**: Boltz-2 `--use_msa_server --max_msa_seqs 64` — 82 designs,
  16 min GPU prediction, plus **30 self-run controls through the identical
  protocol**: 20 amino-acid-**composition-matched scrambles** of the
  top-20 designs and 10 random 100-mers against the same PD-L1 target
- **Analyze**: `prospective_run.py` → `prospective_results.json`
  (raw artifacts: `.data/cs08-designs/night1/`, gitignored; analysis
  reruns from files only)

| | designs (n=82) | scrambles (n=20) | random (n=10) |
|---|---|---|---|
| ipTM median | **0.894** | 0.680 | 0.694 |
| ipTM max | 0.951 | **0.937** | 0.904 |

Findings (each is the point of the experiment):

1. **Distributions separate; individuals do not.** Designs beat controls
   as a group (Mann-Whitney p≈1e-4; median-difference bootstrap
   CI95 [+0.12, +0.30]) — but **AUC is only 0.80**, 6/30 controls sit
   above the design median, and the best *scramble* (0.937) out-ranks
   89% of real designs (73/82 below 0.937). "Order my list by ipTM" is not a ranking of
   binders; it is a ranking of Boltz's confidence, which shuffling
   composition-preserved garbage can also achieve.
2. **The Step-1 replay conclusion is validated prospectively on
   self-generated data**: gate + randomize, do not rank — and we now hold
   the strongest possible version of that claim (we generated the
   molecules, ran the controls, and the score still cannot tell a
   designed binder from its own anagram).
3. **Composition gates are blind by construction** — 82/82 designs,
   20/20 scrambles, 9/10 randoms pass eligibility. Gates are cheap
   hygiene (length/cys/homopolymer compliance), never detection.
4. **Honest verdicts under the 0.7 gate** (run in the tracker, step 3
   below): 72 validated, 4 invalidated, **6 inconclusive** — the declared
   ±0.05 single-prediction band straddles the gate, so near-gate designs
   abstain (same physics as the small-molecule side). Every verdict
   carries `predicted_by: boltz2` proxy stamping; nothing here is a
   binding measurement.
5. **Entry decision: NO-GO as ranker, GO as gate.** Submitting an
   ipTM-ordered list would misrepresent the evidence we generated. The
   defensible play is a gated, diverse shortlist (floor-passed, near-copy
   screened) with the ranking claim withdrawn — or a wet-lab validation
   round, which is the only thing that would upgrade this evidence tier.

Caveats we own (small-n discipline): one target; one prediction per
complex (no replicate variance — per-item ipTM is a point estimate, so
individual verdicts are stated with a ±band, never bare); designed
sequences return near-empty MSAs (correct, but different from
natural-sequence behavior); Boltz is known-optimistic on designed binders
— the finding is about *ranking ability*, not absolute affinity.

## In the workbench

```sh
.venv/bin/python case-studies/08-proteinbase-entry/seed_workbench.py  # idempotent
make api   # -> http://localhost:8000
```

Program card **CS08 PD-L1 Designs** renders with verdict `partial`, one
2-batch screening experiment (82 + 30), and per-hypothesis cards whose
**origin** line decodes the molecule (length / AF2 seed / MPNN sample;
controls name their parent anagram) and whose **refuted if** clause was
pre-registered at propose time — including the controls' own meta-clause:
*"if this control validates while clearing the same bar as real designs,
the ranking value of ipTM is itself refuted."* It fired for 11 of them,
on the hash chain. That is the use-case in miniature: the framework does
not merely store results; it holds us to what we dared claim *before* we
saw them, and lets the data refute the instrument — with no LLM in the
loop at all.

## Step 3 — the loop itself: BioNexus over the measured data (`bionexus_cycle.py`, CPU, no LLM)

The GPU spoke; the framework listens. All 112 sequences (82 designs + 30
controls) run through the real pipeline — quality floor → EVERY survivor
proposed as a hypothesis with the `iptm >= 0.7` criteria PRE-REGISTERED →
verdict with CI veto (single prediction, declared ±0.05 band, so designs
near the gate abstain instead of coin-flipping) → outcomes sealed into
the SQLite **hash-chained provenance store** (`verify_chain()` → intact).

The tally is the demo:

| role | validated | invalidated | inconclusive |
|---|---|---|---|
| designs | 72 | 4 | 6 (CI straddles gate → abstain) |
| **scrambles** | **8** | 10 | 2 |
| **random peptides** | **3** | 4 | 3 |

The controls' "validated" rows are not mistakes — they are the FIRST-CLASS
finding, recorded honestly in the chain: a random peptide at ipTM 0.90 and
an anagram of a top design at 0.937 clear the same bar the real designs
clear. The evidence line says it flat out: `iptm → pd_l1_binding_kd —
UNRESOLVED` (the proxy chain does not reach the claim; the Goodhart guard
declines to launder model confidence into biology). A dashboard that hides
those rows would be the thing to refuse.

## Built here (all deterministic, CI-tested)
- `entry_gates.py` — competition rules as refuse-and-explain gates:
  40≤len≤250, standard residues, cysteine/homopolymer/low-complexity
  composition sanity, and a near-copy rule (≥75% 5-mer containment vs
  any known binder — documented proxy for "≥10 mutations away")
- `diversity_select.py` — farthest-first traversal (kept WITH its negative
  result, useful once candidates are quality-filtered upstream)
- `replay.py` — policy replay harness (the CS07 pattern, generalized)
- `prospective_run.py` — the Step-2 analysis above (scipy MWU, bootstrap
  CI, gate stats, verdict counts) → `prospective_results.json`
- `bionexus_cycle.py` — the Step-3 loop: hypotheses, CI-veto verdicts,
  hash-chained sealing → `bionexus_cycle_results.json` + the chain DB
- `seed_workbench.py` — surfaces the campaign in the workbench UI: program
  card, pre-registered problem tree, per-hypothesis provenance statements
  (every design decoded: length/AF2 seed/MPNN sample from the name; every
  control named with its parent scramble), 2 batched lab-runs, all sealed
  into the live `bionexus.db` hash chain
- `runpack/` — operator-runnable pod scripts (setup + BindCraft/Boltz
  YAML builders — including the three-letter→one-letter ATOM-record
  extraction fix and the `--use_msa_server` requirement that ate two
  nights). The pod run's TRACE is the downloaded logs + artifacts in
  `.data/cs08-designs/night1/` + `prospective_results.json`; its
  BOOKKEEPING is step 3 (`bionexus_cycle.py` sealing into
  `.data/cs08-bionexus-cycle.db`). `jobrunner.py` — chaining DURING the
  GPU run itself — is mock-tested (`tests/test_protein_design.py`) and
  stays the path for the next campaign; this run chains AFTER it, and
  we say so.
