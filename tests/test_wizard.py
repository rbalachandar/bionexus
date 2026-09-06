"""Tests for the wizard experiment store (persistent DMTA state)."""
import pytest

from bionexus.wizard_store import WizardStore


def test_create_update_roundtrip(tmp_path):
    s = WizardStore(tmp_path / "wiz.db")
    eid = s.create("Does X cause Y?", "causal", "c-Myc")
    rec = s.get(eid)
    assert rec["status"] == "defining"
    assert rec["question"] == "Does X cause Y?"

    s.update(eid, "designing", problem={"q": "x"})
    rec = s.get(eid)
    assert rec["status"] == "designing"
    assert rec["payload"]["problem"] == {"q": "x"}
    assert rec["payload"]["problem"] is not None


def test_status_update_preserves_payload(tmp_path):
    s = WizardStore(tmp_path / "wiz.db")
    eid = s.create("Q", "causal", "T")
    s.update(eid, "designing", problem={"question": "Q"})
    s.update(eid, "readiness_ok", readiness={"verdict": "ready"})
    rec = s.get(eid)
    assert rec["payload"]["problem"]["question"] == "Q"
    assert rec["payload"]["readiness"]["verdict"] == "ready"


def test_ongoing_excludes_finished(tmp_path):
    s = WizardStore(tmp_path / "wiz.db")
    a = s.create("ongoing", "causal", "T")
    b = s.create("done", "causal", "T")
    s.update(a, "executing")
    s.update(b, "verdict_recorded", verdict="supports hypothesis")
    ongoing = s.ongoing()
    finished = s.finished()
    assert [e["id"] for e in ongoing] == [a]
    assert [e["id"] for e in finished] == [b]
    assert finished[0]["payload"]["verdict"] == "supports hypothesis"


def test_invalid_status_rejected(tmp_path):
    s = WizardStore(tmp_path / "wiz.db")
    eid = s.create("Q", "causal", "T")
    with pytest.raises(AssertionError):
        s.update(eid, "bogus_status")


def test_get_missing(tmp_path):
    s = WizardStore(tmp_path / "wiz.db")
    assert s.get("nope") is None
