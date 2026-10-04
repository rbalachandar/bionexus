"""bn demo — the moment must LAND, every run, on the real machinery."""
import subprocess
import sys
from pathlib import Path

from bionexus.demo import DEMO_GATE_UM, EXPECTED, run_demo


def test_demo_engineers_the_two_moments(tmp_path):
    rep = run_demo(db_path=tmp_path / "demo.db",
                   html_path=tmp_path / "diary.html")
    assert rep["verdicts"] == EXPECTED
    assert rep["chain_ok"] and rep["records"] > 20
    assert rep["simulated"] is True

    ab = rep["moments"]["abstain"]
    assert ab["ci95"][0] < DEMO_GATE_UM < ab["ci95"][1]   # straddle

    rf = rep["moments"]["refutation"]
    assert rf["rule"] == "ci-overlap" and rf["agreed"] is False
    pre_ci = rf["preliminary"]["ci95"]
    assert pre_ci[1] < DEMO_GATE_UM     # preliminary looked like a REAL hit
    assert rf["secondary_uM"] > rf["primary_uM"]

    assert "abstain" in rep["narration"][0].lower() or "ABSTAIN" in rep["narration"][0]
    assert any("REFUTED" in line for line in rep["narration"])

    html = (tmp_path / "diary.html").read_text()
    assert "Campaign diary" in html and "BORDER" in html


def test_demo_is_deterministic(tmp_path):
    a = run_demo(db_path=tmp_path / "a.db")
    b = run_demo(db_path=tmp_path / "b.db")
    assert a["verdicts"] == b["verdicts"] == EXPECTED
    assert [l for l in a["narration"]] == b["narration"]


def test_cli_demo_exit_zero(tmp_path):
    out = subprocess.run(
        [sys.executable, "-m", "bionexus.cli", "demo", "--quiet",
         "--db", str(tmp_path / "c.db")],
        capture_output=True, text=True, cwd=Path(__file__).parent.parent)
    assert out.returncode == 0
    assert "the two moments landed" in out.stdout
    assert "chain verified: OK" in out.stdout
