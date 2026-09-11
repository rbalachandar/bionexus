"""labread — automatic instrument-result ingestion (scientist-facing, stable).

The point of the library: devices and labs produce files; BioNexus reads them.
`read_plate(path)` auto-detects the export format, standardizes it, fits
dose-response IC50s, and computes assay QC (Z' factor) — zero configuration.

Supported today:
- long-format CSV/TSV exports (any column order, header synonyms:
  well/position, sample/compound, conc/concentration, value/RFU/OD/...)
- plate-grid exports (rows A-H, columns 1-12 numeric grid, e.g. Biotek/Synergy
  style text exports), with metadata header lines skipped automatically
- BioNexus imaging evidence (.npy well images via the imaging lab)
- Excel (.xlsx) via the optional openpyxl extra

Control wells are auto-recognized by id: ctrl, control, blank, neg, vehicle,
ntc, standard.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any

from bionexus.adapters.lab.simulator import parse_concentration_um

WELL_RE = re.compile(r"^([A-P])(\d{1,2})$", re.IGNORECASE)

SYNONYMS: dict[str, list[str]] = {
    "well": ["well", "position", "pos", "site", "well_id", "wellid"],
    "sample": ["sample", "sample_id", "sampleid", "compound", "compound_id",
               "name", "id", "molecule", "analyte"],
    "conc": ["conc", "concentration", "conc_um", "concentration_um", "conc(uM)",
             "dose", "uM"],
    "value": ["value", "rfu", "od", "abs", "absorbance", "reading", "signal",
              "measurement", "counts", "response", "value_mean", "median"],
}
CONTROL_IDS = {"ctrl", "control", "blank", "neg", "negative", "vehicle",
               "ntc", "standard", "dmso", "medium", "mock"}


def is_control(sample_id: str) -> bool:
    s = sample_id.strip().lower().replace(" ", "_")
    return any(s.startswith(c) or s == c for c in CONTROL_IDS)


# ------------------------------------------------------------------ sniffing

def _rows_from_csv(path: Path) -> list[list[str]]:
    for dialect in (",", "\t", ";"):
        try:
            with path.open(newline="") as f:
                rows = [r for r in csv.reader(f, delimiter=dialect) if any(c.strip() for c in r)]
            if rows and max(len(r) for r in rows) >= 2:
                return rows
        except Exception:
            continue
    return []


def _header_score(header: list[str]) -> tuple[int, dict[str, int]]:
    """How many recognized columns, and their index map."""
    mapping: dict[str, int] = {}
    for i, col in enumerate(header):
        c = col.strip().lower()
        for field, names in SYNONYMS.items():
            if field in mapping:
                continue
            if any(c == n or c.replace(" ", "_") == n or n in c for n in names):
                mapping[field] = i
                break
    return len(mapping), mapping


def detect_format(path: Path) -> str:
    """'long' | 'grid' | 'npy' | 'xlsx' | 'unknown'."""
    suffix = path.suffix.lower()
    if suffix == ".npy":
        return "npy"
    if suffix == ".xlsx":
        return "xlsx"
    rows = _rows_from_csv(path)
    if not rows:
        return "unknown"
    best = 0
    for row in rows[:20]:
        if any(WELL_RE.match(c) for c in row):
            continue  # grid data row
        score, _ = _header_score(row)
        best = max(best, score)
    if best >= 3:
        return "long"
    # grid: any row where first cell is a plate row letter and rest are numbers
    for row in rows:
        if row and WELL_RE.match(row[0] + "1") and len(row) > 2 and all(
                _is_number(c) for c in row[1:] if c.strip()):
            return "grid"
    return "unknown"


def _is_number(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


# ------------------------------------------------------------------- parsing

def _parse_long(rows: list[list[str]]) -> list[dict[str, Any]]:
    ((_, mapping), header_i) = max(((_header_score(r), i) for i, r in enumerate(rows[:20])),
                                   key=lambda t: (t[0][0], -t[1]))
    records: list[dict[str, Any]] = []
    for row in rows[header_i + 1:]:
        if len(row) <= max(mapping.values(), default=0):
            continue
        well = row[mapping["well"]].strip() if "well" in mapping else ""
        if well and not WELL_RE.match(well):
            continue
        sample = (sanitize_label(row[mapping["sample"]]) if "sample" in
                  mapping else (well or ""))
        value = row[mapping["value"]].strip() if "value" in mapping else ""
        if not _is_number(value):
            continue
        conc = None
        if "conc" in mapping:
            conc = parse_concentration_um(row[mapping["conc"]])
        records.append({"well": well.upper(), "sample": sample, "conc_um": conc,
                        "value": float(value), "control": is_control(sample)})
    return records


def _parse_grid(rows: list[list[str]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row in rows:
        m = WELL_RE.match((row[0] + "1"))
        if not m or not row[1:]:
            continue
        row_letter = m.group(1).upper()
        if not all(_is_number(c) for c in row[1:] if c.strip()):
            continue
        for j, cell in enumerate(row[1:], start=1):
            if not cell.strip():
                continue
            records.append({"well": f"{row_letter}{j}", "sample": f"{row_letter}{j}",
                            "conc_um": None, "value": float(cell), "control": False})
    return records


# --------------------------------------------------------------- analysis

def _hill_sse(log_ic50: float, pts: list[tuple[float, float]],
              max_response: float) -> float:
    ic50 = 10 ** log_ic50
    sse = 0.0
    for c, v in pts:
        pred = max_response / (1.0 + ic50 / max(c, 1e-9))
        sse += (v - pred) ** 2
    return sse


def _hill_fit_ic50(pts: list[tuple[float, float]],
                   max_response: float | None) -> float | None:
    """Least-squares Hill fit by grid search, refined once.

    max_response given  -> 2-param fit (IC50 only).
    max_response None   -> 3-param fit: the plateau is ALSO unknown, so we
      grid-search the max multiplier over the observed top response (1x–4x).
      Pretending the observed max is the true max biases IC50 toward the
      potent side — the classic right-censoring trap.
    Returns IC50 in µM or None."""
    import math

    if len(pts) < 2:
        return None
    top = max(v for _, v in pts)
    if top <= 0:
        return None
    lo, hi = -3.0, 2.5                      # 0.001 – ~316 µM
    n = 60
    step = (hi - lo) / n
    if max_response is None:                # 3-param: unknown plateau
        mults = [1.0 + 3.0 * j / 12 for j in range(13)]        # 1x .. 4x
        best = (None, None, float("inf"))
        for m in mults:
            for i in range(n + 1):
                g = lo + step * i
                s = _hill_sse(g, pts, top * m)
                if s < best[2]:
                    best = (g, m, s)
        if best[0] is None:
            return None
        g0, m0, sse0 = best
        for m in [max(1.0, m0 - 0.25 + 0.5 * k / 4) for k in range(5)]:
            for i in range(-8, 9):
                g = g0 + i * step / 8
                s = _hill_sse(g, pts, top * m)
                if s < sse0:
                    sse0, g0, m0 = s, g, m
        return 10 ** g0
    if max_response <= 0:
        return None
    best, best_sse = None, float("inf")
    for i in range(n + 1):
        g = lo + step * i
        s = _hill_sse(g, pts, max_response)
        if s < best_sse:
            best, best_sse = g, s
    for i in range(-8, 9):                   # refine
        g = best + i * step / 8
        s = _hill_sse(g, pts, max_response)
        if s < best_sse:
            best, best_sse = g, s
    if best_sse >= float("inf"):
        return None
    return 10 ** best


def fit_ic50(points: list[tuple[float, float]], max_response: float = 100.0) -> float | None:
    """IC50 from (conc, response) points — Hill fit, with legacy linear
    interpolation as the fallback for sparse data."""
    pts = sorted((c, v) for c, v in points if v is not None)
    if len(pts) < 2:
        return None
    hill = _hill_fit_ic50(pts, max_response)
    if hill is not None and len(pts) >= 3:
        return round(hill, 3)
    if max_response is None and len(pts) >= 3:
        return None  # 3-param declined to fit -> honest censoring, not a guess
    target = max_response / 2.0
    for (c0, v0), (c1, v1) in zip(pts, pts[1:]):
        if min(v0, v1) <= target <= max(v0, v1):
            frac = 0.0 if v1 == v0 else (target - v0) / (v1 - v0)
            return round(c0 + frac * (c1 - c0), 3)
    return None  # right-censored within this concentration range


def fit_ic50_ci(points: list[tuple[float, float]], max_response: float = 100.0,
                n_boot: int = 300, seed: int = 7) -> dict[str, float] | None:
    """Residual bootstrap CI for the Hill IC50.

    Refits on resampled residuals around the fitted curve; returns
    {ic50, ci_low, ci_high} (95%, log-scale percentiles) or None.
    Deterministic given the seed — reproducible verdicts, same as everything
    else in BioNexus.
    """
    import math
    import random

    pts = sorted((c, v) for c, v in points if v is not None)
    if len(pts) < 3 or (max_response is not None and max_response <= 0):
        return None
    base = _hill_fit_ic50(pts, max_response)
    if base is None:
        return None
    rng = random.Random(seed)
    boots: list[float] = []
    if max_response is None:
        # residual bootstrap around the best 3-param fit, at its implied max
        top = max(v for _, v in pts)
        mults = [1.0 + 3.0 * j / 12 for j in range(13)]
        best_m = min(mults, key=lambda m: _hill_sse(math.log10(base), pts,
                                                    top * m))
        fitted = [top * best_m / (1.0 + base / max(c, 1e-9)) for c, _ in pts]
    else:
        fitted = [max_response / (1.0 + base / max(c, 1e-9)) for c, _ in pts]
    residuals = [v - f for (_, v), f in zip(pts, fitted)]
    for _ in range(n_boot):
        sample = [(c, max(0.0, f + rng.choice(residuals)))
                  for (c, _v), f in zip(pts, fitted)]
        est = _hill_fit_ic50(sample, max_response)
        if est:
            boots.append(math.log10(est))
    if len(boots) < 30:                      # too few successful refits
        return {"ic50": round(base, 3), "ci_low": None, "ci_high": None,
                "method": "hill-no-ci"}
    boots.sort()
    q = lambda p: boots[max(0, min(len(boots) - 1, int(p * (len(boots) - 1))))]
    return {"ic50": round(base, 3), "ci_low": round(10 ** q(0.025), 3),
            "ci_high": round(10 ** q(0.975), 3), "method": "hill-bootstrap"}


def z_factor(values: list[float]) -> float:
    import math

    if len(values) < 2:
        return float("nan")
    mean = sum(values) / len(values)
    var = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(var)


def sanitize_label(text: Any, cap: int = 60) -> str:
    """Instrument-file labels are UNTRUSTED data: strip control characters,
    collapse whitespace, cap length. They flow into logs, prompts and table
    keys — they must never carry structure or instructions."""
    s = "".join(ch for ch in str(text) if ch.isprintable())
    s = " ".join(s.split())
    return s[:cap]


def analyze_records(records: list[dict[str, Any]],
                    max_response: float | None = None) -> dict[str, Any]:
    """Compound IC50 table + Z' factor. Controls drive Z'; compounds get fits."""
    import math

    by_sample: dict[str, list[tuple[float | None, float]]] = {}
    for r in records:
        by_sample.setdefault(r["sample"], []).append((r["conc_um"], r["value"]))

    ctrl_wells = [r for r in records if r["control"]]
    ctrl_vals = [r["value"] for r in ctrl_wells]
    # Z' from control spread vs overall dynamic range
    all_vals = [r["value"] for r in records]
    zp = float("nan")
    if len(ctrl_vals) >= 2:
        def _std(v):
            m = sum(v) / len(v)
            return (sum((x - m) ** 2 for x in v) / (len(v) - 1)) ** 0.5 if len(v) > 1 else 0.0
        sigma_all = _std(all_vals) or 1.0
        spread = abs(sum(all_vals) / len(all_vals) - sum(ctrl_vals) / len(ctrl_vals))
        zp = max(-1.0, min(1.0, 1 - 3 * (_std(ctrl_vals) + 1.0) / (spread + sigma_all)))

    compounds: dict[str, Any] = {}
    for sample, vals in by_sample.items():
        if is_control(sample):
            continue
        pts = [(c, v) for c, v in vals if c is not None]
        flagged = max_response is None
        ic50 = fit_ic50(pts, max_response)
        ci = fit_ic50_ci(pts, max_response) if len(pts) >= 3 else None
        if ci:
            ic50 = ci["ic50"]
        compounds[sample] = {
            "ic50_um": ic50,
            "ic50_ci": (ci["ci_low"], ci["ci_high"]) if ci and ci.get("ci_low")
                        is not None else None,
            "fit_method": (ci or {}).get("method", "linear-interp"),
            "n_points": len(pts) or len(vals),
            "right_censored": pts and ic50 is None,
            "fit_quality": "known-max" if max_response else ("observed-max" if pts else "n/a"),
            "flagged_single_dose": not pts,
        }
    return {"z_prime": (round(zp, 3) if zp == zp else None),
            "controls_detected": len(ctrl_wells),
            "compounds": compounds}


# ------------------------------------------------------------- entry point

class PlateResult:
    """Scientist-facing result of read_plate: records + fits + QC + table."""

    def __init__(self, path: Path, fmt: str, records: list[dict], analysis: dict):
        self.source = str(path)
        self.format = fmt
        self.records = records
        self.analysis = analysis

    @property
    def z_prime(self) -> float | None:
        return self.analysis["z_prime"]

    def table(self) -> str:
        compounds = self.analysis["compounds"]
        single_dose = all(r["flagged_single_dose"] for r in compounds.values())
        if single_dose:
            vals = [self._record_value(r) for r in self.records if not r["control"]]
            med = sorted(vals)[len(vals) // 2] if vals else float("nan")
            return (f"single-dose plate: {len(vals)} wells, median signal {med:.1f}\n"
                    "(no concentration series in export — dose-response fit unavailable;\n"
                    " pass a concentration-mapped long-format export for IC50 fits)")
        lines = [f"{'compound':<14} {'IC50 (uM)':>10} {'points':>7}  note"]
        for sample, r in compounds.items():
            ic50 = f"{r['ic50_um']:.2f}" if r["ic50_um"] is not None else (
                "> range" if r["right_censored"] else "-")
            note = ("single-dose" if r["flagged_single_dose"] else
                    "right-censored" if r["right_censored"] else r["fit_quality"])
            lines.append(f"{sample:<14} {ic50:>10} {r['n_points']:>7}  {note}")
        return "\n".join(lines)

    def _record_value(self, r: dict) -> float:
        return r["value"]

    def to_csv(self, path: str | Path) -> Path:
        """Export the standardized records + fitted IC50s for Excel/GraphPad."""
        import csv as _csv
        from pathlib import Path as _P

        out = _P(path)
        with out.open("w", newline="") as f:
            w = _csv.writer(f)
            w.writerow(["well", "sample", "conc_um", "value", "control", "ic50_um"])
            for r in self.records:
                ic50 = self.analysis["compounds"].get(r["sample"], {}).get("ic50_um", "")
                w.writerow([r["well"], r["sample"], r["conc_um"], r["value"],
                            r["control"], ic50])
        return out

    def curve_svg(self, sample: str, width: int = 560, height: int = 340) -> str:
        """Dose-response SVG for one compound (from this plate's records)."""
        from bionexus.plots import dose_response_svg

        pts = [(r["conc_um"], r["value"]) for r in self.records
               if r["sample"] == sample and r.get("conc_um") is not None]
        comp = self.analysis["compounds"].get(sample, {})
        return dose_response_svg(pts, ic50=comp.get("ic50_um"),
                                 ci=comp.get("ic50_ci"),
                                 title=f"{sample} — {self.source}",
                                 width=width, height=height)

    def __str__(self) -> str:
        head = (f"plate: {self.source} [{self.format}] | "
                f"wells: {len(self.records)} | controls: {self.analysis['controls_detected']} | "
                f"Z': {self.z_prime}")
        return head + "\n" + self.table()


def read_plate(path: str | Path, max_response: float | None = None) -> PlateResult:
    """Auto-detect, parse, fit and QC an instrument/lab result file."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    fmt = detect_format(path)
    if fmt == "long":
        records = _parse_long(_rows_from_csv(path))
    elif fmt == "grid":
        records = _parse_grid(_rows_from_csv(path))
    elif fmt == "npy":
        from bionexus.adapters.lab.imaging import analyze_plate, ImagingPlateReader
        dev = ImagingPlateReader(seed=0)
        plate = {p.stem: {"image": __import__("numpy").load(p), "sample_id": p.stem,
                          "conc_um": None, "artifact": ""}
                 for p in sorted(path.parent.glob("*.npy"))}
        analysis = analyze_plate(plate)
        records = [{"well": w, "sample": v["sample_id"], "conc_um": v["conc_um"],
                    "value": v["image"].mean(), "control": is_control(v["sample_id"])}
                   for w, v in plate.items()]
        return PlateResult(path, "npy", records, analysis)
    elif fmt == "xlsx":
        try:
            import openpyxl
        except ImportError as exc:
            raise ImportError("pip install openpyxl to read .xlsx exports") from exc
        ws = openpyxl.load_workbook(path, data_only=True).active
        rows = [[("" if c is None else str(c)) for c in row] for row in ws.iter_rows(values_only=True)]
        # reuse the CSV sniffing on the extracted rows
        long_score = max((_header_score(r)[0] for r in rows[:20]), default=0)
        grid_hit = any(r and WELL_RE.match(r[0] + "1") and
                       all(_is_number(c) for c in r[1:] if c.strip())
                       for r in rows)
        records = (_parse_long(rows) if long_score >= 3 else
                   _parse_grid(rows) if grid_hit else [])
        fmt = "xlsx-long" if long_score >= 3 else "xlsx-grid"
    else:
        raise ValueError(f"unrecognized plate format: {path}")

    analysis = analyze_records(records, max_response)
    return PlateResult(path, fmt, records, analysis)
