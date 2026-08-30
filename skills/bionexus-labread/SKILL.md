---
name: bionexus-labread
description: "Analyze instrument/lab result files automatically: auto-detect vendor export format (long CSV, plate grid, xlsx, imaging evidence), find controls, fit dose-response IC50s, compute Z' assay QC. Use when the user has plate-reader or assay export files to interpret."
license: Apache-2.0
compatibility: "Python 3.10+. pip install bionexuslab (core deps: pydantic). Optional extras: lab-imaging (numpy), bio-rdkit (rdkit)."
allowed-tools: Read Write Edit Bash
metadata:
  version: "0.1.0"
  skill-author: "BioNexus contributors"
---

## Overview

`bionexus.labread.read_plate()` is the zero-configuration reader: point it at a
file from any plate reader / assay export and get an IC50 table plus Z' factor.
Format, header synonyms, and control wells are auto-detected.

## Usage

```sh
bn read results.csv                    # table output
bn read results.csv --html out.html   # shareable summary
```

```python
from bionexus.labread import read_plate
r = read_plate("synergy_export.csv")   # or .xlsx, .tsv, plate-grid
print(r)                               # IC50 table + Z'
```

## What is auto-detected

- Header synonyms: Well/Position, Compound/Sample, Conc/Dose, RFU/OD/Value...
- Vendor metadata header blocks (Biotek/Gen5 style) — skipped
- Control wells: ctrl/control/blank/vehicle/DMSO/negative
- Plate-grid layouts (rows A-P x numbered columns)
- Imaging evidence (.npy well micrographs)

## Honesty rules

- Compounds with no IC50 in-range are reported **right-censored** — do not
  invent values; recommend higher concentrations.
- Single-dose exports cannot yield IC50s — the output says so.
- Z' < 0.3 means the assay window failed; recommend a re-run, not data use.
