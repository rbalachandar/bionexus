"""labread — automatic instrument-result ingestion (scientist-facing, stable).

The point of the library: devices and labs produce files; Proef reads them.
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
- Proef imaging evidence (.npy well images via the imaging lab)
- Excel (.xlsx) via the optional openpyxl extra

Control wells are auto-recognized by id: ctrl, control, blank, neg, vehicle,
ntc, standard.
"""
from __future__ import annotations

# curve models / statistics live in fitting.py; re-exported for callers
from proef.fitting import (GRID_CEIL_UM, GRID_FLOOR_UM, GRID_LOG_HI, GRID_LOG_LO, _hill_fit_ic50, _hill_sse, _spearman, classify_curve, fit_ic50, fit_ic50_ci, hill_response, replicate_ci, std_dev)  # noqa: F401
from proef.labread.common import (  # noqa: F401
    CONTROL_IDS, MISSING_TOKENS, POS_CONTROL_IDS, QC_ZPRIME_FLOOR, SYNONYMS, WELL_RE, _CHANNEL_RE, _channel_from_cell, _header_score, _is_missing, _is_number, _rows_from_csv, _well_columns, control_class, is_control, sanitize_label)
from proef.labread.formats import (  # noqa: F401
    _META_KEY, _parse_grid, _parse_kinetic, _parse_long, detect_format, extract_instrument_meta)
from proef.labread.pubchem import (  # noqa: F401
    _ASCENDING, _DESCENDING, _DOSE_NAME, _parse_pubchem, _pubchem_frame, _scale_of, tag_row_unit)
from proef.labread.layout import (  # noqa: F401
    _layout_qc, _layout_sections, bind_layout)
from proef.labread.analysis import (  # noqa: F401
    PlateResult, analyze_records, read_plate, to_pct_inhibition)
