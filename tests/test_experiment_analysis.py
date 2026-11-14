"""Generic analysis lifecycle: profile dispatch, typed errors, determinism.

The lifecycle must stay modality-neutral: nothing here (or in the shared
contracts) knows about plates, compounds, or IC50s. Plate specifics are
pinned in test_plate_assay_analysis.py.
"""
from pathlib import Path

import pytest

from proef import experiment_analysis as EA
from proef.core.contracts.analysis import (
    AnalysisProfile, AnalysisState, DispositionAction, EvidenceOrigin,
    HumanDisposition, PreliminaryCall)


def test_profiles_registry_has_plate_assay():
    assert AnalysisProfile.plate_assay in EA.PROFILES


def test_unknown_profile_is_typed_error():
    with pytest.raises(EA.AnalysisError) as e:
        EA.preview("mass_spec", Path("x.csv"), {})
    assert e.value.code == "unknown_profile"


def test_missing_source_is_typed_error(tmp_path):
    with pytest.raises(EA.AnalysisError) as e:
        EA.preview("plate_assay", tmp_path / "nope.csv", {})
    assert e.value.code == "missing_source"


def test_invalid_config_is_typed_error(tmp_path):
    src = tmp_path / "s.csv"
    src.write_text("well,sample,conc_um,value\nA1,C1,1,5\n")
    with pytest.raises(EA.AnalysisError) as e:
        EA.preview("plate_assay", src, {"metric": "ic50_um",
                                        "bogus_knob": 1})
    assert e.value.code == "invalid_config"


def test_unreadable_source_is_typed_error(tmp_path):
    junk = tmp_path / "junk.csv"
    junk.write_text("this is not a plate\n,,,,\n")
    with pytest.raises(EA.AnalysisError) as e:
        EA.preview("plate_assay", junk, {})
    assert e.value.code == "unreadable_source"


def test_analysis_error_is_raisable_and_typed():
    err = EA.AnalysisError("unreadable_source", "bad bytes")
    assert err.code == "unreadable_source"
    assert "bad bytes" in str(err)


def test_is_terminal_hold():
    assert EA.is_terminal_hold({"state": "unsupported_regime"})
    assert EA.is_terminal_hold({"state": "qc_hold"})
    assert not EA.is_terminal_hold({"state": "analyzed"})


def test_generic_contract_vocabulary_complete():
    # generic vs profile-specific states are distinguished
    for s in ("uploaded", "preview_ready", "configured", "analyzed",
              "reviewed", "unreadable", "needs_input", "analysis_failed"):
        assert s in {m.value for m in AnalysisState}
    # evidence origin is closed: unknown stays unknown
    assert EvidenceOrigin("unknown").value == "unknown"
    # disposition can never be confused with confirmation
    assert DispositionAction.acknowledge.value == "acknowledge"


def test_preliminary_call_no_call_allowed():
    c = PreliminaryCall(entity="X", call="no_call", reason="single-dose")
    assert c.call == "no_call"


def test_human_disposition_stamps_actor_and_time():
    d = HumanDisposition(action=DispositionAction.override,
                         reason="curve is shallow", actor="kim",
                         target="C-101")
    assert d.actor == "kim" and d.at > 0
