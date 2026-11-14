"""The proxy ladder — a measure is always a proxy for the claim.

Bender et al.'s Goodhart warning, made mechanical: an IC50 is not target
engagement, target engagement is not cellular efficacy, cellular efficacy
is not the clinical question. Every criterion may therefore declare
`proxy_of`, and every verdict/rollup PRINTS the evidence distance — the
chain of rungs between what was measured and what is ultimately claimed.
Distance is never hidden by confident phrasing; a program gated on ic50
is four rungs from the patient, and the UI says so.

Default ladder (drug-discovery convention; extend per program by
declaring proxy_of on the criterion):

    ic50_um / percent_inhibition / kda / ...  (biophysical/biochemical)
      -> target_engagement
      -> cellular_efficacy
      -> animal_efficacy
      -> clinical_efficacy
"""
from __future__ import annotations

from typing import Any

CLINICAL = "clinical_efficacy"

#: metric -> the claim it is a proxy FOR (one rung up)
LADDER: dict[str, str] = {
    "ic50_um": "target_engagement",
    "ic50": "target_engagement",
    "percent_inhibition": "target_engagement",
    "potency_pct": "target_engagement",
    "kd_nM": "target_engagement",
    "tensile_mpa": "preclinical_performance",
    "strength_mpa": "preclinical_performance",
    "target_engagement": "cellular_efficacy",
    "cellular_efficacy": "animal_efficacy",
    "in_vivo_potency": "animal_efficacy",
    "animal_efficacy": "clinical_efficacy",
    "preclinical_performance": "clinical_efficacy",
}


def chain(metric: str, proxy_of: str | None = None) -> list[str]:
    """The full evidence chain from `metric` up to the clinical claim.

    `proxy_of` (when declared) overrides the default ladder step for the
    starting metric; the walk then follows the canonical ladder. Cycles
    stop the walk — an unresolvable claim distance is reported as such,
    never as zero."""
    chain_: list[str] = [metric]
    cur = (proxy_of or LADDER.get(metric) or "").strip()
    while cur and cur != CLINICAL and cur not in chain_:
        chain_.append(cur)
        cur = LADDER.get(cur, "")
    if cur == CLINICAL:
        chain_.append(CLINICAL)
    return chain_


def distance(metric: str, proxy_of: str | None = None) -> dict[str, Any]:
    """{"rungs": int | None, "chain": [...], "claim": clinical}.
    rungs=None => the chain does not reach the clinical claim from this
    metric (an unresolved proxy — say so, don't print 0)."""
    c = chain(metric, proxy_of)
    return {"rungs": len(c) - 1 if c and c[-1] == CLINICAL else None,
            "chain": c,
            "claim": CLINICAL,
            "resolved": bool(c) and c[-1] == CLINICAL}


def evidence_line(metric: str, proxy_of: str | None = None) -> str:
    d = distance(metric, proxy_of)
    if not d["resolved"]:
        return (f"proxy chain from '{metric}' does not reach the clinical "
                f"claim ({'→'.join(d['chain'])}) — unresolved")
    n = d["rungs"]
    return (f"evidence distance: {n} rung{'s' if n != 1 else ''} from "
            f"clinical ({'→'.join(d['chain'])})")
