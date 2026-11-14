"""Physical failure-mode detection — the foam/retry gap.

Agents habitually treat instrument failures as software errors: retry,
retry, retry — while the plate is foaming. This module classifies bad
readings into PHYSICAL vs DATA causes before the agent's reasoning ever
sees them, using cheap sensor-plausibility checks tuned to the instrument
kind. Physical verdicts come with a recommended action (flag for operator,
do not retry) so the harness — not the LLM's general priors — decides.
"""
from __future__ import annotations


def classify(values: list[float], error: str | None = None,
             instrument: str | None = None) -> dict:
    """{kind: physical|data|unknown, evidence, action}"""
    if error:
        e = error.lower()
        if any(k in e for k in ("hardware", "communication", "timeout on device",
                                 "no response from instrument", "lamp",
                                 "motor", "vacuum", "temperature excursion")):
            return {"kind": "physical",
                    "evidence": f"device-level error: {error[:120]}",
                    "action": "do not retry blindly; flag for operator"}
        return {"kind": "data", "evidence": error[:120],
                "action": "re-parse or request corrected export"}
    vals = [v for v in values if v is not None]
    if not vals:
        return {"kind": "data", "evidence": "no numeric readings",
                "action": "check export mapping, then re-read once"}
    if len(vals) > 2:
        if max(vals) == min(vals):
            return {"kind": "physical",
                    "evidence": (f"all {len(vals)} readings identical "
                                 f"({vals[0]:g}) — detector saturation, "
                                 "unmixed wells, or plate not dispensed"),
                    "action": "do not retry; physical inspection required"}
        if max(vals) <= 1e-6:
            return {"kind": "physical",
                    "evidence": "zero signal across the plate — lamp/optics "
                                "or coupling failure likely",
                    "action": "do not retry; check reader optics"}
        spread = (max(vals) - min(vals))
        mean = sum(vals) / len(vals)
        if mean > 0 and spread / mean > 50:
            return {"kind": "physical",
                    "evidence": (f"dynamic range {spread / mean:.0f}x the "
                                 "mean — unit or dilution error, or spill"),
                    "action": "quarantine plate; operator review"}
    if any(v < 0 for v in vals):
        return {"kind": "physical",
                "evidence": "negative readings — baseline subtraction fault "
                            "or detector drift",
                "action": "flag instrument for recalibration"}
    return {"kind": "unknown", "evidence": "no physical signature detected",
            "action": "proceed with standard data-error handling"}
