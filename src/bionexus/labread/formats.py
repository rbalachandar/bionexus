"""Instrument-export format detection and the long / grid / kinetic parsers."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from bionexus.adapters.lab.simulator import parse_concentration_um
from bionexus.labread.common import WELL_RE, _channel_from_cell, _header_score, _is_missing, _is_number, _rows_from_csv, _well_columns, is_control, sanitize_label


def detect_format(path: Path) -> str:
    """'long' | 'kinetic' | 'grid' | 'npy' | 'xlsx' | 'unknown'."""
    suffix = path.suffix.lower()
    if suffix == ".npy":
        return "npy"
    if suffix == ".xlsx":
        return "xlsx"
    rows = _rows_from_csv(path)
    if not rows:
        return "unknown"
    if rows and rows[0] and rows[0][0].strip() == "PUBCHEM_RESULT_TAG":
        return "pubchem"
    best = 0
    for row in rows[:20]:
        if any(WELL_RE.match(c) for c in row):
            continue  # grid data row
        score, _ = _header_score(row)
        best = max(best, score)
    if best >= 3:
        return "long"
    for row in rows:
        if _well_columns(row):
            return "kinetic"
    # grid: any row where first cell is a plate row letter and rest are numbers
    for row in rows:
        if row and WELL_RE.match(row[0] + "1") and len(row) > 2 and all(
                _is_number(c) for c in row[1:] if c.strip()):
            return "grid"
    return "unknown"


def _parse_long(rows: list[list[str]], unit_out: dict | None = None
                ) -> list[dict[str, Any]]:
    ((_, mapping), header_i) = max(((_header_score(r), i) for i, r in enumerate(rows[:20])),
                                   key=lambda t: (t[0][0], -t[1]))
    if unit_out is not None and "value" in mapping:
        hdr = rows[header_i][mapping["value"]].strip()
        unit_out["unit"] = sanitize_label(hdr, 24) or "instrument response"
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
        if ("conc" in mapping and len(row) > mapping["conc"]
                and row[mapping["conc"]].strip()):
            # blank conc means UNKNOWN, not the simulator's default 10 uM
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


def _parse_kinetic(rows: list[list[str]], unit_out: dict | None = None,
                   cycles: str = "last") -> list[dict[str, Any]]:
    """Flatten kinetic well-column tables to one record per (channel, well).

    cycles='last' is endpoint behaviour (default), 'first' initial rate,
    'mean' the average over reads. A table ends at the next well header or
    channel-label row; all-missing rows inside a table are skipped, not fatal.
    """
    import statistics

    blocks: dict[str, dict[str, list[float]]] = {}
    label = ""
    i = 0
    while i < len(rows):
        cells = [c.strip() for c in rows[i]]
        nonempty = [c for c in cells if c]
        if len(nonempty) == 1 and _channel_from_cell(nonempty[0]) == nonempty[0]:
            label = nonempty[0]
            i += 1
            continue
        cols = _well_columns(rows[i])
        if cols:
            chan = label or next(
                (c for c in cells[:cols[0][0]] if _channel_from_cell(c)),
                "") or "response"
            if chan == "response" and _channel_from_cell(label):
                chan = _channel_from_cell(label)
            wellmap = blocks.setdefault(chan, {})
            j = i + 1
            while j < len(rows):
                r = [c.strip() for c in rows[j]]
                if _well_columns(r):
                    break
                if len([c for c in r if c]) == 1 and _channel_from_cell(
                        next(c for c in r if c)):
                    break  # next block's label row
                present = [(k, w, r[k]) for k, w in cols if k < len(r)
                           and not _is_missing(r[k])]
                if not any(_is_number(v) for _, _, v in present):
                    j += 1
                    continue
                for k, w, v in present:
                    if _is_number(v):
                        wellmap.setdefault(w, []).append(float(v))
                j += 1
            i = j
            continue
        i += 1

    records: list[dict[str, Any]] = []
    for chan, wellmap in blocks.items():
        for w, vs in sorted(wellmap.items()):
            v = (vs[-1] if cycles == "last" else vs[0] if cycles == "first"
                 else statistics.fmean(vs))
            records.append({"well": w, "sample": w, "conc_um": None,
                            "value": v, "control": False, "channel": chan})
    if unit_out is not None and blocks:
        unit_out["unit"] = (sanitize_label(next(iter(blocks)), 24)
                            or "instrument response")
        unit_out["channels"] = list(blocks)
        unit_out["reads"] = max((len(v) for wm in blocks.values()
                                 for v in wm.values()), default=1)
    return records


_META_KEY = re.compile(
    r"^(application|device|firmware|software version|reader type|reader serial"
    r" number|serial number|start time|plate type|plate number|plate"
    r"|experiment file path|protocol file path|date|time)\b[: ]*",
    re.IGNORECASE)


def extract_instrument_meta(rows: list[list[str]]) -> dict[str, str]:
    """Pull reader/device/software/date identity out of the metadata preamble.

    Honest provenance: the instrument model and firmware are part of the
    measurement, the same way 'instrument_version' is for sim labs. Stops at
    the first kinetic well-header row so header cells like 'Time [s]' are
    never mistaken for metadata.
    """
    meta: dict[str, str] = {}
    for row in rows[:120]:
        if _well_columns(row):
            break
        cells = [c.strip() for c in row]
        for i, cell in enumerate(cells):
            if not cell:
                continue
            m = _META_KEY.match(cell)
            if not m:
                continue
            key = m.group(0).lower().strip(" :").replace(" ", "_")
            val = cell[m.end():].strip(" :")
            if not val:
                rest = [c for c in cells[i + 1:] if c]
                val = rest[0] if rest else ""
            if not val or val.startswith("["):
                continue
            if "\\" in val:  # windows paths: keep the file name only
                val = val.split("\\")[-1]
            meta.setdefault(key, sanitize_label(val, 80))
    return meta
