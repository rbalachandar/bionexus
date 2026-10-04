"""S-T0.2 — vendor plate-reader ingestion hardening.

Fixtures in tests/data/instruments/ are REAL instrument exports (Tecan
i-control CSV/XLSX, BioTek KC1 flat, Gen5 tab/ISO-8859) plus a real
multi-section plate layout; provenance and licenses in README.md there.
These tests are the contract: vendor dirt must not defeat ingestion, and
what the instrument says (reader, firmware, endpoint cycle) must survive
into the standardized records.
"""
from pathlib import Path

import pytest

from bionexus.labread import (bind_layout, detect_format, extract_instrument_meta,
                              read_plate, _rows_from_csv, _well_columns)

DATA = Path(__file__).parent / "data" / "instruments"
TECAN = DATA / "tecan_ON1.csv"
TECAN_X = DATA / "tecan_ON1.xlsx"
BIOTEK = DATA / "biotek_1steptimer.csv"
GEN5 = DATA / "gen5_demo_input.txt"
LAYOUT = DATA / "plate_layout_96.csv"

pytestmark = pytest.mark.skipif(not TECAN.exists(), reason="vendor fixtures missing")


def test_detect_format_real_vendor_files():
    assert detect_format(TECAN) == "kinetic"
    assert detect_format(BIOTEK) == "kinetic"
    assert detect_format(GEN5) == "kinetic"  # latin-1 + tab must not yield unknown


def test_tecan_icontrol_csv_kinetics():
    r = read_plate(TECAN)
    assert r.format == "kinetic"
    assert len(r.channels) == 2 and r.channels[0] == "OD600:600"
    assert len(r.records) == 192  # 96 wells x 2 channels, endpoint per well
    od = [x for x in r.records if x["channel"] == "OD600:600"]
    assert len(od) == 96
    assert all(0.0 < x["value"] < 1.0 for x in od)  # OD, sane range
    assert r.instrument["application"] == "Tecan i-control"
    assert r.instrument["device"] == "infinite 200Pro"
    assert r.instrument["serial_number"] == "1409002252"
    assert "2014" in r.instrument["firmware"]
    assert r.response_unit == "OD600:600"
    # layout QC is per-channel: no OD/Lum magnitude pooling
    assert set(r.analysis["layout_qc"]) == {"OD600:600", "LUMI:Lum"}
    assert abs(r.analysis["layout_qc"]["OD600:600"]["edge_minus_inner"]) < 0.05


def test_tecan_xlsx_matches_csv_values():
    pytest.importorskip("openpyxl")
    a = read_plate(TECAN)
    b = read_plate(TECAN_X)
    assert b.format == "xlsx-kinetic" and len(b.records) == len(a.records)
    va = {(x["well"], x["channel"]): x["value"] for x in a.records}
    vb = {(x["well"], x["channel"]): x["value"] for x in b.records}
    assert va.keys() == vb.keys()
    for k in list(va)[:40]:
        assert va[k] == pytest.approx(vb[k], rel=1e-6)
    assert b.instrument["device"] == "infinite 200Pro"


def test_biotek_kc1_flat_384_multichannel():
    r = read_plate(BIOTEK)
    assert r.format == "kinetic"
    assert len(r.channels) == 4  # 2 plate passes x (LUM, OD600)
    lum = [x for x in r.records if x["channel"].startswith("LUM_1")]
    assert len(lum) == 384  # full A1..P24 grid from one block group
    assert all(x["value"] >= 0 and x["value"] == x["value"] for x in r.records)
    assert r.instrument["reader_type"] == "Synergy HTX"
    assert r.instrument["software_version"] == "3.12.08"
    assert r.instrument["plate_type"].startswith("Greiner 384")


def test_gen5_latin1_tab_and_missing_tokens():
    rows = _rows_from_csv(GEN5)
    assert max(len(r) for r in rows) > 100  # tab dialect wins over comma confetti
    r = read_plate(GEN5)
    assert r.format == "kinetic"
    assert set(r.channels) == {"tht:440/30,485/20", "abs:500"}
    assert len(r.records) == 288
    assert r.instrument["reader_type"] == "Synergy 2"
    assert r.instrument["plate_type"] == "Corning 384 flat bottom"
    # '?????' tokens become ABSENT wells, never fabricated zeros
    tht = [x for x in r.records if x["channel"] == "tht:440/30,485/20"]
    assert 0 < len(tht) < 384  # partial read range A2..P10: no phantom wells
    assert all(isinstance(x["value"], float) and x["value"] > 0 for x in r.records)


def test_kinetic_cycle_reduction_modes(tmp_path):
    f = tmp_path / "kin.csv"
    hdr = "Time,Tdeg,A" + ",A".join(str(i) for i in range(1, 13))
    f.write_text("LUM:450\n" + hdr + "\n"
                 "0:01,37,1,2,3,4,5,6,7,8,9,10,11,12\n"
                 "0:02,37,11,12,13,14,15,16,17,18,19,20,21\n"
                 "0:03,37,21,22,23,24,25,26,27,28,29,30,31\n")
    by = lambda res: {x["well"]: x["value"] for x in res.records}  # noqa: E731
    last, first, mean = (read_plate(f, cycles=c) for c in ("last", "first", "mean"))
    assert by(last)["A1"] == 21.0 and by(first)["A1"] == 1.0
    assert by(mean)["A1"] == pytest.approx(11.0)


def test_real_multilayer_layout_binds_tecan_plate():
    r = read_plate(TECAN, layout=LAYOUT)
    bound = [x for x in r.records if x["conc_um"] is not None]
    assert len(bound) == 150  # H row + G cols 4-12 are empty in the layout
    rna = [x for x in r.records if x["sample"] == "RNA"]
    assert len(rna) == 36  # rows A-C x 12 doses, first channel
    assert {x["conc_um"] for x in rna} == {
        1e-06, 3.33e-07, 1.11e-07, 3.7e-08, 1.23e-08, 4.12e-09,
        1.37e-09, 4.57e-10, 1.52e-10, 5.08e-11, 1.69e-11, 5.65e-12}
    assert rna[0]["layout"]["protein"] == pytest.approx(5e-08)  # layer preserved
    assert "buffer" in r.analysis["compounds"]
    # second channel never pooled with the first
    assert all("·" in x["sample"] for x in r.records if x["channel"] == "LUMI:Lum")


def test_layout_dialects_headerless_grid_and_long(tmp_path):
    grid = tmp_path / "l.csv"
    grid.write_text("A,1,2,3,4,5,6,7,8,9,10,11,12\n"
                    "B,1,2,3,4,5,6,7,8,9,10,11,12\n")
    plate = tmp_path / "p.csv"
    hdr = "Time,Tdeg,W"
    plate.write_text("LUM:450\n" + "Time,Tdeg," +
                     ",".join(f"{L}{c}" for L in "AB" for c in range(1, 13)) + "\n"
                     "0:01,37," + ",".join("5" for _ in range(24)) + "\n")
    recs = read_plate(plate).records
    assert bind_layout(recs, grid) == 24
    assert [x for x in recs if x["well"] == "B12"][0]["conc_um"] == 12.0

    long_l = tmp_path / "l2.csv"
    long_l.write_text("well,sample,conc_um\nA1,cipro,10\nA2,cipro,1\n"
                      "B1,ntc,\n")
    recs = read_plate(plate).records
    assert bind_layout(recs, long_l) >= 2
    byw = {x["well"]: x for x in recs}
    assert byw["A1"]["sample"] == "cipro" and byw["A1"]["conc_um"] == 10.0
    assert byw["B1"]["control"] is True


def test_meta_scraper_skips_operator_identity():
    meta = extract_instrument_meta(_rows_from_csv(TECAN))
    joined = " ".join(meta.values()).lower()
    assert "vecchion" not in joined and "user" not in joined
    assert meta["date"] == "14.10.2016"


def test_str_line_reports_reader_identity():
    line = str(read_plate(BIOTEK)).splitlines()[0]
    assert "Synergy HTX" in line and "kinetic" in line


LONG_QC = (
    "Well ID,Compound,Conc (uM),RFU\n"
    "A1,blank,,1000\nA2,blank,,1010\nB1,blank,,990\nB2,blank,,1005\n"
    "A3,pos,,100\nA4,pos,,110\nB3,pos,,95\nB4,pos,,105\n"
    "C1,cip,1,550\nC2,cip,1,562\nD1,cip,10,300\nD2,cip,10,311\n"
    "E1,cip,0.1,930\nE2,cip,0.1,941\n"
)


def test_real_zprime_requires_both_control_classes(tmp_path):
    from bionexus.labread import control_class
    assert (control_class("blank"), control_class("pos"), control_class("cip")) == \
           ("neg", "pos", None)
    f = tmp_path / "p.csv"
    f.write_text(LONG_QC)
    r = read_plate(f)
    assert r.z_prime_kind == "real"
    assert r.z_prime is not None and r.z_prime > 0.8  # clean bimodal plate
    assert "Z' " in str(r) and "real" in str(r)
    # without a positive class we must fall back to the labeled heuristic
    f2 = tmp_path / "p2.csv"
    f2.write_text(LONG_QC.replace(",pos,,", ",unk,,")
                  .replace("pos", "unk"))  # 'unk' is not a control id
    r2 = read_plate(f2)
    assert r2.z_prime_kind == "heuristic"
    assert "Z'~" in str(r2)


def test_pct_inhibition_normalization_uses_plate_controls(tmp_path):
    f = tmp_path / "p.csv"
    f.write_text(LONG_QC)
    r = read_plate(f, normalize="pct_inhibition")
    assert r.response_unit == "% inhibition"
    cip1 = [x for x in r.records if x["sample"] == "cip" and x["conc_um"] == 1.0]
    # blank mean 1001.25, pos mean 102.5 -> 550 -> ~50.2 %I
    assert cip1[0]["value"] == pytest.approx(50.2, abs=0.5)
    assert cip1[0]["value_raw"] == 550.0
    assert r.analysis["z_prime_kind"] == "real"  # controls untouched by scaling


def test_pct_inhibition_refuses_without_control_classes(tmp_path):
    f = tmp_path / "p.csv"
    f.write_text("Well ID,Compound,Conc (uM),RFU\n"
                 "A1,cip,1,550\nA2,cip,10,300\n")
    with pytest.raises(ValueError, match="cannot normalize"):
        read_plate(f, normalize="pct_inhibition")


def test_batch_date_lands_on_records_and_export(tmp_path):
    r = read_plate(BIOTEK)
    assert "29/9/2022" in r.batch and "Plate 1" in r.batch
    assert r.records[0]["batch"] == r.batch
    out = r.to_csv(tmp_path / "e.csv")
    head = out.read_text().splitlines()[0]
    assert head == ("well,sample,conc_um,value,control,ic50_um,"
                    "batch,channel,value_raw")


def test_edge_effect_declared_not_gated(tmp_path):
    rows = []
    for ri, L in enumerate("ABCDEFGH"):
        for c in range(1, 13):
            edge = ri in (0, 7) or c in (1, 12)
            rows.append(f"{L}{c},cp{c},{c},"
                        f"{2000 if edge else 1000}")
    f = tmp_path / "edge.csv"
    f.write_text("Well ID,Compound,Conc (uM),RFU\n" + "\n".join(rows) + "\n")
    r = read_plate(f)
    lq = r.analysis["layout_qc"]
    assert lq and lq["edge_minus_inner"] > 500  # hot perimeter declared
    assert lq["n_edge"] + lq["n_inner"] == 96
    assert r.z_prime is None and len(r.analysis["compounds"]) == 12
    # no controls -> no Z' claim at all, but layout metadata still stands
