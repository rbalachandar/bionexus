"""PubChem / NCATS qHTS deposit parser (self-normalized curve deposits)."""
from __future__ import annotations

import re
from typing import Any

from bionexus.labread.common import _is_number


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
