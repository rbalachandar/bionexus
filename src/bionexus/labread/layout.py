"""Plate-layout binding and layout-level QC."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from bionexus.adapters.lab.simulator import parse_concentration_um
from bionexus.labread.common import SYNONYMS, WELL_RE, _header_score, _is_missing, _is_number, _rows_from_csv, is_control, sanitize_label


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
