"""Derivation records — how a number was made, as DATA not prose.

The framework is instrument-generic: a plate reader's IC50, a qPCR fold
change, a sequencer's variant call and a microscope's cell count are made by
different chains. So no UI caption may hard-code one chain. Instead, every
analysis path attaches a `derivation` dict to its verdict, and the UI simply
renders whatever the record says.

Shape (all keys optional, so any domain can fill what it knows):
    measured_by:  "instrument (version)"
    raw:          {quantity, wells|reads|images|..., replicates}
    derived:      {metric, method, ci}
    decided_by:   {criteria}
"""
from __future__ import annotations


def describe(der: dict | None) -> str:
    """One generic line from a derivation dict. Unknown => says so."""
    if not der:
        return "derivation not recorded for this verdict"
    parts = []
    raw = der.get("raw") or {}
    seg = []
    if raw.get("quantity"):
        q = f"measured {raw['quantity']}"
        for unit_key, label in (("wells", "wells"), ("reads", "reads"),
                                ("images", "images"), ("peaks", "peaks"),
                                ("records", "records"), ("replicates", "replicates")):
            if raw.get(unit_key):
                q += f" · {raw[unit_key]} {label}"
        seg.append(q)
    if der.get("measured_by"):
        seg.append(f"on {der['measured_by']}")
    if seg:
        parts.append(" · ".join(seg))
    d = der.get("derived") or {}
    if d:
        line = f"derived {d.get('metric', 'value')}"
        if d.get("method"):
            line += f" via {d['method']}"
        if d.get("ci"):
            line += f" · CI: {d['ci']}"
        parts.append(line)
    dec = der.get("decided_by") or {}
    if dec.get("criteria"):
        parts.append(f"decided by pre-registered criteria: {dec['criteria']}")
    return " → ".join(p for p in parts if p) or "derivation not recorded"


def build(instrument: str | None = None, version: str | None = None,
          quantity: str | None = None, counts: dict | None = None,
          metric: str | None = None, method: str | None = None,
          ci: str | None = None, criteria: str | None = None) -> dict:
    """Convenience builder used by the analysis paths."""
    return {
        "measured_by": (f"{instrument} ({version})" if instrument and version
                        else instrument),
        "raw": {"quantity": quantity, **(counts or {})},
        "derived": {"metric": metric, "method": method, "ci": ci},
        "decided_by": {"criteria": criteria},
    }
