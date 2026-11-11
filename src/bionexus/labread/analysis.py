"""Compound IC50 table + Z', PlateResult and the read_plate entry point."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from bionexus.fitting import GRID_CEIL_UM, GRID_FLOOR_UM, classify_curve, fit_ic50, fit_ic50_ci
from bionexus.labread.common import WELL_RE, _header_score, _is_number, _rows_from_csv, _well_columns, control_class, is_control, sanitize_label
from bionexus.labread.formats import _parse_grid, _parse_kinetic, _parse_long, detect_format, extract_instrument_meta
from bionexus.labread.layout import _layout_qc, bind_layout
from bionexus.labread.pubchem import _parse_pubchem, _pubchem_frame


def to_pct_inhibition(records: list[dict[str, Any]],
                      control_classes: dict[str, str] | None = None) -> bool:
    """Normalize non-control values to % inhibition against BOTH control
    classes: %I = 100*(blank - v)/(blank - positive). Requires >=2 wells of
    each class and the right orientation; otherwise REFUSES (returns False,
    values untouched) — a fabricated normalized unit is worse than raw RFU.
    Keeps r['value_raw'] alongside the transformed r['value']."""
    neg = [r["value"] for r in records if r.get("control")
           and control_class(r["sample"], control_classes) == "neg"]
    pos = [r["value"] for r in records if r.get("control")
           and control_class(r["sample"], control_classes) == "pos"]
    if len(neg) < 2 or len(pos) < 2:
        return False
    b = sum(neg) / len(neg)
    p = sum(pos) / len(pos)
    if not (b > p):  # blanks must out-signal full-inhibition wells
        return False
    for r in records:
        if r.get("control"):
            continue
        r["value_raw"] = r["value"]
        r["value"] = 100.0 * (b - r["value"]) / (b - p)
    return True


def analyze_records(records: list[dict[str, Any]],
                    max_response: float | None = None,
                    control_classes: dict[str, str] | None = None) -> dict[str, Any]:
    """Compound IC50 table + Z' factor. Controls drive Z'; compounds get fits.
    `control_classes`: explicit scientist-confirmed sample->class overrides
    (win over name sniffing)."""
    import math

    by_sample: dict[str, list[tuple[float | None, float]]] = {}
    for r in records:
        by_sample.setdefault(r["sample"], []).append((r["conc_um"], r["value"]))

    ctrl_wells = [r for r in records if r["control"]]
    neg_vals = [r["value"] for r in ctrl_wells
                if control_class(r["sample"], control_classes) == "neg"]
    pos_vals = [r["value"] for r in ctrl_wells
                if control_class(r["sample"], control_classes) == "pos"]
    all_vals = [r["value"] for r in records]

    def _std(v):
        m = sum(v) / len(v)
        return (sum((x - m) ** 2 for x in v) / (len(v) - 1)) ** 0.5 if len(v) > 1 else 0.0

    zp = float("nan")
    zp_kind = None
    if len(neg_vals) >= 2 and len(pos_vals) >= 2:
        # REAL Z' (Zhang 1999): needs both control classes, nothing else.
        denom = abs(sum(neg_vals) / len(neg_vals) - sum(pos_vals) / len(pos_vals))
        if denom > 0:
            zp = max(-1.0, min(1.0,
                               1 - 3 * (_std(neg_vals) + _std(pos_vals)) / denom))
            zp_kind = "real"
    if zp_kind is None and len(ctrl_wells) >= 2:
        ctrl_vals = [r["value"] for r in ctrl_wells]
        sigma_all = _std(all_vals) or 1.0
        spread = abs(sum(all_vals) / len(all_vals) - sum(ctrl_vals) / len(ctrl_vals))
        zp = max(-1.0, min(1.0, 1 - 3 * (_std(ctrl_vals) + 1.0) / (spread + sigma_all)))
        zp_kind = "heuristic"

    compounds: dict[str, Any] = {}
    for sample, vals in by_sample.items():
        if control_class(sample, control_classes) is not None:
            continue
        pts = [(c, v) for c, v in vals if c is not None]
        flagged = max_response is None
        ic50 = fit_ic50(pts, max_response)
        ci = fit_ic50_ci(pts, max_response) if len(pts) >= 3 else None
        if ci:
            ic50 = ci["ic50"]
        # LEFT-censoring: saturated plateau, transition below the measurable
        # window (estimate or CI floor pinned at the grid edge / rounded to
        # 0.0). A number at the floor is a range statement, not an IC50.
        left_censored = bool(ic50 is not None and pts) and (
            ic50 <= GRID_FLOOR_UM * 1.05
            or bool(ci and ci.get("ci_low") is not None
                    and ci["ci_low"] <= GRID_FLOOR_UM * 1.05))
        # RIGHT-censoring at the grid ceiling: an estimate (or CI top)
        # pinned at the search-grid edge is "> range", not a measured IC50.
        at_ceiling = bool(ic50 is not None and pts) and (
            ic50 >= GRID_CEIL_UM * 0.95
            or bool(ci and ci.get("ci_high") is not None
                    and ci["ci_high"] >= GRID_CEIL_UM * 0.95))
        compounds[sample] = {
            "ic50_um": ic50,
            "ic50_ci": (ci["ci_low"], ci["ci_high"]) if ci and ci.get("ci_low")
                        is not None else None,
            "fit_method": (ci or {}).get("method", "linear-interp"),
            # what the curve model actually is: slope fixed at 1, bottom at 0
            "fit_model": ("1-parameter logistic (IC50 only; slope=1, "
                          "bottom=0, top known)" if max_response else
                          "2-parameter logistic (IC50 + top; slope=1, "
                          "bottom=0)"),
            "n_points": len(pts) or len(vals),
            "right_censored": bool(pts) and (ic50 is None or at_ceiling),
            "left_censored": left_censored,
            "fit_quality": "known-max" if max_response else ("observed-max" if pts else "n/a"),
            "flagged_single_dose": not pts,
        }
    return {"z_prime": (round(zp, 3) if zp == zp else None),
            "z_prime_kind": zp_kind,
            "z_prime_note": (
                "real Z' (Zhang): both control classes, >=2 wells each"
                if zp_kind == "real" else
                "approximation: control spread vs global dynamic range with "
                "a constant positive-control term (real Z' needs a positive "
                "control class); QC heuristic, gated at QC_ZPRIME_FLOOR"),
            "controls_detected": len(ctrl_wells),
            "layout_qc": _layout_qc(records),
            "compounds": compounds}


class PlateResult:
    """Scientist-facing result of read_plate: records + fits + QC + table."""

    def __init__(self, path: Path, fmt: str, records: list[dict], analysis: dict,
                 response_unit: str | None = None, instrument: dict | None = None,
                 channels: list[str] | None = None, reads: int | None = None,
                 batch: str = "", regime: dict | None = None):
        self.source = str(path)
        self.format = fmt
        self.records = records
        self.analysis = analysis
        self.instrument = instrument or {}
        self.channels = channels or []
        self.reads = reads
        self.batch = batch
        self.regime = regime
        self.response_unit = response_unit or {
            "npy": "mean pixel intensity", "grid": "well value",
            "xlsx-grid": "well value"}.get(fmt, "instrument response")

    @property
    def z_prime(self) -> float | None:
        return self.analysis["z_prime"]

    @property
    def z_prime_kind(self) -> str | None:
        return self.analysis.get("z_prime_kind")

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
            ic50 = (f"{r['ic50_um']:.2f}" if r["ic50_um"] is not None else
                    ("> range" if r["right_censored"] else "<=0.001"))
            note = ("single-dose" if r["flagged_single_dose"] else
                    "right-censored" if r["right_censored"] else
                    "left-censored (below measurable window)"
                    if r["left_censored"] else r["fit_quality"])
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
            w.writerow(["well", "sample", "conc_um", "value", "control", "ic50_um",
                        "batch", "channel", "value_raw"])
            for r in self.records:
                ic50 = self.analysis["compounds"].get(r["sample"], {}).get("ic50_um", "")
                w.writerow([r["well"], r["sample"], r["conc_um"], r["value"],
                            r["control"], ic50, r.get("batch", ""),
                            r.get("channel", ""), r.get("value_raw", "")])
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
        reader = (self.instrument.get("device")
                  or self.instrument.get("reader_type")
                  or self.instrument.get("application") or "")
        serial = (self.instrument.get("serial_number")
                  or self.instrument.get("reader_serial_number") or "")
        ident = f" | reader: {reader}{' (' + serial + ')' if serial else ''}" if reader else ""
        real = self.z_prime_kind == "real"
        zlabel = (f"Z' {self.z_prime} (real: pos+neg control classes)"
                  if real else f"Z'~ {self.z_prime} (control-spread heuristic)")
        lq = self.analysis.get("layout_qc") or {}
        if "edge_minus_inner" in lq:
            edge = f" | edge-effect {lq['edge_minus_inner']:+.1f}"
        elif lq:  # per-channel layout QC: declare the first channel
            first = next(iter(lq.values()))
            edge = f" | edge-effect {first['edge_minus_inner']:+.1f} ({next(iter(lq))})"
        else:
            edge = ""
        batch = f" | batch: {self.batch}" if self.batch else ""
        if self.regime:
            if self.regime.get("validated"):
                ident += " | regime: pubchem/{} — validated (CS05)".format(
                    self.regime["frame"])
            elif self.regime.get("mode") == "shape-only":
                ident += (" | regime: pubchem/{} — SHAPE-ONLY admits "
                          "(no IC50 claims; CS06)".format(
                              self.regime["frame"]))
            else:
                ident += (" | regime: pubchem/{} — NOT VALIDATED, verdicts "
                          "refused (CS06)".format(self.regime["frame"]))
        head = (f"plate: {self.source} [{self.format}] | "
                f"wells: {len(self.records)} | controls: {self.analysis['controls_detected']} | "
                f"{zlabel}{ident}{batch}{edge}")
        return head + "\n" + self.table()


def read_plate(path: str | Path, max_response: float | None = None,
               layout: str | Path | None = None,
               cycles: str = "last",
               normalize: str | None = None,
               assert_regimes: bool = True) -> PlateResult:
    """Auto-detect, parse, fit and QC an instrument/lab result file.

    layout: optional well->(sample, conc_um) plate-layout file to join onto
    grid/kinetic exports that carry no compound identity (dose-response fits
    become possible). cycles: kinetic reduction per well — 'last' (endpoint),
    'first', or 'mean'. normalize='pct_inhibition': rescale non-control
    values against the plate's own blank + full-inhibition controls.

    Regime gate (CS06's lesson): deposited percent tables are fingerprinted
    for their normalization frame; only frames validated by an external
    reproduction (pubchem/external-reference — CS05, 98.9% agreement,
    zero false actives) get dose-response assertions. Self-normalized
    qHTS deposits REFUSE the surface — no fabricated verdicts, and the
    refusal names its regime. assert_regimes=False is a RESEARCH bypass
    (used by the CS06 negative-result study); never for campaign verdicts.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    fmt = detect_format(path)
    _unit: dict = {}
    instrument: dict = {}
    regime: dict | None = None
    if fmt == "long":
        rows = _rows_from_csv(path)
        records = _parse_long(rows, _unit)
        instrument = extract_instrument_meta(rows)
    elif fmt == "grid":
        rows = _rows_from_csv(path)
        records = _parse_grid(rows)
        instrument = extract_instrument_meta(rows)
    elif fmt == "kinetic":
        rows = _rows_from_csv(path)
        records = _parse_kinetic(rows, _unit, cycles=cycles)
        instrument = extract_instrument_meta(rows)
    elif fmt == "pubchem":
        rows = _rows_from_csv(path)
        records = _parse_pubchem(rows, _unit)   # blind by construction
        frame = _pubchem_frame(records) if records else "unknown"
        instrument = {"deposition": "PubChem submitter table",
                      "n_doses": _unit.get("n_doses")}
        regime = {"dialect": "pubchem", "frame": frame,
                  "validated": frame == "external-reference",
                  "validation_source": ("CS05 (case-studies/05-paper-pilot): "
                                        "98.9% decisive agreement, "
                                        "0 false actives"
                                        if frame == "external-reference"
                                        else "CS06 (case-studies/06-ncats-"
                                             "deposit): FAILED reproduction "
                                             "(rho=0.107)")}
    elif fmt == "npy":
        from bionexus.adapters.lab.imaging import analyze_plate, ImagingPlateReader
        dev = ImagingPlateReader(seed=0)
        plate = {p.stem: {"image": __import__("numpy").load(p), "sample_id": p.stem,
                          "conc_um": None, "artifact": ""}
                 for p in sorted(path.parent.glob("*.npy"))}
        analysis = analyze_plate(plate)
        records = [{"well": w, "sample": sanitize_label(v["sample_id"]),
                    "conc_um": v["conc_um"],
                    "value": v["image"].mean(),
                    "control": is_control(v["sample_id"])}
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
        kinetic_hit = any(_well_columns(r) for r in rows)
        grid_hit = any(r and WELL_RE.match(r[0] + "1") and
                       all(_is_number(c) for c in r[1:] if c.strip())
                       for r in rows)
        instrument = extract_instrument_meta(rows)
        if long_score >= 3:
            records = _parse_long(rows, _unit)
            fmt = "xlsx-long"
        elif kinetic_hit:
            records = _parse_kinetic(rows, _unit, cycles=cycles)
            fmt = "xlsx-kinetic"
        elif grid_hit:
            records = _parse_grid(rows)
            fmt = "xlsx-grid"
        else:
            records = []
            fmt = "xlsx-unknown"
    else:
        raise ValueError(f"unrecognized plate format: {path}")

    if layout is not None:
        bind_layout(records, layout)
    channels = _unit.get("channels") or []
    if len(channels) > 1:  # keep channels as separate samples, never pooled
        first = channels[0]
        for r in records:
            ch = r.get("channel") or first
            if ch != first:
                r["sample"] = f"{r['sample']}·{sanitize_label(ch, 12)}"

    if normalize == "pct_inhibition":
        if not to_pct_inhibition(records):
            raise ValueError(
                "cannot normalize to %inhibition: need >=2 blank (negative-"
                "class) AND >=2 full-inhibition (positive-class) control "
                "wells with blank signal > positive — raw values kept")
        _unit["unit"] = "% inhibition"

    batch = " · ".join(x for x in (
        instrument.get("plate_number") or "",
        instrument.get("date") or "", instrument.get("time") or "") if x)
    for r in records:
        if batch:
            r.setdefault("batch", batch)  # batch/date: first-class covariate

    refuse = regime is not None and not regime["validated"] and assert_regimes
    analysis = analyze_records([] if refuse else records, max_response)
    if refuse:
        analysis["regime_refusal"] = True
        if regime["frame"] == "self-normalized":
            # SHAPE-ONLY ADMISSION (CS06 re-admission ladder): absolute
            # IC50 semantics need an external reference this frame does
            # not have; shape classes are invariant under affine
            # renormalization, so they are the ONLY claims made here.
            bys: dict[str, list[tuple[float, float]]] = {}
            for r in records:
                bys.setdefault(r["sample"], []).append((r["conc_um"],
                                                        r["value"]))
            analysis["shape_only"] = {s: classify_curve(p)
                                      for s, p in bys.items()}
            regime["mode"] = "shape-only"
            regime["note"] = (
                "REGIME SHAPE-ONLY — absolute IC50/verdict claims are "
                "refused on self-normalized deposits (no external "
                "reference); concentration-dependence SHAPE classes "
                "(rise-complete/partial/flat/noisy/falling) with "
                "within-curve midpoints are admitted and labeled. "
                "Never merge shape admits with validated IC50 verdicts.")
        else:  # unknown frame: no claim at all survives
            regime["note"] = (
                "REGIME NOT VALIDATED — no dose-response assertions issued "
                "on this normalization frame (CS06: fixed-reference "
                "crossing rules do not port to unvalidated deposits). "
                "Research mode (assert_regimes=False) is for declared "
                "reproduction studies, never campaign verdicts.")

    analysis_out = analysis
    return PlateResult(path, fmt, records, analysis_out,
                       response_unit=_unit.get("unit"), instrument=instrument,
                       channels=channels, reads=_unit.get("reads"), batch=batch,
                       regime=regime)
