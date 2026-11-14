"""Virtual bioprocess QC — the biologic Make/Test boundary.

For biologic batches that passed synthesis: a deterministic stability
and aggregation screen (seeded from the sequence). A batch with high
aggregation risk or a short half-life is refused into Test — the same
gate-on-the-physical-step pattern as synthesis, so biologics get a real
Make before any assay runs.
"""
from __future__ import annotations

import hashlib
import random

MAX_AGGREGATION = 0.35
MIN_T_HALF_H = 12.0


def bioprocess_qc(candidate: str, sequence: str,
                  lot: str) -> dict:
    seed = hashlib.sha256(f"{candidate}|{sequence}|{lot}".encode()).hexdigest()
    rng = random.Random(seed)
    aggregation = round(rng.random(), 3)
    t_half = round(4 + rng.random() * 40, 1)        # hours
    ok = aggregation <= MAX_AGGREGATION and t_half >= MIN_T_HALF_H
    reasons = []
    if aggregation > MAX_AGGREGATION:
        reasons.append(f"aggregation risk {aggregation} > {MAX_AGGREGATION}")
    if t_half < MIN_T_HALF_H:
        reasons.append(f"t½ {t_half}h < {MIN_T_HALF_H}h")
    return {"candidate": candidate, "lot": lot,
            "aggregation_risk": aggregation, "t_half_h": t_half,
            "ok": ok, "note": "; ".join(reasons)}
