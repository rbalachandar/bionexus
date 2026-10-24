"""Case study 04 addendum — ACQUISITION REPLAY (does bo-ei actually help?).

The claim `bo-ei` must earn before it becomes a campaign default:

  1. on a surrogate that DOES rank the blinded EGFR library, EI must
     recover >= as many true actives as naive greedy (best-predicted-first)
     and as the interim champion gates+randomize;
  2. on a FLAT surrogate that cannot rank (the CS07/CS08 regime), EI must
     NOT beat random — if it does, the "advantage" is leakage, not science;
  3. EI must spend zero wells outside the applicability domain.

Real CS04 machinery, offline: the exact blinding + Morgan-RF surrogate from
run.py are reused, so arms share one discipline and one truth.

Run: .venv/bin/python case-studies/04-prospective-hit2lead/acq_replay.py
"""
from __future__ import annotations

import json
import random
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))
sys.path.insert(0, str(HERE))

import run as cs04                                   # noqa: E402
from bionexus.acquisition import (Posterior, randomize_batch,  # noqa: E402
                                  select_batch)

GATE_UM = 1.0                       # CS04 pre-registered hit bar (pIC50 >= 6)
SEED = 42
N_PERM = 200                        # seeds for the bootstrap spread per arm


def prepare_posteriors(library: dict[str, dict], pol):
    """Compute each candidate's (mean_um, tree_sd, family, in_domain,
    ad_note) ONCE — fingerprints, AD check and the forest-std are the slow
    part and must not re-run per permutation. Returns a spec list the
    correlated and flat arms both build on."""
    import numpy as np
    from rdkit import Chem, RDLogger
    from rdkit.Chem import rdFingerprintGenerator
    RDLogger.DisableLog("rdApp.*")
    gen = rdFingerprintGenerator.GetMorganGenerator(radius=pol.radius,
                                                     fpSize=pol.n_bits)
    cids = list(library)
    X = []
    valid = []
    for cid in cids:
        mol = Chem.MolFromSmiles(library[cid]["smiles"])
        valid.append(mol is not None)
        X.append([float(b) for b in gen.GetFingerprint(mol).ToBitString()]
                 if mol is not None else [0.0] * pol.n_bits)
    # forest-std: predict once per tree over the whole matrix, then std
    # across trees -> log10(IC50) fold uncertainty (pIC50 differs by a sign
    # + constant only), vectorized over candidates.
    per_tree = np.array([est.predict(X) for est in pol.model.estimators_])
    sd_by_cid = {cid: (round(float(per_tree[:, i].std()), 4) if valid[i] else 0.3)
                 for i, cid in enumerate(cids)}
    specs = []
    for i, cid in enumerate(cids):
        r = library[cid]
        chk = pol.ad.check(r["smiles"])
        specs.append({
            "candidate": cid, "mean": r["surrogate_pred_um"],
            "sd": sd_by_cid[cid], "family": cs04.murcko(r["smiles"]) or None,
            "in_domain": not chk["extrapolation"],
            "ad_note": (f"nn-Tanimoto {chk['nn_tanimoto']} < floor "
                        f"{chk['ad_floor']}" if chk["extrapolation"] else ""),
        })
    return specs


def build_posteriors(specs: list[dict], flat: bool, seed: int,
                     source: str) -> list[Posterior]:
    if flat:
        # decouple the surrogate from truth: permute the means across the
        # pool, keep the sd distribution. A "predictor" with no signal.
        rng = random.Random(seed)
        means = [s["mean"] for s in specs]
        rng.shuffle(means)
    else:
        means = [s["mean"] for s in specs]
    return [Posterior(candidate=s["candidate"], mean=m, sd=s["sd"],
                      family=s["family"], in_domain=s["in_domain"],
                      ad_note=s["ad_note"], source=source)
            for s, m in zip(specs, means)]


def _actives(library: dict[str, dict]) -> set[str]:
    return {cid for cid, r in library.items() if r["truth_um"] <= GATE_UM}


def _greedy(posters: list[Posterior], k: int, seed: int) -> set[str]:
    # naive exploit: best predicted potency first, ignores sd + AD
    order = sorted(posters, key=lambda p: (p.mean, p.candidate))
    return {p.candidate for p in order[:k]}


def _arm(posteriors, lib, k, arm, seed) -> dict:
    act = _actives(lib)
    if arm == "bo-ei":
        sel = select_batch(posteriors, k=k, target=GATE_UM, direction="min",
                           metric_log=True, seed=seed, max_per_family=1)
        picks = {p.candidate for p in sel.picks}
        ad_wells = sum(1 for p in posteriors
                       if p.candidate in picks and not p.in_domain)
    elif arm == "greedy":
        picks = _greedy(posteriors, k, seed)
        ad_wells = sum(1 for p in posteriors
                       if p.candidate in picks and not p.in_domain)
    else:  # gates+randomize (interim champion), AD-respecting
        sel = randomize_batch(posteriors, k=k, seed=seed,
                              skip_out_of_domain=True)
        picks = {p.candidate for p in sel.picks}
        ad_wells = 0
    hits = len(picks & act)
    return {"arm": arm, "seed": seed, "k": k, "hits": hits,
            "hits_per_well": round(hits / k, 4),
            "recall": round(hits / len(act), 4) if act else 0.0,
            "ad_wells": ad_wells}


def _bootstrap(posters, lib, k, arm, lo, hi) -> dict:
    """Repeat the pick under successive selection seeds; report the mean +
    percentile CI, honest about the spread."""
    res = [_arm(posters, lib, k, arm, seed=s) for s in range(lo, hi)]
    hits = [r["hits"] for r in res]
    hpw = sorted(r["hits_per_well"] for r in res)
    return {
        "mean_hits": round(statistics.mean(hits), 3),
        "hits_ci95": [round(hpw[int(0.025 * (len(hpw) - 1))], 3),
                      round(hpw[int(0.975 * (len(hpw) - 1))], 3)],
        "mean_hpw": round(statistics.mean(hpw), 3),
        "ad_wells_max": max(r["ad_wells"] for r in res),
    }


def study():
    corpus = cs04.load_corpus()
    drugs = json.loads((cs04.HERE / "heldout.json").read_text())["drugs"]
    pool, _reveal = cs04.blind_drugs(corpus, drugs)
    pol, _train, test = cs04.train_surrogate(pool)
    library = cs04.build_library(test, pol)
    act = _actives(library)
    base_rate = len(act) / len(library)

    specs = prepare_posteriors(library, pol)          # AD + tree-sd: once
    correlated = build_posteriors(specs, flat=False, seed=SEED,
                                  source="morgan2048-rf")

    out: dict = {"pool_n": len(library), "actives": len(act),
                 "base_rate": round(base_rate, 4),
                 "ad_outside_pool": sum(1 for s in specs if not s["in_domain"]),
                 "budgets": {}}

    for k in (6, 12):
        # flat regime: a fresh permutation per seed = a fresh useless
        # surrogate; bo-ei must track random, not beat it.
        flat_bo, flat_rand = [], []
        for s in range(N_PERM):
            fp = build_posteriors(specs, flat=True, seed=1000 + s,
                                  source="flat-morgan-rf")
            flat_bo.append(_arm(fp, library, k, "bo-ei", s)["hits"])
            flat_rand.append(_arm(fp, library, k, "random", s)["hits"])

        def pct(vals):
            v = sorted(vals)
            return [v[int(0.025 * (len(v) - 1))], v[int(0.975 * (len(v) - 1))]]

        out["budgets"][k] = {
            # correlated surrogate: bo-ei & greedy are deterministic on one
            # fixed pool; random varies with the selection seed.
            "correlated": {
                "bo-ei": _arm(correlated, library, k, "bo-ei", SEED),
                "greedy": _arm(correlated, library, k, "greedy", SEED),
                "random": _bootstrap(correlated, library, k, "random",
                                     0, N_PERM),
            },
            "flat": {
                "bo-ei": {"mean_hits": round(statistics.mean(flat_bo), 3),
                          "hits_ci95": pct(flat_bo)},
                "random": {"mean_hits": round(statistics.mean(flat_rand), 3),
                           "hits_ci95": pct(flat_rand)},
            },
        }
    return out


def main():
    out = study()
    (HERE / "acq_replay_results.json").write_text(json.dumps(out, indent=2))
    print(f"CS04 acquisition replay — pool={out['pool_n']} "
          f"actives={out['actives']} (base rate {out['base_rate']:.2f}/well) "
          f"AD-outside={out['ad_outside_pool']}")
    for k, regimes in out["budgets"].items():
        c = regimes["correlated"]
        print(f"\n  budget k={k} | surrogate CAN rank (correlated):")
        for arm in ("bo-ei", "greedy", "random"):
            b = c[arm]
            if "hits_ci95" in b and "ad_wells_max" in b:      # bootstrap
                print(f"    {arm:7s} mean_hits={b['mean_hits']:.2f} "
                      f"ci{b['hits_ci95']} ad_wells_max={b['ad_wells_max']}")
            elif "hits_ci95" in b:                            # flat-style
                print(f"    {arm:7s} mean_hits={b['mean_hits']:.2f} "
                      f"ci{b['hits_ci95']}")
            else:                                             # deterministic
                print(f"    {arm:7s} hits={b['hits']} "
                      f"hits/well={b['hits_per_well']:.2f} "
                      f"ad_wells={b['ad_wells']}")
        f = regimes["flat"]
        print(f"  budget k={k} | surrogate CANNOT rank (flat) — "
              f"bo-ei must ≈ random:")
        for arm in ("bo-ei", "random"):
            b = f[arm]
            print(f"    {arm:7s} mean_hits={b['mean_hits']:.2f} "
                  f"ci{b['hits_ci95']}")


if __name__ == "__main__":
    main()
