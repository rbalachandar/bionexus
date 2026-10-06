# CS08 — Competition Entry Attempt (step 1: the discipline layer, zero GPU)

Goal: a serious, honest entry into a Proteinbase/Adaptyv binder-design
competition (Anthropic×Adaptyv live until Dec 2026). Step 1 builds and
PROVES the parts that need no GPU: eligibility gates, near-copy rule,
diversity selection, and a replay harness that scores selection POLICIES
against real wet-lab outcomes.

## What the replay on real data proved (`replay.py` -> `replay_results.json`)

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

## Built here (all deterministic, CI-tested, `tests/test_entry_gates.py`)
- `entry_gates.py` — competition rules as refuse-and-explain gates:
  40≤len≤250, standard residues, cysteine/homopolymer/low-complexity
  composition sanity, and a near-copy rule (≥75% 5-mer containment vs
  any known binder — documented proxy for "≥10 mutations away")
- `diversity_select.py` — farthest-first traversal (kept WITH its negative
  result, useful once candidates are quality-filtered upstream)
- `replay.py` — policy replay harness (the CS07 pattern, generalized)

## Step 2 (needs the rented 4090 — see `runpack/`)
BindCraft generation through our gates -> Boltz-1 interface screening
(the quality signal replay says we lack) -> gate+diverse selection within
the screened subset -> submission pack, fully `predicted_by`-stamped and
hash-chained. The run-pack scripts in `runpack/` are operator-runnable;
nothing in them has been executed against real hardware yet, and this
README will say so until it has.
