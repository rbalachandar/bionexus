"""Program profile tests — the TPP one level above experiments."""
import json

from bionexus import program as P


def test_load_defaults_and_save_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "PATH", tmp_path / "program.json")
    doc = P.load()
    assert doc["gate"] == "hit"
    P.save({"program": "KRAS", "target": "G12C", "gate": "lead",
            "lead_ic50_nm": 20})
    doc = P.load()
    assert doc["program"] == "KRAS" and doc["gate"] == "lead"
    assert doc["hit_ic50_nm"] == P.DEFAULT["hit_ic50_nm"]   # merged default


def test_gate_threshold_units(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "PATH", tmp_path / "program.json")
    P.save({"gate": "hit", "hit_ic50_nm": 1000})
    assert P.gate_threshold_um() == 1.0                     # nM -> µM
    P.save({"gate": "lead", "lead_ic50_nm": 50})
    assert P.gate_threshold_um() == 0.05


def test_gate_summary_mentions_program_target_gate(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "PATH", tmp_path / "program.json")
    P.save({"program": "MAP4K1-prog", "target": "MAP4K1", "gate": "hit"})
    txt = P.gate_summary()
    assert "MAP4K1-prog" in txt and "gate: hit" in txt


def test_corrupt_file_falls_back(tmp_path, monkeypatch):
    p = tmp_path / "program.json"
    p.write_text("{not json")
    monkeypatch.setattr(P, "PATH", p)
    assert P.load()["program"] == P.DEFAULT["program"]
