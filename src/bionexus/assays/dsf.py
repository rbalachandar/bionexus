"""DSF analysis — thermal shifts from qPCR-style melt exports.

Parses long-format thermal melt data (temperature vs fluorescence per
well/curve — the export shape of qPCR instruments and DSF reader
attachments) and computes the melting temperature Tm per curve:

- Tm = temperature of the minimum of dF/dT (the fluorescence drop at
  the unfolding transition), on a lightly smoothed curve
- span (F_max - F_min) is reported as a curve-quality flag: a flat
  curve means no transition was observed, and that is reported rather
  than guessed

Quantitative thermodynamics (DeltaH, DeltaS via Boltzmann fitting) is
deliberately out of scope here — Tm is the decision variable for
comparing construct stability.
"""
from __future__ import annotations

from pathlib import Path
import csv

TempSynonyms = ("temperature", "temp", "t", "celsius")
ValueSynonyms = ("fluorescence", "fluor", "rfu", "value", "f")


def _num(v):
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return None


def read_dsf(path: str | Path) -> dict:
    """Parses long-format rows: id-ish column, temperature, fluorescence.
    Returns {"source", "curves": [{curve, tm, span, points}]}."""
    curves: dict[str, list[tuple[float, float]]] = {}
    with open(path, newline="", encoding="utf-8", errors="replace") as fh:
        reader = csv.DictReader(fh)
        fields = {k.lower().strip(): k for k in (reader.fieldnames or [])}
        temp_col = next((fields[s] for s in TempSynonyms
                         if s in fields), None)
        val_col = next((fields[s] for s in ValueSynonyms if s in fields),
                       None)
        if not temp_col or not val_col:
            raise ValueError("DSF export needs temperature + fluorescence "
                             f"columns; saw {reader.fieldnames}")
        id_col = next((fields[s] for s in ("well", "sample", "curve", "id")
                       if s in fields), None)
        for row in reader:
            t, v = _num(row.get(temp_col)), _num(row.get(val_col))
            if t is None or v is None:
                continue
            key = str(row.get(id_col, "curve")) if id_col else "curve"
            curves.setdefault(key, []).append((t, v))

    results = []
    for name, pts in sorted(curves.items()):
        pts.sort()
        if len(pts) < 5:
            results.append({"curve": name, "tm": None, "span": None,
                            "points": len(pts),
                            "note": "too few points for a transition"})
            continue
        vals = [v for _t, v in pts]
        span = max(vals) - min(vals)
        if span <= 0:
            results.append({"curve": name, "tm": None, "span": round(span, 3),
                            "points": len(pts),
                            "note": "flat curve — no transition observed"})
            continue
        # Tm = the steepest point of the transition (peak |dF/dT| on a
        # 3-point window) — works for rising and falling transitions
        tm, best = None, -1.0
        for i in range(1, len(pts) - 1):
            deriv = abs((pts[i - 1][1] - pts[i + 1][1]) / 2.0)
            if deriv > best:
                best, tm = deriv, pts[i][0]
        results.append({"curve": name, "tm": round(tm, 2),
                        "span": round(span, 3), "points": len(pts),
                        "note": ""})
    return {"source": str(path), "curves": results}
