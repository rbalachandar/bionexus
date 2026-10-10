"""labread native-PubChem ingestion — the CS05 deposition format, as a
hermetic unit test. The parser must be BLIND: it extracts only identity +
the raw %inhibition ladder (doses from the RESULT_ATTR_CONC_* meta rows,
which the REST header truncates) and never the submitter's IC50/OUTCOME
answer-key columns.
"""
from pathlib import Path

import pytest

from bionexus.labread import detect_format, read_plate

# Two compounds x 4 doses, built column-exact: identity block (6 cols) then
# the PERCENT dose columns (6..9). The header NAMES all four doses here but
# the meta rows — not the header — are what the parser trusts, mirroring
# the real deposit where the REST header truncates the dose names.
_HDR = (["PUBCHEM_RESULT_TAG", "PUBCHEM_SID", "PUBCHEM_CID",
         "PUBCHEM_EXT_DATASOURCE_SMILES", "PUBCHEM_ACTIVITY_OUTCOME",
         "PUBCHEM_ACTIVITY_SCORE"]
        + ["Inhibition at 1.0 uM", "Inhibition at 10 uM",
           "Inhibition at 30 uM", "Inhibition at 60 uM"])
_UNIT = ["RESULT_UNIT"] + [""] * 5 + ["PERCENT"] * 4
_CONC = ["RESULT_ATTR_CONC_MICROMOL"] + [""] * 5 + ["1.0", "10.0",
                                                    "30.0", "60.0"]
_D1 = ["1", "1001", "55001", "CCO", "Active", "90", "5", "40", "80", "95"]
_D2 = ["2", "1002", "55002", "CCN", "Inactive", "10", "2", "4", "7", "9"]
MINI = "\n".join([",".join(_HDR), ",".join(_UNIT), ",".join(_CONC),
                  ",".join(_D1), ",".join(_D2)]) + "\n"


def test_pubchem_detect_and_blind_parse(tmp_path):
    f = tmp_path / "deposit.csv"
    f.write_text(MINI)
    assert detect_format(f) == "pubchem"
    res = read_plate(f, max_response=100.0)
    assert len(res.records) == 8  # 2 compounds x 4 doses
    # doses come from the META row, not the (truncated) header
    assert sorted({r["conc_um"] for r in res.records}) == [1.0, 10.0, 30.0, 60.0]
    # value is the RAW inhibition on the ascending effect scale
    a5 = [r for r in res.records if r["sample"] == "SID1001"]
    assert {r["inhibition_pct"] for r in a5} == {5.0, 40.0, 80.0, 95.0}
    # BLIND: answer-key columns never surface in records or the fit input
    assert all("outcome" not in r and "verdict" not in r for r in res.records)
    assert "Active" not in str(res.analysis)  # their call is NOT in our fit


def test_pubchem_fit_recovers_the_strong_compound(tmp_path):
    f = tmp_path / "deposit.csv"
    f.write_text(MINI)
    res = read_plate(f, max_response=100.0)
    comp = res.analysis["compounds"]
    # SID1001 crosses 50% between 10 and 30 uM -> ~0.05-0.1 log; SID1002 never
    assert comp["SID1001"]["ic50_um"] is not None
    assert comp["SID1001"]["ic50_um"] < 100.0
    # SID1002 never crosses 50% inside the window: either no number (honest
    # censoring) or one far above the tested range — never an "Active"
    c2 = comp["SID1002"]["ic50_um"]
    assert c2 is None or c2 > 100.0


# ---------------------------------------------------------------- dialect B
# NCATS qHTS style (AID 2061307, 2025): doses EMBEDDED in header names,
# percent-ACTIVITY scale (decreasing for inhibitors, negative past full
# kill), sparse reassay curves, no usable RESULT_ATTR_CONC meta rows.
NC = (
    "PUBCHEM_RESULT_TAG,PUBCHEM_SID,PUBCHEM_CID,PUBCHEM_EXT_DATASOURCE_SMILES,"
    "PUBCHEM_ACTIVITY_OUTCOME,Fit_LogAC50,"
    "Activity at 0.001 uM,Activity at 0.01 uM,Activity at 1 uM,"
    "Activity at 10 uM,Activity at 100 uM\n"
    "3,3001,60001,CCOc1ccccc1,Active,-7.0,101,99,60,-58,-210\n"
    "4,3002,60002,CCN,Inactive,,100,,104,98,101\n"
)


def test_pubchem_dialect_b_embedded_doses_and_activity_flip(tmp_path):
    f = tmp_path / "ncats.csv"
    f.write_text(NC)
    assert detect_format(f) == "pubchem"
    res = read_plate(f, max_response=100.0)
    u = res.response_unit
    assert "flipped" in u  # disclosure: activity columns inverted to effect
    by = {}
    for r in res.records:
        by.setdefault(r["sample"], {})[r["conc_um"]] = r["inhibition_pct"]
    # 101% activity at 0.001 uM -> -1% inhibition; -58% activity -> 158% inh
    assert by["SID3001"][0.001] == -1.0
    assert by["SID3001"][10.0] == 158.0
    assert 0.01 not in by["SID3002"]       # sparse: empty well stays absent
    comp = res.analysis["compounds"]
    assert comp["SID3001"]["ic50_um"] is not None
    c2 = comp["SID3002"]["ic50_um"]
    assert c2 is None or c2 > 100.0


def test_pubchem_refuses_anonymous_percent_columns(tmp_path):
    # no meta conc row, no dose-named headers: parser must refuse, NOT guess
    rows = ["PUBCHEM_RESULT_TAG,PUBCHEM_SID,PUBCHEM_CID,"
            "PUBCHEM_EXT_DATASOURCE_SMILES,RESULT_5,RESULT_6",
            "1,1,1,CCO,10,20,40"]
    f = tmp_path / "anon.csv"
    f.write_text("\n".join(rows) + "\n")
    res = read_plate(f, max_response=100.0)
    assert res.records == []


# ------------------------------------------------------------- regime gate
# CS06 lesson encoded: deposited percent tables are fingerprinted for their
# normalization frame; only externally-validated frames may assert verdicts.

NC_INT = (
    "PUBCHEM_RESULT_TAG,PUBCHEM_SID,PUBCHEM_CID,PUBCHEM_EXT_DATASOURCE_SMILES,"
    "PUBCHEM_ACTIVITY_OUTCOME,Fit_LogAC50,"
    "Activity at 0.001 uM,Activity at 0.01 uM,Activity at 1 uM,"
    "Activity at 10 uM,Activity at 100 uM\n"
    "1,101,1,CCO,Active,,2,1.5,0.4,-0.6,-1.2\n"
    "2,102,2,CCN,Active,,1,0,-1,2,0.5\n"
)


def test_regime_gate_refuses_self_normalized(tmp_path):
    f = tmp_path / "internal.csv"
    f.write_text(NC_INT)
    res = read_plate(f, max_response=100.0)
    assert res.regime["frame"] == "self-normalized"
    assert res.regime["validated"] is False
    assert res.analysis["regime_refusal"] is True
    assert res.analysis["compounds"] == {}          # NO absolute claims
    assert res.analysis["shape_only"], "shape admits present"
    assert all(v["class"] in ("flat", "noisy", "falling",
                              "rise-complete", "rise-partial-low",
                              "rise-partial-high", "insufficient")
               for v in res.analysis["shape_only"].values())
    assert all("midpoint_uM" in v for v in
               res.analysis["shape_only"].values())
    assert len(res.records) == 10                    # records stay faithful
    assert "SHAPE-ONLY" in str(res)
    bypass = read_plate(f, max_response=100.0, assert_regimes=False)
    assert bypass.analysis["compounds"], "research mode fits"
    assert "regime_refusal" not in bypass.analysis


def test_regime_gate_passes_validated_external(tmp_path):
    f = tmp_path / "external.csv"
    f.write_text(MINI)
    res = read_plate(f, max_response=100.0)
    assert res.regime["frame"] == "external-reference"
    assert res.regime["validated"] is True
    assert "CS05" in res.regime["validation_source"]
    assert res.analysis["compounds"], "validated regime keeps asserting"


# ------------------------------------------------------------ shape QC
from bionexus.labread import classify_curve  # noqa: E402


def _sig(x0=1.0, h=2.5, base=0.0, top=100.0):
    cs = [0.001, 0.01, 0.1, 0.3, 1, 3, 10, 30]
    return [(c, base + (top - base) / (1 + (x0 / c) ** h)) for c in cs]


def test_classify_curve_classes():
    assert classify_curve(_sig())["class"] == "rise-complete"
    assert classify_curve(_sig())["midpoint_uM"] == pytest.approx(1.0, rel=0.3)
    assert classify_curve(_sig(base=60, top=75))["class"] == "flat"
    noisy = [(c, 50 + (-1) ** i * 25) for i, c in enumerate(
        [0.01, 0.1, 1, 10, 100, 1000])]
    assert classify_curve(noisy)["class"] == "noisy"
    falling = [(c, 100 - v) for c, v in _sig()]
    assert classify_curve(falling)["class"] == "falling"
    # every dose past midpoint of span -> potent below the measured window
    partial_low = [(c, v) for c, v in _sig(x0=0.001)][:8]
    assert classify_curve(partial_low)["class"].startswith("rise")
    assert classify_curve([(1, 1), (10, 40)])["class"] == "insufficient"


def test_shape_claims_survive_renormalization_bridge():
    """Ladder 1 of cross-regime trust: an affine renormalization (what the
    self-normalized frame IS, relative to an external one — new = a*old+b,
    a>0) must NOT change shape class or ordering of within-curve midpoints.
    Absolute numbers may shift; claims are only admitted where the class
    says the frame supports them."""
    strong = _sig(x0=0.3)
    weak = _sig(x0=10.0)
    for a, b in ((1.0, 0.0), (0.6, 20.0), (3.0, -10.0), (0.4, 60.0)):
        s = classify_curve([(c, a * v + b) for c, v in strong])
        w = classify_curve([(c, a * v + b) for c, v in weak])
        assert s["class"] == w["class"] == "rise-complete", (a, b, s, w)
        assert s["midpoint_uM"] < w["midpoint_uM"]


def test_frame_median_rule_is_live_not_dead_code():
    # sabotage audit found: with the med>55 clause sabotaged away, the
    # whole suite stayed green (flat-saturation covered every fixture).
    # This curve set is NOT flat (range 35) but starts high — only the
    # median rule can catch it.
    from bionexus.labread import _pubchem_frame
    recs = [{"sample": f"S{i}", "conc_um": c, "value": v}
            for i in range(8) for c, v in ((1.0, 60.0), (3.0, 85.0), (10.0, 95.0))]
    assert _pubchem_frame(recs) == "self-normalized"
    ext = [{"sample": f"S{i}", "conc_um": c, "value": v}
           for i in range(8) for c, v in ((1.0, 2.0), (3.0, 8.0), (10.0, 20.0))]
    assert _pubchem_frame(ext) == "external-reference"


def test_sub_micromolar_ic50_fit_needs_the_wide_log_range():
    # sabotage audit found: widening the Hill lower bound to 0 (killing
    # sub-1uM capability) left the suite green. Truth: 0.1 uM sigmoidal.
    import math
    from bionexus.labread import fit_ic50_ci
    ic50_true = 0.1
    pts = [(c, 100.0 / (1.0 + ic50_true / c))
           for c in (0.003, 0.01, 0.03, 0.1, 0.3, 1.0, 3.0)]
    f = fit_ic50_ci(pts)
    assert f is not None
    assert 0.05 <= f["ic50"] <= 0.2, f"sub-uM recovery broken: {f}"
