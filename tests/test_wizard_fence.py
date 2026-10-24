"""S-T5 completion: wizard fence — uploads must carry device identity and
match declared instruments; readiness vetoes capabilities the fence's
instruments do not declare."""
import tempfile
from pathlib import Path

import pytest

from bionexus.api import wizard_sessions as W
from bionexus.experiment import (BiologicalSystem, ClaimType,
                                 DeliveryConditions, ExperimentDefinition,
                                 Intervention, ReadoutCapability, ReadoutSpec)
from bionexus.readiness import review_experiment


def _program_with_fence(match=None):
    from bionexus import program as program_cfg
    name = "FenceEnforceProg"
    program_cfg.delete_program(name)
    labs = [{"instrument": "labmcp-mettler-toledo",
             **({"match": match} if match else {})}]
    program_cfg.save_program_record({
        "program": name, "objective": "fence test", "custom": True,
        "mode": "guided", "autonomy": "act", "metric": "ph", "unit": "pH",
        "direction": "max", "gate_value": 7.2, "k": 1, "rounds": 1,
        "candidates": "", "labs": labs})
    return name


def _clean():
    from bionexus import program as program_cfg
    program_cfg.delete_program("FenceEnforceProg")


def _defn(readout: ReadoutSpec) -> ExperimentDefinition:
    return ExperimentDefinition(
        scientific_question="q?", claim_type=ClaimType.causal_modification,
        intervention=Intervention(kind="user_defined", target="t"),
        system=BiologicalSystem(cell_line="user", target_half_life_min=120),
        delivery=DeliveryConditions(method="user",
                                    per_cell_loading_measured=True),
        readout=readout, controls=[])


def _write_export(tmp: Path, name: str, body: str) -> Path:
    f = tmp / name
    f.write_text(body)
    return f


def test_upload_without_device_identity_refused_under_fence(tmp_path):
    program_cfg_name = _program_with_fence()
    try:
        d = W.create_session("q?", "t", "causal_modification", program=program_cfg_name)
        f = _write_export(tmp_path, "anon.csv",
                          "well,compound,conc_um,value\nA1,C1,10,50\n")
        with pytest.raises(ValueError, match="no device identity"):
            W.upload(d["sid"], "anon.csv", f.read_bytes())
    finally:
        _clean()


def test_upload_with_device_identity_accepted(tmp_path):
    program_cfg_name = _program_with_fence()
    try:
        d = W.create_session("q?", "t", "causal_modification", program=program_cfg_name)
        f = _write_export(tmp_path, "bio.csv",
                          "Software Version,3.00\n"
                          "Reader Type,Synergy HTX\n"
                          "Serial Number,2206293D\n"
                          "\n"
                          "Well,Compound,conc_um,value\n"
                          "A1,C1,10,50\n")
        r = W.upload(d["sid"], "bio.csv", f.read_bytes())
        assert r["plate"]["n_wells"] >= 1
    finally:
        _clean()


def test_declared_match_pattern_enforced(tmp_path):
    program_cfg_name = _program_with_fence(match=["Synergy HTX"])
    try:
        d = W.create_session("q?", "t", "causal_modification", program=program_cfg_name)
        f = _write_export(tmp_path, "other.csv",
                          "Reader Type,FakeReader X\n"
                          "\n"
                          "Well,Compound,conc_um,value\n"
                          "A1,C1,10,50\n")
        with pytest.raises(ValueError, match="does not match"):
            W.upload(d["sid"], "other.csv", f.read_bytes())
    finally:
        _clean()


def test_readiness_vetoes_unmet_fence_capability():
    needed = ReadoutSpec(
        assay="user",
        capabilities=[ReadoutCapability.edited_vs_unedited])
    blocked = review_experiment(
        _defn(needed),
        available_caps={"readouts": ["read_weight", "get_status"]})
    checks = {f.check: f for f in blocked.findings}
    assert checks["fence_capability"].severity == "blocker"

    ok = review_experiment(
        _defn(needed),
        available_caps={"readouts": ["edited_vs_unedited", "read_weight"]})
    checks2 = {f.check: f for f in ok.findings}
    assert checks2["fence_capability"].severity == "pass"
