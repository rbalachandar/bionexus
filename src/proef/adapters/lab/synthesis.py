"""Virtual production — Make as a first-class, modality-agnostic step.

Design decides the intervention; Make produces it. For small molecules
that is chemical synthesis; for biologics, expression and purification;
for other modalities, whatever production means. The QC semantics are
shared: every batch gets a yield, a purity, and a lot id, and batches
below spec are refused into Test. Deterministic (seeded from candidate
+ structure/sequence) so the same design always produces the same batch.
"""
from __future__ import annotations

import hashlib
import random

MIN_PURITY = 85.0
MIN_YIELD = 10.0


class VirtualSynthesizer:
    """Deterministic virtual synthesis: batch yield and purity from the
    candidate identity. A SMILES (when present) shifts the seed — the
    same structure always synthesizes the same way."""

    name = "virtual-synthesis"

    def __init__(self, min_purity: float = MIN_PURITY,
                 min_yield: float = MIN_YIELD):
        self.min_purity = min_purity
        self.min_yield = min_yield

    # how each modality words its production step
    ACTIONS = {"small molecule": "synthesized",
               "": "synthesized",
               "biologic": "expressed and purified",
               "cell therapy": "engineered and expanded",
               "mRNA": "transcribed and encapsulated"}

    def synthesize(self, candidate: str, smiles: str | None = None,
                   modality: str = "", attempt: int = 1,
                   route: dict | None = None) -> dict:
        """attempt > 1 is a REAL re-synthesis: process re-optimization on a
        different route run (its own lot seed), recorded separately. One
        refused batch never silently dooms a candidate that a second
        process run could deliver — and each attempt is provenance.

        route: a planned RoutePlan.summary() from the retrosynthesis
        adapter. When given, batch yield is drawn from the ROUTE'S MODELED
        overall yield (± seeded process variance) instead of a flat prior —
        Make answers to the plan, and the plan is stamped into the batch."""
        seed = hashlib.sha256(
            f"{candidate}|{smiles or ''}|a{attempt}".encode()).hexdigest()
        rng = random.Random(seed)
        if smiles and route:
            # batch yield is DRAWN FROM THE ROUTE (modeled overall yield ±
            # seeded process variance), not a flat prior
            mu = float(route.get("yield_pct", 50.0))
            yield_pct = round(min(95.0, max(1.0, rng.gauss(mu, mu * 0.25))), 1)
            purity = round(78 + rng.random() * 21.5, 1)
        elif smiles:
            # designed molecules carry real synthetic risk: ~30% of
            # structures fail purity or yield (deterministic per structure).
            # Distribution calibrated to that stated claim: an earlier
            # uniform purity U[60,99.5] against a 85 gate failed ~2/3 of
            # batches — a Make stub should not dominate a real-data study
            # (CS04 caught the intent/behavior mismatch).
            yield_pct = round(5 + rng.random() * 90, 1)
            purity = round(78 + rng.random() * 21.5, 1)
        else:
            # virtual candidates without structures are the lab's
            # abstraction — always synthesizable at high quality
            yield_pct = round(40 + rng.random() * 55, 1)
            purity = round(90 + rng.random() * 9.5, 1)
        ok = purity >= self.min_purity and yield_pct >= self.min_yield
        lot = "lot-" + seed[:8]
        out = {"attempt": attempt,
               "candidate": candidate, "smiles": smiles or "",
               "modality": modality,
               "action": self.ACTIONS.get(modality.lower().strip(),
                                          "produced"),
               "yield_pct": yield_pct, "purity": purity, "ok": ok,
               "lot": lot,
               "note": "" if ok else
               f"purity {purity} < {self.min_purity} or yield "
               f"{yield_pct} < {self.min_yield} — batch refused into Test"}
        if route:  # batch answers to a planned route — stamp everything
            out["route"] = route.get("route", "")
            out["route_steps"] = route.get("steps")
            out["route_yield_model_pct"] = route.get("yield_pct")
            out["route_lead_time_days"] = route.get("lead_time_days")
            out["route_cost_usd"] = route.get("cost_usd")
            out["data_origin"] = route.get("data_origin", "")
        return out
