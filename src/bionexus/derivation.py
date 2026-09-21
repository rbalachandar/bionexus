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


_UNIT_SUFFIX = {"um": "µM", "nm": "nM", "us": "µs", "ct": "Ct",
                "mpa": "MPa", "pct": "%", "nm2": "nm²"}

# machine metric -> human wording (verdicts read like the program's goal)
_METRIC_WORDS = {
    "potency_pct": "potency",
    "potency": "potency",
    "tensile_strength_mpa": "tensile strength",
    "tensile": "tensile strength",
    "strength_mpa": "strength",
    "conductivity": "conductivity",
    "density": "density",
    "thermal_stability": "thermal stability",
    "stability": "stability",
    "aggregation": "aggregation",
    "immunogenicity": "immunogenicity",
    "expression": "expression",
    "sterility": "sterility",
    "phenotype_stability": "phenotype stability",
    "organism_dose_response": "organism response",
    "phytotoxicity": "phytotoxicity",
    "fold_change": "fold change",
    "ic50_um": "IC50",
    "ic50": "IC50",
}


def metric_label(metric: str | None) -> str:
    """Machine metric -> human wording: ic50_um -> 'IC50 (µM)';
    potency_pct -> 'potency (%)'; tensile_strength_mpa ->
    'tensile strength (MPa)'. Unknown metrics prettify."""
    if not metric:
        return "value"
    m = metric.strip().lower()
    if m in _METRIC_WORDS:
        base = _METRIC_WORDS[m]
        suffix = m.split("_")[-1]
        if suffix in _UNIT_SUFFIX and suffix not in ("ct",):
            return f"{base} ({_UNIT_SUFFIX[suffix]})"
        return base
    parts = metric.split("_")
    if len(parts) > 1 and parts[-1].lower() in _UNIT_SUFFIX:
        return (f"{'_'.join(parts[:-1]).upper()} "
                f"({_UNIT_SUFFIX[parts[-1].lower()]})")
    return metric.replace("_", " ")


def criteria_label(metric: str | None, direction: str | None,
                   threshold) -> str:
    if metric is None or threshold is None:
        return ""
    op = "≤" if direction == "min" else "≥" if direction == "max" else "="
    return f"{metric_label(metric)} {op} {threshold:g}"


def describe(der: dict | None) -> str:
    """One generic line from a derivation dict. Unknown => says so."""
    if not der:
        return "derivation not recorded for this verdict"
    parts = []
    raw = der.get("raw") or {}
    obs = []
    if raw.get("quantity"):
        obs.append(f"measured {raw['quantity']}")
    for unit_key, label in (("wells", "wells"), ("reads", "reads"),
                            ("images", "images"), ("peaks", "peaks"),
                            ("records", "records"), ("replicates", "replicates")):
        if raw.get(unit_key):
            obs.append(f"{raw[unit_key]} {label}")
    clause = " ".join(obs)
    if clause and der.get("measured_by"):
        clause += f" on {der['measured_by']}"
    if clause:
        parts.append(clause)
    d = der.get("derived") or {}
    if d.get("metric") or d.get("method"):
        line = f"{metric_label(d.get('metric'))}"
        line += f" by {d['method']}" if d.get("method") else "derived"
        if d.get("ci"):
            line += f", {d['ci']}"
        parts.append(line)
    dec = der.get("decided_by") or {}
    crit = (criteria_label(dec.get("metric"), dec.get("direction"),
                           dec.get("threshold"))
            or dec.get("criteria") or "")
    if crit:
        parts.append(f"gate: {crit}")
    return "  →  ".join(p for p in parts if p) or "derivation not recorded"


def build(instrument: str | None = None, version: str | None = None,
          quantity: str | None = None, counts: dict | None = None,
          metric: str | None = None, method: str | None = None,
          ci: str | None = None, criteria: str | None = None,
          criteria_metric: str | None = None,
          criteria_direction: str | None = None,
          criteria_threshold=None) -> dict:
    """Convenience builder used by the analysis paths. Pass criteria as
    structured parts when available (renders humanely); a plain string still
    works for legacy callers."""
    return {
        "measured_by": (f"{instrument} ({version})" if instrument and version
                        else instrument),
        "raw": {"quantity": quantity, **(counts or {})},
        "derived": {"metric": metric, "method": method, "ci": ci},
        "decided_by": ({"metric": criteria_metric,
                        "direction": criteria_direction,
                        "threshold": criteria_threshold}
                       if criteria_metric is not None
                       else {"criteria": criteria}),
    }
