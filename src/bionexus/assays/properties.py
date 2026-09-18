"""Property-sweep analysis — the materials Analyze phase.

Reads a formulation sweep export (param vs measured property), finds the
best-performing formulation, and reports how sharply the property peaks
(so a flat sweep is reported honestly as 'no optimum found' instead of a
spurious winner).
"""
from __future__ import annotations

from pathlib import Path
import csv


def _num(v):
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return None


def read_property_sweep(path: str | Path, param: str | None = None,
                        metric: str | None = None) -> dict:
    """Parses rows with a parameter column and a metric column; returns
    the best formulation, the peak sharpness, and all points."""
    with open(path, newline="", encoding="utf-8", errors="replace") as fh:
        reader = csv.DictReader(fh)
        fields = {k.lower().strip(): k for k in (reader.fieldnames or [])}
        param_col = fields.get((param or "").lower()) or next(
            (fields[s] for s in ("crosslinker_pct", "dopant", "param",
                                 "concentration", "value")
             if s in fields), None)
        metric_col = fields.get((metric or "").lower()) or next(
            (fields[s] for s in ("tensile_strength_mpa", "conductivity",
                                 "property", "strength", "metric")
             if s in fields), None)
        if not param_col or not metric_col:
            raise ValueError("sweep export needs a parameter column and a "
                             f"metric column; saw {reader.fieldnames}")
        id_col = next((fields[s] for s in ("sample", "id", "formulation")
                       if s in fields), None)
        pts = []
        for row in reader:
            x, y = _num(row.get(param_col)), _num(row.get(metric_col))
            if x is None or y is None:
                continue
            pts.append((x, y, str(row.get(id_col, f"F{len(pts) + 1}"))))
    if len(pts) < 3:
        raise ValueError("need at least 3 sweep points")

    pts.sort()
    best_x, best_y, best_id = max(pts, key=lambda p: p[1])
    xs = [p[0] for p in pts]
    span = max(xs) - min(xs)
    # sharpness: how much better the best is vs the sweep mean
    mean_y = sum(p[1] for p in pts) / len(pts)
    sharpness = (best_y - mean_y) / max(span / max(len(pts) - 1, 1), 1e-9)
    return {"source": str(path), "param": param_col, "metric": metric_col,
            "points": [{"param": x, "value": y, "sample": sid}
                       for x, y, sid in pts],
            "best": {"param": best_x, "value": round(best_y, 3),
                     "sample": best_id},
            "peak_sharpness": round(sharpness, 3),
            "note": "" if sharpness > 1.0 else
            "flat sweep — no optimum stands out; do not over-read the "
            "best point"}
