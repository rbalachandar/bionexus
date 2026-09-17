"""ELISA analysis — immunogenicity/serology from plate-reader files.

Parses the same long/grid formats as `labread.read_plate` (any vendor
CSV/XLSX: Molecular Devices, Tecan, ...), then computes:

- cutoff  = mean(blank) + 3 x sd(blank)          (standard serology rule)
- per sample: max OD, endpoint titer (highest dilution with OD >= cutoff,
  when a dilution column is present), and a positive/negative call

Honest scope: a qualitative screen and titer, not a calibrated
concentration — that needs a validated standard curve on the same plate.
"""
from __future__ import annotations

from pathlib import Path

from bionexus.labread import read_plate


def read_elisa(path: str | Path, blank_pattern: str = "blank") -> dict:
    pr = read_plate(path)
    records = [r for r in pr.records if r.get("value") is not None]
    blanks = [float(r["value"]) for r in records
              if r.get("control") or blank_pattern in
              str(r.get("sample", "")).lower()]
    samples = [r for r in records
               if r.get("value") is not None and not r.get("control")
               and blank_pattern not in str(r.get("sample", "")).lower()]
    if blanks:
        mean_b = sum(blanks) / len(blanks)
        sd_b = (sum((v - mean_b) ** 2 for v in blanks)
                / max(1, len(blanks) - 1)) ** 0.5 if len(blanks) > 1 else 0.0
        cutoff = mean_b + 3 * sd_b
    else:
        vals = sorted(float(r["value"]) for r in records)
        cutoff = vals[len(vals) // 2] if vals else 0.0   # no blanks: median

    per_sample: dict[str, list[dict]] = {}
    for r in samples:
        per_sample.setdefault(str(r.get("sample")), []).append(r)

    rows = []
    for sample, rs in sorted(per_sample.items()):
        rs_sorted = sorted(rs, key=lambda r: float(r.get("conc_um") or 0))
        max_od = max(float(r["value"]) for r in rs)
        positive = max_od >= cutoff
        titer = None
        if len(rs) > 1 and any(r.get("conc_um") for r in rs):
            # dilution series: titer = highest dilution still >= cutoff
            above = [float(r["conc_um"]) for r in rs_sorted
                     if float(r["value"]) >= cutoff]
            titer = max(above) if above else None
        rows.append({"sample": sample, "max_od": round(max_od, 3),
                     "titer": titer,
                     "call": "positive" if positive else "negative"})
    return {"source": str(path), "cutoff": round(cutoff, 4),
            "n_blanks": len(blanks), "results": rows,
            "response_unit": pr.response_unit}
