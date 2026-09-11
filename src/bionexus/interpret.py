"""Prediction attribution — "why" beside every model number.

Per-instance explanations for the built-in policies:
  - CharRidgePolicy: exact — each n-gram's (count × slot weight) contribution;
    hashed slots can collide, and the output says so.
  - MorganFingerprintRF: importance-weighted presence — global mean-decrease-
    impurity × bits active in THIS molecule; folded bits are hashed indices,
    not named substructures, and the output says so too.

Honesty rule: an explanation that overstates itself is worse than none.
"""
from __future__ import annotations

import math


def explain_prediction(policy, smiles: str) -> dict:
    name = getattr(policy, "name", type(policy).__name__)

    # --- char n-gram ridge: exact per-n-gram contributions -----------------
    if hasattr(policy, "w") and hasattr(policy, "_featurize"):
        n = getattr(policy, "ngram", 3)
        grams = [smiles[k:k + n] for k in
                 range(max(0, len(smiles) - n + 1))]
        counts: dict[int, float] = {}
        for g in grams:
            h = int(_md5(g)[:8], 16) % policy.dim
            counts[h] = counts.get(h, 0.0) + 1.0
        count_norm = math.sqrt(sum(c * c for c in counts.values())) or 1.0
        raw: dict[str, float] = {}
        for g in grams:
            h = int(_md5(g)[:8], 16) % policy.dim
            raw[g] = raw.get(g, 0.0) + policy.w[h] / count_norm
        contrib = sorted(raw.items(), key=lambda t: -abs(t[1]))
        pred = policy.predict(smiles)
        return {
            "policy": name, "method": "ngram-contributions",
            "prediction": round(pred, 3),
            "baseline_mean": round(getattr(policy, "mean", 0.0), 3),
            "top_positive": [(g, round(w, 3)) for g, w in contrib if w > 0][:5],
            "top_negative": [(g, round(w, 3)) for g, w in contrib if w < 0][-5:],
            "caveat": "hashed slots: an n-gram's weight may include collisions",
        }

    # --- random forest over folded Morgan bits: importance × presence ------
    if hasattr(policy, "model") and hasattr(policy, "_fp"):
        try:
            import numpy as np
            x = np.asarray(policy._fp(smiles))
            imp = np.asarray(policy.model.feature_importances_)
            active = np.nonzero(x)[0]
            ranked = sorted(active, key=lambda b: -imp[b] * x[b])
            pred = policy.predict(smiles)
            return {
                "policy": name, "method": "importance-weighted-bits",
                "prediction": round(float(pred), 3),
                "top_bits": [(int(b), round(float(imp[b]), 4))
                             for b in ranked[:8]],
                "n_active_bits": int(len(active)),
                "caveat": "folded Morgan bits are hashed indices, not named "
                          "substructures; map via fingerprint back-mapping "
                          "for chemistry-readable reasons",
            }
        except ImportError:
            pass

    return {"policy": name, "method": "none",
            "caveat": "this policy exposes no per-instance attribution"}


def _md5(s: str) -> str:
    import hashlib
    return hashlib.md5(s.encode()).hexdigest()  # noqa: S324


def explain_admet(summary: dict) -> dict:
    """Rule-based ADMET: the 'why' is the triggered rules themselves."""
    reasons = []
    if summary.get("lipinski_violations"):
        reasons.append(f"Lipinski: {summary['lipinski_violations']} violation(s)")
    if summary.get("pains_alerts"):
        reasons.append(f"PAINS: {', '.join(summary['pains_alerts'])}")
    if summary.get("mw_da", 0) and summary["mw_da"] > 500:
        reasons.append(f"MW {summary['mw_da']} Da > 500")
    return {"method": "triggered-rules", "reasons": reasons or ["no flags"],
            "prediction": None}


def explain_variant(impact) -> dict:
    """AlphaGenome AVI: feature attributions come with the score."""
    return {"method": "avi-feature-attributions",
            "prediction": impact.avi_score,
            "top_drivers": dict(sorted(impact.attributions.items(),
                                       key=lambda kv: -kv[1])[:3]),
            "caveat": "attribution categories, not per-feature gradients"}
