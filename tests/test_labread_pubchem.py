"""labread native-PubChem ingestion — the CS05 deposition format, as a
hermetic unit test. The parser must be BLIND: it extracts only identity +
the raw %inhibition ladder (doses from the RESULT_ATTR_CONC_* meta rows,
which the REST header truncates) and never the submitter's IC50/OUTCOME
answer-key columns.
"""
from pathlib import Path

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
