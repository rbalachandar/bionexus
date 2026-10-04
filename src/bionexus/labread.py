"""labread — automatic instrument-result ingestion (scientist-facing, stable).

The point of the library: devices and labs produce files; BioNexus reads them.
`read_plate(path)` auto-detects the export format, standardizes it, fits
dose-response IC50s, and computes assay QC (Z' factor) — zero configuration.

Supported today:
- long-format CSV/TSV exports (any column order, header synonyms:
  well/position, sample/compound, conc/concentration, value/RFU/OD/...)
- plate-grid exports (rows A-H, columns 1-12 numeric grid, e.g. Biotek/Synergy
  style text exports), with metadata header lines skipped automatically
- vendor kinetic tables (Tecan i-control CSV/XLSX, BioTek KC1 flat CSV,
  Gen5-style tab text): time/cycle rows x well columns, multi-channel,
  '?????' missing tokens and Windows-1252 bytes tolerated; endpoint
  reduction via cycles='last'|'first'|'mean'
- optional plate-layout join (well -> sample/conc) so bare grids get
  dose-response fits: read_plate(path, layout=...)
- instrument identity metadata (reader, device, firmware, date) extracted
  from the preamble for honest provenance: PlateResult.instrument
- native PubChem deposited tables (two dialects: meta-row dose ladders and
  header-embedded doses; %inhibition or %Activity polarity, flips
  disclosed) — with a REGIME GATE: the normalization frame is fingerprinted
  and only externally-validated frames assert verdicts (CS05 validated
  external-reference; self-normalized qHTS tables refuse the surface, per
  CS06's published negative result). Records always stay standardized.
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

# QC acceptance floor for the plate-level z'-style heuristic below. Named in
# ONE place because it gates verdicts everywhere (watch, autoloop).
QC_ZPRIME_FLOOR = 0.5


def replicate_ci(values: list[float | None], seed: int = 7,
                 n_boot: int = 200) -> tuple[float, float] | None:
    """Bootstrap CI (95%) of the MEAN over replicate well readings at one
    dose. This is how a property metric (potency_pct, tensile MPa, t_half)
    gets an interval: well-level variance, same abstention rule as the
    Hill IC50. Returns None below 3 usable wells — a single reading has
    no measurable spread, and inventing one is not honesty."""
    vals = [v for v in values if isinstance(v, (int, float))]
    if len(vals) < 3:
        return None
    from bionexus.benchmark import bootstrap_ci
    lo, hi = bootstrap_ci([float(v) for v in vals], n_boot=n_boot, seed=seed)
    return (lo, hi)

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
POS_CONTROL_IDS = {"pos", "positive", "max_inhibition", "full_inhibition",
                   "dead", "killed"}


def is_control(sample_id: str) -> bool:
    return control_class(sample_id) is not None


def control_class(sample_id: str) -> str | None:
    """'pos' | 'neg' | None. A real Z' needs BOTH classes; conflating them
    would print a QC number that means nothing."""
    s = sample_id.strip().lower().replace(" ", "_")
    if any(s.startswith(c) or s == c for c in POS_CONTROL_IDS):
        return "pos"
    if any(s.startswith(c) or s == c for c in CONTROL_IDS):
        return "neg"
    return None

# ------------------------------------------------------------------ sniffing

def _rows_from_csv(path: Path) -> list[list[str]]:
    # vendor exports are frequently Windows-1252/latin-1 (°, µ in metadata);
    # a strict utf-8 read of e.g. a BioTek Gen5 .txt throws and the file is
    # mislabeled 'unknown'. And the delimiter must be CHOSEN, not guessed
    # first-come: a tab-delimited Gen5 line containing 'tht:440/30,485/20'
    # 'succeeds' under the comma dialect as width-3 confetti. Pick the
    # (encoding, delimiter) whose MEDIAN row width is largest.
    best_rows: list[list[str]] = []
    best_width = 0
    for encoding in ("utf-8-sig", "latin-1"):
        for dialect in (",", "\t", ";"):
            try:
                with path.open(newline="", encoding=encoding) as f:
                    rows = [r for r in csv.reader(f, delimiter=dialect)
                            if any(c.strip() for c in r)]
            except (OSError, UnicodeDecodeError, csv.Error):
                continue
            if not rows:
                continue
            widths = sorted(len(r) for r in rows)
            median = widths[len(widths) // 2]
            if median > best_width:
                best_rows, best_width = rows, median
    return best_rows if best_width >= 2 else []


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


def _is_number(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


# ------------------------------------------------------------------- parsing

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


# ------------------------------------------------------- vendor kinetics
# Real instrument exports (Tecan i-control, BioTek KC1 flat, Gen5 .txt) are
# kinetic tables: one ROW per read (time/cycle/temperature), one COLUMN per
# well (A1..H12 or A1..P24), preceded by a big metadata preamble and repeated
# per channel (e.g. OD600 + Luminescence). Missing wells are '?????' tokens
# and files carry Windows-1252 bytes. This section exists so those parse
# without hand-editing the export.

MISSING_TOKENS = {"?", "??", "???", "?????", "----", "---", "*", "n/a", "na",
                  "nan", "none", "null", "over range", "error", "overflow"}
_CHANNEL_RE = re.compile(r"[A-Za-z0-9_\-]{2,24}:[A-Za-z0-9_/,\.\-]{2,24}")


def _is_missing(cell: str) -> bool:
    c = cell.strip().lower()
    return (not c or c in MISSING_TOKENS or set(c) <= {"?", "-"})


def _channel_from_cell(cell: str) -> str:
    m = _CHANNEL_RE.search(cell)
    return m.group(0) if m else ""


def _well_columns(row: list[str]) -> list[tuple[int, str]]:
    """Longest contiguous run (>=8) of well-name cells: the kinetic header.

    Returns (column_index, WELL) pairs. Column-major layout lets us map data
    rows back to wells even when Time/Temp/Cycle prefix columns vary — and
    ignores trailing summary columns like Gen5's 'Max V [...]'.
    """
    hits = [(i, c.strip().upper()) for i, c in enumerate(row)
            if WELL_RE.match(c.strip())]
    best: list[tuple[int, str]] = []
    cur: list[tuple[int, str]] = []
    for item in hits:
        if cur and item[0] == cur[-1][0] + 1:
            cur.append(item)
        else:
            if len(cur) > len(best):
                best = cur
            cur = [item]
    if len(cur) > len(best):
        best = cur
    return best if len(best) >= 8 else []


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
# deliberately NOT extracted: operator/user names — instrument identity is
# part of the measurement, the technician's login is not.


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


def _layout_sections(rows: list[list[str]]):
    """Parse a possibly multi-section layout grid.

    Real plate maps (wellr's own example included) stack named sections:
    'conc' (dose per well), 'sample' (what sits in the well), 'protein', ...
    each introduced by a header row like 'conc,1,2,...'. Returns
    (conc_map, sample_map, extras) where extras keeps the other layers by
    section name — nothing is silently dropped.
    """
    conc_map: dict[str, float | None] = {}
    sample_map: dict[str, str] = {}
    extras: dict[str, dict[str, Any]] = {}
    section = None
    for row in rows:
        cells = [c.strip() for c in row]
        if not cells or not cells[0]:
            continue
        c0 = cells[0].lower()
        if (not WELL_RE.match(cells[0] + "1") and len(cells[0]) > 1
                and len(cells) > 1 and cells[1] == "1"):
            if any(c0 == n or c0 in n for n in SYNONYMS["conc"]):
                section = "conc"
            elif any(c0 == n or c0 in n for n in SYNONYMS["sample"]):
                section = "sample"
            else:
                section = sanitize_label(c0, 24)
                extras.setdefault(section, {})
            continue
        m = WELL_RE.match(cells[0] + "1")
        if not m or len(cells[0]) > 2:
            continue
        letter = cells[0].upper()
        for j, cell in enumerate(cells[1:], start=1):
            if _is_missing(cell):
                continue
            well = f"{letter}{j}"
            if section == "conc":
                conc_map[well] = (parse_concentration_um(cell)
                                  if _is_number(cell) else None)
            elif section == "sample":
                sample_map[well] = (sanitize_label(cell) if not _is_number(cell)
                                    else sanitize_label(f"{c0} {cell}"))
            elif section:
                extras[section][well] = (float(cell) if _is_number(cell)
                                         else sanitize_label(cell, 40))
            elif _is_number(cell):
                conc_map[well] = float(cell)  # headerless single conc grid
            else:
                sample_map[well] = sanitize_label(cell)
    return conc_map, sample_map, extras


def bind_layout(records: list[dict[str, Any]], layout: str | Path) -> int:
    """Attach well -> (sample, conc_um) from a plate-layout file.

    Two layout dialects: a grid ('conc,1..12' header, one lettered row per
    plate row; possibly several named sections stacked — dose, sample,
    reagent), or long ('well,sample,conc_um'). Empty layout cells mean
    'no compound in that well' and leave the record unmapped. Extra
    categorical layers land on each record as r['layout'].
    Returns the number of wells bound (conc or sample).
    """
    path = Path(layout)
    rows = _rows_from_csv(path)
    if not rows:
        raise ValueError(f"unreadable layout file: {path}")
    dose_map: dict[str, float | None] = {}
    name_map: dict[str, str] = {}
    extra_maps: dict[str, dict[str, Any]] = {}

    long_score = max((_header_score(r)[0] for r in rows[:10]), default=0)
    if long_score >= 2:  # long layout: well + conc (+ optional sample)
        ((_, mapping), header_i) = max(
            ((_header_score(r), i) for i, r in enumerate(rows[:10])),
            key=lambda t: (t[0][0], -t[1]))
        for row in rows[header_i + 1:]:
            well = (row[mapping["well"]].strip().upper()
                    if "well" in mapping and len(row) > mapping["well"] else "")
            if not WELL_RE.match(well):
                continue
            conc = (parse_concentration_um(row[mapping["conc"]])
                    if "conc" in mapping and len(row) > mapping["conc"]
                    and row[mapping["conc"]].strip() else None)
            dose_map[well] = conc
            if "sample" in mapping and len(row) > mapping["sample"]:
                name_map[well] = sanitize_label(row[mapping["sample"]])
    else:
        dose_map, name_map, extra_maps = _layout_sections(rows)

    bound = 0
    for r in records:
        w = r["well"].upper()
        hit = False
        if w in dose_map:
            r["conc_um"] = dose_map[w]
            hit = True
        if w in name_map:
            r["sample"] = name_map[w]
            hit = True
        for sec, m in extra_maps.items():
            if w in m:
                r.setdefault("layout", {})[sec] = m[w]
                hit = True
        bound += hit
    for r in records:
        r["control"] = is_control(str(r["sample"]))
    return bound


_DOSE_NAME = re.compile(r"at\s+([0-9][0-9.eE+-]*)\s*(nM|uM|\u00b5M)", re.IGNORECASE)
_ASCENDING = ("inhibit",)
_DESCENDING = ("activity", "response", "control", "% ctrl")


def _scale_of(name: str) -> str:
    low = name.lower()
    if any(k in low for k in _ASCENDING):
        return "inhibition"      # rises with dose: our native effect scale
    if any(k in low for k in _DESCENDING):
        return "activity"        # falls with dose: flip to 100 - x
    return "unknown"


def _parse_pubchem(rows: list[list[str]],
                   unit_out: dict | None = None) -> list[dict[str, Any]]:
    """Parse a PubChem deposited assay table (the submitter's own upload,
    REST-exported) into standardized records — STRUCTURALLY BLIND: only
    identity columns (SID/CID/SMILES) and the raw percentage value columns
    are read; PUBCHEM_ACTIVITY_OUTCOME and the submitter's IC50/Hill/Fit
    columns are never touched here. Scoring against those answer-key
    columns must happen downstream, explicitly.

    Two deposition dialects (both real, both seen in the wild):
      A. Jacobs/MLPCN style — dose ladder in `RESULT_ATTR_CONC_*` meta
         rows; the REST header may truncate the value-column NAMES, so
         the meta row is the truth (unit suffix in the tag: MICROMOL or
         NANOMOLAR).
      B. NCATS qHTS style — doses embedded in header names
         ('Activity at 0.233 uM'), no usable meta rows, and on a
         PERCENT-**ACTIVITY** scale (decreasing for inhibitors, often
         negative past full inhibition) — detected by the column name and
         flipped onto the ascending effect scale, with the flip DISCLOSED
         in unit_out['scale'].
    Scale polarity by name: 'Inhibit*' -> as-is; 'Activity/Response/
    Control*' -> 100 - x. Unknown-polarity columns are refused (no silent
    inversion — a mis-signed curve is worse than none).
    """
    header = [c.strip() for c in rows[0]]

    def col(*names: str) -> int:
        for n in names:
            if n in header:
                return header.index(n)
        return -1

    sid_i, cid_i, smi_i = col("PUBCHEM_SID"), col("PUBCHEM_CID"), \
        col("PUBCHEM_EXT_DATASOURCE_SMILES", "PUBCHEM_EXT_DATASOURCE_STRUCTures")
    conc_row = unit_row = None
    for r in rows:
        if not r:
            continue
        tag = r[0].strip()
        if tag.startswith("RESULT_ATTR_CONC"):
            if conc_row is None or tag.endswith("MICROMOL"):
                conc_row = r            # micromolar preferred if mixed
        elif tag == "RESULT_UNIT" and unit_row is None:
            unit_row = r
    pcols: list[tuple[int, float, str]] = []      # (col, uM, scale-name)
    if conc_row is not None and any(_is_number(c) for c in conc_row[1:]):
        nano = "NANO" in conc_row[0].upper()
        for j, c in enumerate(conc_row):
            if j == 0 or not c.strip() or not _is_number(c):
                continue
            if (unit_row is not None and j < len(unit_row)
                    and unit_row[j].strip().upper().startswith("PERCENT")):
                pcols.append((j, float(c) / 1000.0 if nano else float(c),
                              _scale_of(header[j] if j < len(header) else "")))
    else:  # dialect B: doses in the header names themselves
        for j, name in enumerate(header):
            m = _DOSE_NAME.search(name)
            if m:
                um = float(m.group(1))
                if m.group(2).lower() == "nm":
                    um /= 1000.0
                pcols.append((j, um, _scale_of(name)))
    if not pcols or smi_i < 0:
        return []
    # dialect A's REST header truncation leaves SOME value columns unnamed
    # (scale unknown from the name). They belong to the same measured family
    # as the named ones — inherit a single consistent named scale; refuse if
    # the named columns themselves disagree or none are nameable.
    named = {s for _, _, s in pcols if s != "unknown"}
    if len(named) > 1:
        if unit_out is not None:
            unit_out["refused"] = ("mixed scale polarity in one deposition: "
                                   + ", ".join(sorted(named)))
        return []
    if len(named) == 1:
        inherit = named.pop()
        pcols = [(j, c, inherit if s == "unknown" else s)
                 for j, c, s in pcols]
    unknown = {s for _, _, s in pcols if s == "unknown"}
    if unknown:  # wholly anonymous percent columns: no safe polarity
        if unit_out is not None:
            unit_out["refused"] = ("value columns without recognizable "
                                   "scale polarity: " + ", ".join(sorted(unknown)))
        return []
    scales = sorted({s for _, _, s in pcols})
    if unit_out is not None:
        flipped = [s for s in scales if s == "activity"]
        unit_out["unit"] = ("% inhibition (ascending effect scale"
                           + ("; activity columns flipped: 100 - x)"
                              if flipped else ")"))
        unit_out["scale"] = "+".join(scales)
        unit_out["n_doses"] = len(pcols)
    records: list[dict[str, Any]] = []
    for r in rows:
        if not r or not r[0].strip().isdigit():
            continue
        sid = r[sid_i].strip() if 0 <= sid_i < len(r) else ""
        cid = r[cid_i].strip() if 0 <= cid_i < len(r) else ""
        smi = r[smi_i].strip() if smi_i < len(r) else ""
        name = f"SID{sid}" if sid else (f"CID{cid}" if cid else smi[:16])
        for j, um, scale in pcols:
            if j >= len(r) or not _is_number(r[j]):
                continue          # sparse curves: unfilled wells stay absent
            raw = float(r[j])
            inh = 100.0 - raw if scale == "activity" else raw
            records.append({"well": "", "sample": name, "conc_um": um,
                            "value": round(inh, 3), "control": False,
                            "inhibition_pct": round(inh, 3), "smiles": smi,
                            "cid": cid})
    return records


def tag_row_unit(tag: str) -> str:
    return "nano" if "NANO" in tag.upper() else "micro"


def _pubchem_frame(records: list[dict[str, Any]]) -> str:
    """Fingerprint the normalization frame of a deposited percent table.

    External-reference deposits (Jacobs/MLPCN style; validated by CS05
    against the lab's own calls) start most compounds at the ZERO end of
    the effect scale: the lowest measured dose of each curve reads ~0%
    inhibition (compound present, enzyme still running).
    Internally self-normalized deposits (NCATS qHTS style; CS06 showed a
    fixed 50%-crossing rule CANNOT port to them) start at the collapsed
    assay floor — most curves' lowest dose already sits at/above full
    effect because the plate's own DMSO/bottom references were divided
    out before deposition.

    Heuristic (documented, deliberately blunt): median lowest-dose
    response > 55 — or > 50% of compounds flat-saturated (range < 25 with
    min > 75) — is a self-normalized fingerprint. This is a refusal
    trigger, not a claim: 'unknown' behaves like self-normalized.
    """
    by: dict[str, list[tuple[float, float]]] = {}
    for r in records:
        by.setdefault(r["sample"], []).append((r["conc_um"], r["value"]))
    firsts, flat = [], 0
    for pts in by.values():
        pts = sorted(pts)
        if len(pts) >= 3:
            firsts.append(pts[0][1])
            vals = [v for _, v in pts]
            if min(vals) > 75 and max(vals) - min(vals) < 25:
                flat += 1
    if not firsts:
        return "unknown"
    firsts.sort()
    med = firsts[len(firsts) // 2]
    if med > 55 or flat / len(firsts) > 0.5:
        return "self-normalized"
    return "external-reference"


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


def std_dev(values: list[float]) -> float:
    """Sample standard deviation (n-1 denominator). NOT a Z'-factor —
    the old name invited that mistake; the plate QC heuristic lives in
    analyze_records and is labeled there."""
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


def _layout_qc(records: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Edge/column effects from WELL GEOMETRY of non-control wells.

    Declared, never silently corrected and never gated: a hot perimeter or a
    drifting column is plate metadata the verdict should know about. Edges
    are inferred from the observed grid (A../..last read row, col 1..last
    read col), so partial reads get a conservative 'outer ring' definition.
    Multi-channel plates get one QC dict PER CHANNEL (pooling OD magnitudes
    with luminescence would produce a meaningless statistic).
    """
    groups: dict[str, list] = {}
    for r in records:
        if r.get("control"):
            continue
        m = WELL_RE.match(str(r.get("well", "")))
        if m:
            chan = r.get("channel") or ""
            groups.setdefault(chan, []).append(
                (ord(m.group(1).upper()) - 65, int(m.group(2)), r["value"]))

    def _qc(pts) -> dict[str, Any] | None:
        if len(pts) < 24:
            return None
        max_r = max(p[0] for p in pts)
        max_c = max(p[1] for p in pts)
        edge = [v for ri, ci, v in pts if ri in (0, max_r) or ci in (1, max_c)]
        inner = [v for ri, ci, v in pts
                 if ri not in (0, max_r) and ci not in (1, max_c)]
        if not edge or not inner:
            return None
        colmeans: dict[int, list[float]] = {}
        for _, ci, v in pts:
            colmeans.setdefault(ci, []).append(v)
        drift = None
        if len(colmeans) >= 3:
            ms = [sum(x) / len(x) for x in colmeans.values()]
            drift = round(max(ms) - min(ms), 6)
        return {"n_edge": len(edge), "n_inner": len(inner),
                "edge_minus_inner": round(
                    sum(edge) / len(edge) - sum(inner) / len(inner), 6),
                "column_drift": drift}

    qcs = {chan: _qc(pts) for chan, pts in groups.items()}
    qcs = {k: v for k, v in qcs.items() if v is not None}
    if not qcs:
        return None
    if len(qcs) == 1:
        return next(iter(qcs.values()))
    return qcs


def to_pct_inhibition(records: list[dict[str, Any]]) -> bool:
    """Normalize non-control values to % inhibition against BOTH control
    classes: %I = 100*(blank - v)/(blank - positive). Requires >=2 wells of
    each class and the right orientation; otherwise REFUSES (returns False,
    values untouched) — a fabricated normalized unit is worse than raw RFU.
    Keeps r['value_raw'] alongside the transformed r['value']."""
    neg = [r["value"] for r in records if r.get("control")
           and control_class(r["sample"]) == "neg"]
    pos = [r["value"] for r in records if r.get("control")
           and control_class(r["sample"]) == "pos"]
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
                    max_response: float | None = None) -> dict[str, Any]:
    """Compound IC50 table + Z' factor. Controls drive Z'; compounds get fits."""
    import math

    by_sample: dict[str, list[tuple[float | None, float]]] = {}
    for r in records:
        by_sample.setdefault(r["sample"], []).append((r["conc_um"], r["value"]))

    ctrl_wells = [r for r in records if r["control"]]
    neg_vals = [r["value"] for r in ctrl_wells
                if control_class(r["sample"]) == "neg"]
    pos_vals = [r["value"] for r in ctrl_wells
                if control_class(r["sample"]) == "pos"]
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

    GRID_FLOOR_UM = 10 ** -3    # mirrors _hill_fit_ic50's lower grid bound
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
        # LEFT-censoring: saturated plateau, transition below the measurable
        # window (estimate or CI floor pinned at the grid edge / rounded to
        # 0.0). A number at the floor is a range statement, not an IC50.
        left_censored = bool(ic50 is not None and pts) and (
            ic50 <= GRID_FLOOR_UM * 1.05
            or bool(ci and ci.get("ci_low") is not None
                    and ci["ci_low"] <= GRID_FLOOR_UM * 1.05))
        compounds[sample] = {
            "ic50_um": ic50,
            "ic50_ci": (ci["ci_low"], ci["ci_high"]) if ci and ci.get("ci_low")
                        is not None else None,
            "fit_method": (ci or {}).get("method", "linear-interp"),
            "n_points": len(pts) or len(vals),
            "right_censored": pts and ic50 is None,
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


# ------------------------------------------------------------- entry point

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
            ident += (" | regime: pubchem/{} — validated ({})".format(
                self.regime["frame"],
                "CS05") if self.regime.get("validated") else
                " | regime: pubchem/{} — NOT VALIDATED, verdicts refused "
                "(CS06)".format(self.regime["frame"]))
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
        regime["note"] = (
            "REGIME NOT VALIDATED — no dose-response assertions issued on this "
            "normalization frame (CS06: fixed-reference crossing rules do not "
            "port to self-normalized qHTS deposits). Records remain faithfully "
            "standardized; research mode (assert_regimes=False) is for "
            "declared reproduction studies, never campaign verdicts.")

    analysis_out = analysis
    return PlateResult(path, fmt, records, analysis_out,
                       response_unit=_unit.get("unit"), instrument=instrument,
                       channels=channels, reads=_unit.get("reads"), batch=batch,
                       regime=regime)
