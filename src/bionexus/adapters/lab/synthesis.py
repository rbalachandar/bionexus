"""Virtual synthesis — Make as a first-class DMTA step.

Design decides the molecule; Make synthesizes and purifies it. The
virtual synthesizer is deterministic (seeded from candidate + structure)
so the same hypothesis always produces the same batch — reproducible
like everything else. Low-purity or low-yield batches are refused into
Test: a gate on the physical step, same as the assay gate.
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

    def synthesize(self, candidate: str, smiles: str | None = None) -> dict:
        seed = hashlib.sha256(
            f"{candidate}|{smiles or ''}".encode()).hexdigest()
        rng = random.Random(seed)
        if smiles:
            # designed molecules carry real synthetic risk: ~30% of
            # structures fail purity or yield (deterministic per structure)
            yield_pct = round(5 + rng.random() * 90, 1)
            purity = round(60 + rng.random() * 39.5, 1)
        else:
            # virtual candidates without structures are the lab's
            # abstraction — always synthesizable at high quality
            yield_pct = round(40 + rng.random() * 55, 1)
            purity = round(90 + rng.random() * 9.5, 1)
        ok = purity >= self.min_purity and yield_pct >= self.min_yield
        lot = "lot-" + seed[:8]
        return {"candidate": candidate, "smiles": smiles or "",
                "yield_pct": yield_pct, "purity": purity, "ok": ok,
                "lot": lot,
                "note": "" if ok else
                f"purity {purity} < {self.min_purity} or yield "
                f"{yield_pct} < {self.min_yield} — batch refused into Test"}
