"""Plate-assay analysis profile — the first profile over the generic seam.

Pins the honesty rules at the profile boundary: preview never verdicts,
CI-straddle abstains, no-CI never decides, censoring is a no_call with a
reason, the regime gate refuses absolute claims, control overrides work,
and identical bytes+config produce identical payloads.
"""
from pathlib import Path

import pytest

from bionexus import experiment_analysis as EA
from bionexus.analysis_profiles import plate_assay as PA

# long-format plate: compounds x doses on the ascending %inhibition scale
# + blank/pos control classes. C1 is cleanly potent (~1 uM); BORD's IC50
# sits ON a 10 uM gate (CI straddles by construction); NOCI has too few
# points for a bootstrap CI; WEAK never crosses 50% (right-censored).
LONG = "\n".join([
    "well,sample,conc_um,value",
    "A1,blank,0,5", "A2,blank,0,5",
    "A3,pos,0,95", "A4,pos,0,95",
    "B1,C1,0.1,10", "B2,C1,1,50", "B3,C1,10,90",
    "C1,BORD,3,15", "C2,BORD,10,45", "C3,BORD,30,85",
    "D1,NOCI,5,40", "D2,NOCI,50,80",
]) + "\n"

GATE = {"metric": "ic50_um", "direction": "min", "threshold": 10.0,
        "max_response": 100.0}


@pytest.fixture()
def plate(tmp_path) -> Path:
    f = tmp_path / "plate.csv"
    f.write_text(LONG)
    return f


# ------------------------------------------------------------------ preview

def test_preview_reports_interpretation_without_verdicts(plate):
    p = EA.preview("plate_assay", plate, GATE)
    assert p["profile"] == "plate_assay"
    assert p["state"] == "preview_ready"
    assert "compounds" not in p and "calls" not in p  # NO fits published
    assert p["z_prime_kind"] == "real"
    assert set(p["samples"]) >= {"C1", "BORD", "NOCI"}
    assert p["has_doses"] and p["evidence_origin"] == "measured"


def test_preview_warns_when_no_controls(tmp_path):
    f = tmp_path / "p.csv"
    f.write_text("well,sample,conc_um,value\nA1,C1,1,5\nA2,C1,10,3\n")
    p = EA.preview("plate_assay", f, {})
    assert any(d["code"] == "no_controls" for d in p["diagnostics"])
    assert "control_classes" in p["needs_confirmation"]


def test_preview_holds_on_unknown_control_ids(plate):
    cfg = {**GATE, "positive_controls": ["ghost"]}
    p = EA.preview("plate_assay", plate, cfg)
    assert p["state"] == "needs_mapping"
    assert any(d["code"] == "unknown_control_ids" for d in p["diagnostics"])


def test_preview_unsupported_regime_state(tmp_path):
    f = tmp_path / "ncats.csv"
    f.write_text(
        "PUBCHEM_RESULT_TAG,PUBCHEM_SID,PUBCHEM_CID,"
        "PUBCHEM_EXT_DATASOURCE_SMILES,PUBCHEM_ACTIVITY_OUTCOME,"
        "Activity at 0.001 uM,Activity at 0.01 uM,Activity at 1 uM,"
        "Activity at 10 uM,Activity at 100 uM\n"
        "1,101,1,CCO,Active,,2,1.5,0.4,-0.6,-1.2\n"
        "2,102,2,CCN,Active,,1,0,-1,2,0.5\n")
    p = EA.preview("plate_assay", f, {})
    assert p["state"] == "unsupported_regime"
    assert p["regime"]["frame"] == "self-normalized"
    assert p["evidence_origin"] == "measured"  # origin is config-declared


# ------------------------------------------------------------------ analyze

def test_analyze_deterministic_and_structured(plate):
    a = EA.analyze("plate_assay", plate, GATE, source_sha256="deadbeef")
    b = EA.analyze("plate_assay", plate, GATE, source_sha256="deadbeef")
    assert a == b  # same bytes + config -> identical payload
    assert a["state"] == "analyzed"
    assert a["source_sha256"] == "deadbeef"
    assert a["threshold_registered"] is True
    assert a["profile_version"] == PA.PROFILE_VERSION
    assert a["compounds"] and a["calls"]


def test_analyze_without_threshold_emits_no_calls(plate):
    a = EA.analyze("plate_assay", plate, {})
    assert a["threshold_registered"] is False
    assert a["calls"] == []
    assert a["compounds"]["C1"]["ic50_um"] is not None  # estimates still given


def test_ci_straddling_gate_abstains(plate):
    a = EA.analyze("plate_assay", plate, GATE)
    by = {c["entity"]: c for c in a["calls"]}
    # BORD sits on a plateau around the gate: its CI straddles 10 uM
    assert by["BORD"]["call"] == "inconclusive"
    assert "straddles" in by["BORD"]["reason"]


def test_clean_hit_validates_with_ci(plate):
    a = EA.analyze("plate_assay", plate, GATE)
    by = {c["entity"]: c for c in a["calls"]}
    assert by["C1"]["call"] == "validated"
    assert by["C1"]["ci"] is not None and None not in by["C1"]["ci"]


def test_sparse_fit_without_ci_cannot_decide(plate):
    a = EA.analyze("plate_assay", plate, GATE)
    by = {c["entity"]: c for c in a["calls"]}
    # NOCI has 2 points -> no bootstrap CI -> inconclusive, never decisive
    assert by["NOCI"]["call"] == "inconclusive"
    assert "usable CI" in by["NOCI"]["reason"]


def test_right_censored_is_no_call_not_invalidated(tmp_path):
    f = tmp_path / "weak.csv"
    f.write_text("well,sample,conc_um,value\n"
                 "A1,blank,0,5\nA2,blank,0,5\n"
                 "A3,pos,0,95\nA4,pos,0,95\n"
                 "B1,WEAK,1,5\nB2,WEAK,10,6\nB3,WEAK,100,7\n")
    a = EA.analyze("plate_assay", f, GATE)
    by = {c["entity"]: c for c in a["calls"]}
    assert by["WEAK"]["call"] == "no_call"
    assert "inside the tested window" in by["WEAK"]["reason"]


def test_regime_refusal_blocks_all_calls(tmp_path):
    f = tmp_path / "ncats.csv"
    f.write_text(
        "PUBCHEM_RESULT_TAG,PUBCHEM_SID,PUBCHEM_CID,"
        "PUBCHEM_EXT_DATASOURCE_SMILES,PUBCHEM_ACTIVITY_OUTCOME,"
        "Activity at 0.001 uM,Activity at 0.01 uM,Activity at 1 uM,"
        "Activity at 10 uM,Activity at 100 uM\n"
        "1,101,1,CCO,Active,,2,1.5,0.4,-0.6,-1.2\n"
        "2,102,2,CCN,Active,,1,0,-1,2,0.5\n")
    a = EA.analyze("plate_assay", f, GATE)
    assert a["regime_refused"] is True
    assert a["state"] == "unsupported_regime"
    assert a["calls"] == []            # NO absolute claims on this frame
    assert a["shape_only"], "shape admits still present"
    assert a["compounds"] == {}


def test_control_overrides_reclassify_and_reanalyze(tmp_path):
    # controls named something the sniffer would miss
    f = tmp_path / "p.csv"
    f.write_text("well,sample,conc_um,value\n"
                 "A1,VECTOR,0,5\nA2,VECTOR,0,5\n"
                 "A3,KILLED,0,95\nA4,KILLED,0,95\n"
                 "B1,C1,0.1,10\nB2,C1,1,50\nB3,C1,10,90\n")
    cfg = {**GATE, "positive_controls": ["KILLED"],
           "negative_controls": ["VECTOR"]}
    a = EA.analyze("plate_assay", f, cfg)
    assert a["z_prime_kind"] == "real"
    assert a["state"] == "analyzed"
    by = {c["entity"]: c for c in a["calls"]}
    assert by["C1"]["call"] == "validated"


def test_qc_hold_when_zprime_below_floor(tmp_path):
    # noisy controls -> real Z' below the QC floor
    rows = ["well,sample,conc_um,value",
            "A1,blank,0,5", "A2,blank,0,80",
            "A3,pos,0,20", "A4,pos,0,95",
            "B1,C1,0.1,10", "B2,C1,1,50", "B3,C1,10,90"]
    f = tmp_path / "noisy.csv"
    f.write_text("\n".join(rows) + "\n")
    a = EA.analyze("plate_assay", f, GATE)
    assert a["z_prime"] is not None and a["z_prime"] < 0.5
    assert a["state"] == "qc_hold"


def test_source_file_never_modified(plate):
    before = plate.read_bytes()
    EA.preview("plate_assay", plate, GATE)
    EA.analyze("plate_assay", plate, GATE)
    assert plate.read_bytes() == before


# ----------------------------------------------------------------- layout

GRID = "A,5,50,90\nB,10,40,70\n"
LAYOUT = ("well,sample,conc_um\n"
          "A1,C1,0.1\nA2,C1,1\nA3,C1,10\n"
          "B1,BORD,3\nB2,BORD,10\nB3,BORD,30\n")


def test_layout_joins_grid_export_to_dose_response(tmp_path):
    g = tmp_path / "grid.csv"
    g.write_text(GRID)
    lay = tmp_path / "map.csv"
    lay.write_text(LAYOUT)
    p = EA.preview("plate_assay", g, GATE, layout_path=lay)
    assert p["has_doses"] is True
    assert set(p["samples"]) == {"C1", "BORD"}
    a = EA.analyze("plate_assay", g, GATE, layout_path=lay)
    by = {c["entity"]: c["call"] for c in a["calls"]}
    assert by["C1"] == "validated"          # curve crosses ~1 uM
    assert a["state"] == "analyzed"


def test_preview_without_layout_flags_no_layout(tmp_path):
    g = tmp_path / "grid.csv"
    g.write_text(GRID)
    p = EA.preview("plate_assay", g, GATE)
    assert p["has_doses"] is False
    assert any(d["code"] == "no_layout" for d in p["diagnostics"])


# ------------------------------------------------- normalization refusal

def test_normalization_refusal_blocks_fits(tmp_path):
    # VECTOR(5) < KILLED(95): blank must OUT-signal full-inhibition;
    # impossible here -> to_pct_inhibition refuses, fits must NOT proceed
    f = tmp_path / "p.csv"
    f.write_text("well,sample,conc_um,value\n"
                 "A1,VECTOR,0,5\nA2,VECTOR,0,5\n"
                 "A3,KILLED,0,95\nA4,KILLED,0,95\n"
                 "B1,C1,0.1,10\nB2,C1,1,50\nB3,C1,10,90\n")
    cfg = {**GATE, "normalize": "pct_inhibition",
           "positive_controls": ["KILLED"], "negative_controls": ["VECTOR"]}
    a = EA.analyze("plate_assay", f, cfg)
    assert a["normalization_refused"] is True
    assert a["compounds"] == {}          # no fits on mislabeled raw values
    assert a["calls"] == []
    assert "impossible" in a["normalization_note"]
