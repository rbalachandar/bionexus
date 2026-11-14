"""Shared constants and cell/row helpers for the plate-reader parsers."""
from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any


WELL_RE = re.compile(r"^([A-P])(\d{1,2})$", re.IGNORECASE)


# QC acceptance floor for the plate-level z'-style heuristic below. Named in
# ONE place because it gates verdicts everywhere (watch, autoloop).
QC_ZPRIME_FLOOR = 0.5


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


def control_class(sample_id: str, overrides: dict[str, str] | None = None
                  ) -> str | None:
    """'pos' | 'neg' | None. A real Z' needs BOTH classes; conflating them
    would print a QC number that means nothing. `overrides` maps explicit
    sample ids to classes — a scientist-confirmed classification wins over
    label sniffing."""
    if overrides:
        o = overrides.get(str(sample_id).strip())
        if o in ("pos", "neg"):
            return o
    s = sample_id.strip().lower().replace(" ", "_")
    if any(s.startswith(c) or s == c for c in POS_CONTROL_IDS):
        return "pos"
    if any(s.startswith(c) or s == c for c in CONTROL_IDS):
        return "neg"
    return None


def sanitize_label(text: Any, cap: int = 60) -> str:
    """Instrument-file labels are UNTRUSTED data: strip control characters,
    collapse whitespace, cap length. They flow into logs, prompts and table
    keys — they must never carry structure or instructions."""
    s = "".join(ch for ch in str(text) if ch.isprintable())
    s = " ".join(s.split())
    return s[:cap]


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


def _is_number(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


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
