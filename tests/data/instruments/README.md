# Real vendor plate-reader exports (parser fixtures)

These are **genuine instrument export files from real labs**, used unmodified
as fixtures so `bionexus.labread` is hardened against vendor dirt rather than
an idealized CSV. Retrieved 2026-10-04 from open-source R-package test corpora;
both are MIT-licensed, so redistribution here is permitted with attribution.

| file | instrument / software | provenance | license |
|---|---|---|---|
| `tecan_ON1.csv`, `tecan_ON1.xlsx` | Tecan infinite 200Pro, i-control 1.11 (kinetic OD600 + Luminescence, 96-well, 2016-10-14) | [wellr](https://github.com/BradyAJohnston/wellr) `inst/extdata/` (`tecanON1.*`) | MIT (wellr authors, 2022) |
| `plate_layout_96.csv` | multi-section plate map (conc / sample / protein layers) | [wellr](https://github.com/BradyAJohnston/wellr) `inst/extdata/` | MIT |
| `biotek_1steptimer.csv` | BioTek Synergy HTX, KC1 "1 step timer" flat CSV (kinetic LUM + OD600, 384-well, Fritz Lab 2022-09-29) | [wellr](https://github.com/BradyAJohnston/wellr) `inst/extdata/` (`20220929_1steptimer20.csv`) | MIT |
| `gen5_demo_input.txt` | BioTek Synergy 2, Gen5 v2.06 kinetics `.txt` (tab-delimited, ISO-8859, 384-well) | [gen5helper](https://github.com/ylin00/gen5helper) `inst/extdata/demo_input.txt` | MIT |

Dirt preserved on purpose: giant metadata preambles, trailing blank comma
runs, `?????` missing-value tokens, Windows-1252 bytes (`°` in `Temp. [°C]`),
mixed delimiters, per-channel repeated blocks, and multi-layer layout files.
Operator/user names are deliberately **not** extracted by the metadata
scraper.
