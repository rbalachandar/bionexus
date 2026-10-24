"""`bn select` — the what-would-run preview: prints the EI batch and every
refusal, submits nothing, and is the same policy path a campaign runs."""
import json

from bionexus.cli import main

CFG = {
    "problem": {"objective": "find IC50<=20", "constraints": [
        {"name": "potency", "description": "low IC50", "kind": "hard",
         "limit": 20.0, "unit": "uM"}]},
    "k": 2,
    "hypotheses": [
        {"statement": "A1 binds", "candidate": "A1", "assay_type": "binding",
         "predicted": "2 uM", "predicted_value": 2.0,
         "metadata": {"predicted_sd": 0.2, "extrapolation": True}},
        {"statement": "A2 binds", "candidate": "A2", "assay_type": "binding",
         "predicted": "4 uM", "predicted_value": 4.0,
         "metadata": {"predicted_sd": 0.2}},
        {"statement": "A3 binds", "candidate": "A3", "assay_type": "binding",
         "predicted": "6 uM", "predicted_value": 6.0,
         "metadata": {"predicted_sd": 0.4}},
        {"statement": "A4 binds", "candidate": "A4", "assay_type": "binding",
         "predicted": "60 uM", "predicted_value": 60.0,
         "metadata": {"predicted_sd": 0.2}}],
}


def _write(tmp_path):
    f = tmp_path / "acq.json"
    f.write_text(json.dumps(CFG))
    return str(f)


def test_select_prints_batch_and_refusals(tmp_path, capsys):
    rc = main(["select", _write(tmp_path), "--seed", "1"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "acquisition[bo-ei" in out
    assert "Picks" in out and "A2" in out and "A3" in out
    assert "extrapolation-veto" in out          # AD1 refused, named
    assert "outside batch (budget)" in out      # A4 refused for budget
    assert "nothing was submitted" in out


def test_select_submits_nothing_leaves_no_state(tmp_path, monkeypatch, capsys):
    # a preview must not touch the real provenance db: run in an empty cwd
    # and assert no bionexus.db appears (select uses an in-memory store)
    work = tmp_path / "cwd"
    work.mkdir()
    monkeypatch.chdir(work)
    monkeypatch.setenv("BIONEXUS_DATA_DIR", str(tmp_path / "data"))
    cfg = _write(tmp_path)
    rc = main(["select", cfg])
    assert rc == 0
    assert "Picks" in capsys.readouterr().out
    assert not (work / "bionexus.db").exists()


def test_select_needs_a_source(capsys):
    assert main(["select"]) == 2
