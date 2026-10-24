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


import math


def _spec(cid, mean_um, sd, pred_pic50, r, ad_pol):
    chk = ad_pol.ad.check(r["smiles"])
    return {
        "candidate": cid, "mean": mean_um, "sd": sd,
        "pred_pic50": pred_pic50,
        "truth_pic50": r["median"], "truth_um": r["truth_um"],
        "family": cs04.murcko(r["smiles"]) or None,
        "in_domain": not chk["extrapolation"],
        "ad_note": (f"nn-Tanimoto {chk['nn_tanimoto']} < floor "
                    f"{chk['ad_floor']}" if chk["extrapolation"] else ""),
    }


def rf_specs(library: dict[str, dict], pol):
    """RF-tree-sd posteriors (the shipped default provider). Forest variance
    is the epistemic proxy. AD check comes from the same RF for both
    providers, so RF-vs-GP comparison holds the domain gate CONSTANT and
    varies only the posterior."""
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
    per_tree = np.array([est.predict(X) for est in pol.model.estimators_])
    specs = []
    for i, cid in enumerate(cids):
        r = library[cid]
        mean_um = r["surrogate_pred_um"]
        sd = (round(float(per_tree[:, i].std()), 4) if valid[i] else 0.3)
        pred_pic50 = 6.0 - math.log10(mean_um) if mean_um > 0 else 6.0
        specs.append(_spec(cid, mean_um, sd, pred_pic50, r, pol))
    return specs


def gp_specs(library: dict[str, dict], train: dict, ad_pol, max_train: int = 800):
    """BoTorch GP posteriors, OPTIONAL (skipif botorch absent). The GP
    provides (mean, sd); the AD gate is still the RF's, so the only changed
    thing is the posterior the acquisition ranks on.

    Exact-GP is O(n^3): the CS04 train pool is ~9.5k, so we fit on a seeded
    subsample — a stated, budgeted approximation (this is exactly why a GP
    is not a free default), not an oversight. Coverage was checked to stay
    near nominal at this size."""
    from bionexus.adapters.models.gp_policy import GaussianProcessPolicy
    rng = random.Random(SEED)
    sub = list(train.items())
    rng.shuffle(sub)
    sub = sub[:max_train]
    gp = GaussianProcessPolicy(seed=SEED)                 # tuned defaults
    gp.fit([(smi, v["median"]) for smi, v in sub])
    specs = []
    for cid, r in library.items():
        mean_pic50, sd = gp.predict_with_sd(r["smiles"])
        mean_um = 10 ** (6.0 - mean_pic50)
        specs.append(_spec(cid, mean_um, sd, mean_pic50, r, ad_pol))
    return specs


def calibration_coverage(specs: list[dict]) -> dict:
    """Is the declared sd HONEST? Empirical coverage: |pred − truth| (pIC50,
    truth scatter included) within 1·sd / 2·sd, plus corr(sd, |err|). A
    calibrated provider lands near nominal ~68% / ~95% AND correlates
    sd with error; a too-confident one under-covers."""
    cov1 = cov2 = corr_n = 0
    sds, errs = [], []
    for s in specs:
        err = abs(s["pred_pic50"] - s["truth_pic50"])
        cov1 += 1 if err <= s["sd"] else 0
        cov2 += 1 if err <= 2 * s["sd"] else 0
        sds.append(s["sd"]); errs.append(err)
    n = len(specs) or 1
    def _corr(a, b):
        ma, mb = sum(a) / len(a), sum(b) / len(b)
        num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
        da = math.sqrt(sum((x - ma) ** 2 for x in a))
        db = math.sqrt(sum((y - mb) ** 2 for y in b))
        return round(num / (da * db), 3) if da and db else 0.0
    return {"coverage_1sd": round(cov1 / n, 3),
            "coverage_2sd": round(cov2 / n, 3),
            "corr_sd_error": _corr(sds, errs),
            "n": n}


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


def _budgets(specs, library, source):
    out = {}
    for k in (6, 12):
        correlated = build_posteriors(specs, flat=False, seed=SEED, source=source)
        flat_bo, flat_rand, flat_greedy = [], [], []
        for s in range(N_PERM):
            fp = build_posteriors(specs, flat=True, seed=1000 + s,
                                  source="flat-" + source)
            flat_bo.append(_arm(fp, library, k, "bo-ei", s)["hits"])
            flat_rand.append(_arm(fp, library, k, "random", s)["hits"])
            flat_greedy.append(_arm(fp, library, k, "greedy", s)["hits"])

        def pct(vals):
            v = sorted(vals)
            return [v[int(0.025 * (len(v) - 1))], v[int(0.975 * (len(v) - 1))]]
        out[k] = {
            "correlated": {
                "bo-ei": _arm(correlated, library, k, "bo-ei", SEED),
                "greedy": _arm(correlated, library, k, "greedy", SEED),
                "random": _bootstrap(correlated, library, k, "random", 0, N_PERM),
            },
            "flat": {
                "bo-ei": {"mean_hits": round(statistics.mean(flat_bo), 3),
                          "hits_ci95": pct(flat_bo)},
                "greedy": {"mean_hits": round(statistics.mean(flat_greedy), 3),
                           "hits_ci95": pct(flat_greedy)},
                "random": {"mean_hits": round(statistics.mean(flat_rand), 3),
                           "hits_ci95": pct(flat_rand)},
            },
        }
    return out


def study():
    corpus = cs04.load_corpus()
    drugs = json.loads((cs04.HERE / "heldout.json").read_text())["drugs"]
    pool, _reveal = cs04.blind_drugs(corpus, drugs)
    pol, train, test = cs04.train_surrogate(pool)
    library = cs04.build_library(test, pol)
    act = _actives(library)
    base_rate = len(act) / len(library)

    providers: dict[str, dict] = {}
    rf = rf_specs(library, pol)
    providers["morgan2048-rf"] = {"specs": rf, "cal": calibration_coverage(rf)}
    try:
        gp = gp_specs(library, train, pol)
        providers["morgan-gp"] = {"specs": gp, "cal": calibration_coverage(gp)}
    except Exception as exc:                  # botorch absent → documented skip
        providers["morgan-gp"] = {"skipped": str(exc)[:120]}

    out: dict = {"pool_n": len(library), "actives": len(act),
                 "base_rate": round(base_rate, 4),
                 "ad_outside_pool": sum(1 for s in rf if not s["in_domain"]),
                 "providers": {}}
    for name, p in providers.items():
        if "specs" not in p:
            out["providers"][name] = {"skipped": p["skipped"]}
            continue
        out["providers"][name] = {
            "calibration": p["cal"],
            "budgets": _budgets(p["specs"], library, name)}
    return out


def main():
    out = study()
    (HERE / "acq_replay_results.json").write_text(json.dumps(out, indent=2))
    print(f"CS04 acquisition replay — pool={out['pool_n']} "
          f"actives={out['actives']} (base rate {out['base_rate']:.2f}/well) "
          f"AD-outside={out['ad_outside_pool']}")
    for name, prov in out["providers"].items():
        if "skipped" in prov:
            print(f"\n  provider {name}: SKIPPED ({prov['skipped']})")
            continue
        cal = prov["calibration"]
        print(f"\n  provider {name} — calibration "
              f"(is the sd honest? target ~0.68 / ~0.95):")
        print(f"    cov1sd={cal['coverage_1sd']:.2f} "
              f"cov2sd={cal['coverage_2sd']:.2f} "
              f"corr(sd,err)={cal['corr_sd_error']:.2f}  n={cal['n']}")
        for k, regimes in prov["budgets"].items():
            c = regimes["correlated"]
            bo, gr = c["bo-ei"]["hits"], c["greedy"]["hits"]
            rnd = c["random"]["mean_hits"]
            verdict = ("BEATS greedy" if bo > gr
                       else "ties greedy" if bo == gr else "loses to greedy")
            print(f"    k={k} correlated: bo-ei={bo} greedy={gr} "
                  f"random={rnd:.1f}  →  EI {verdict}")
            f = regimes["flat"]
            print(f"    k={k} flat (no-signal surrogate): bo-ei≈"
                  f"{f['bo-ei']['mean_hits']:.1f} "
                  f"greedy≈{f['greedy']['mean_hits']:.1f} "
                  f"random≈{f['random']['mean_hits']:.1f}")


if __name__ == "__main__":
    main()
