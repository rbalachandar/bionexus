"""Governance tests: halt switch, authorization matrix, SOP sign-off,
physical failure-mode classification. All paths stay inside tmp_path."""
import json

import pytest

from bionexus.core.contracts import (
    AssayType,
    Envelope,
    ProtocolOp,
    ProtocolStep,
    ProtocolSubmission,
    ReagentSpec,
    SampleKind,
    SampleSpec,
)
from bionexus.governance import (
    AuthorizationMatrix,
    HaltSwitch,
    SopRegistry,
)
from bionexus.physfail import classify


def make_protocol(bsl=1, recurring=False, title="t", sample="C1"):
    return ProtocolSubmission(
        envelope=Envelope(experiment_branch_id="gov-test"),
        title=title,
        assay_type=AssayType.binding,
        steps=[ProtocolStep(seq=1, op=ProtocolOp.dispense,
                            params={"volume_ul": 50})],
        samples=[SampleSpec(sample_id=sample, kind=SampleKind.compound)],
        reagents=[ReagentSpec(name="buffer", amount="1 mL", bsl_level=bsl)],
        constraints={"recurring": True} if recurring else {})


class FakeLab:
    def __init__(self):
        self.submitted = []

    def submit_protocol(self, protocol):
        self.submitted.append(protocol)
        return "run-1"


class FakeStore:
    def __init__(self):
        self.records = []

    def append(self, record):
        self.records.append(record)
        return record

    def decisions(self):
        return [r.decision for r in self.records if r.decision]


def _gateway(tmp_path, lab=None, approver=None, matrix=None, halt=None):
    from bionexus.core.safety import LabGateway, SafetyEngine
    lab = lab or FakeLab()
    store = FakeStore()
    gov = {"matrix": matrix or AuthorizationMatrix(),
           "halt": halt or HaltSwitch(path=tmp_path / "HALT")}
    from bionexus.core.interfaces import system_actor
    gw = LabGateway(lab, SafetyEngine(), store, system_actor("gov-test"),
                    governance=gov, approver=approver)
    return gw, lab, store


# ---------------------------------------------------------------- halt switch

def test_halt_engage_status_clear(tmp_path):
    hs = HaltSwitch(path=tmp_path / "HALT")
    assert hs.engaged() is None
    entry = hs.engage("spill in cabinet 2")
    assert entry["reason"] == "spill in cabinet 2"
    assert hs.engaged()["reason"] == "spill in cabinet 2"
    assert hs.clear() is True
    assert hs.engaged() is None
    assert hs.clear() is False


def test_corrupt_halt_file_still_halts(tmp_path):
    p = tmp_path / "HALT"
    p.write_text("not json")
    hs = HaltSwitch(path=p)
    assert hs.engaged() is not None       # fail closed, never fail open


def test_halt_blocks_submission_and_records(tmp_path):
    hs = HaltSwitch(path=tmp_path / "HALT")
    hs.engage("operator stop")
    gw, lab, store = _gateway(tmp_path, halt=hs)
    run_id, reason = gw.submit(make_protocol())
    assert run_id is None
    assert "[halt]" in reason and "operator stop" in reason
    assert lab.submitted == []
    kinds = [d["kind"] for d in store.decisions()]
    assert "halt_refusal" in kinds
    # cleared by human -> submission flows again
    hs.clear()
    run_id, _ = gw.submit(make_protocol())
    assert run_id == "run-1"


# ------------------------------------------------------- authorization matrix

def test_matrix_columns(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)               # SopRegistry writes .data/ here
    m = AuthorizationMatrix()
    assert m.classify(make_protocol()) == ("autonomous",
                                           "within standing policy")
    col, why = m.classify(make_protocol(bsl=2))
    assert col == "human" and "BSL-2" in why
    col, why = m.classify(make_protocol(bsl=3))
    assert col == "never" and "BSL-3" in why
    col, why = m.classify(make_protocol(title="culture of bacillus anthracis"))
    assert col == "never" and "dual-use" in why


def test_matrix_recurring_requires_sop(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    m = AuthorizationMatrix()
    proto = make_protocol(recurring=True, title="weekly QC binding screen")
    col, why = m.classify(proto)
    assert col == "human" and "SOP sign-off" in why
    sid = SopRegistry.sop_id(proto)
    assert any(p["id"] == sid for p in m.sops.pending())
    assert m.sops.approve(sid, by="lab-lead")
    col, why = m.classify(proto)
    assert col == "autonomous" and sid in why


def test_matrix_extra_rules(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = tmp_path / "authz.json"
    cfg.write_text(json.dumps([
        {"name": "no viral work", "text": "lentivirus", "column": "never"},
        {"name": "everything human on binding", "assay": "binding",
         "column": "human"},
    ]))
    m = AuthorizationMatrix(config_path=cfg)
    col, why = m.classify(make_protocol(title="lentivirus pseudotype assay"))
    assert col == "never" and "no viral work" in why
    # first-match order: DURC beats generic rules
    col, _ = m.classify(make_protocol(title="bacillus anthracis growth"))
    assert col == "never"


def test_human_column_needs_approver(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # no approver -> refused
    gw, lab, store = _gateway(tmp_path)
    run_id, reason = gw.submit(make_protocol(bsl=2))
    assert run_id is None and "HUMAN" in reason and "no approver" in reason
    assert lab.submitted == []
    # approver declines -> refused
    gw, lab, store = _gateway(tmp_path, approver=lambda t: False)
    run_id, reason = gw.submit(make_protocol(bsl=2))
    assert run_id is None and "declined" in reason
    # approver signs -> allowed, decision recorded
    gw, lab, store = _gateway(tmp_path, approver=lambda t: True)
    run_id, _ = gw.submit(make_protocol(bsl=2))
    assert run_id == "run-1"
    auth = [d for d in store.decisions() if d.get("kind") == "authorization"]
    assert auth and auth[-1]["column"] == "human"


def test_never_column_blocks_even_with_approver(tmp_path, monkeypatch):
    # note: SafetyEngine already refuses DURC/BSL>=3 before the matrix;
    # this exercises the matrix's own never-column with an operator rule
    monkeypatch.chdir(tmp_path)
    cfg = tmp_path / "authz.json"
    cfg.write_text(json.dumps(
        [{"name": "no pseudotype work", "text": "lentivirus",
          "column": "never"}]))
    gw, lab, store = _gateway(
        tmp_path, approver=lambda t: True,
        matrix=AuthorizationMatrix(config_path=cfg))
    run_id, reason = gw.submit(make_protocol(title="lentivirus entry assay"))
    assert run_id is None and "NEVER" in reason and "no pseudotype" in reason
    assert lab.submitted == []
    auth = [d for d in store.decisions() if d.get("kind") == "authorization"]
    assert auth and auth[-1]["column"] == "never"


# ------------------------------------------------------------- sop registry

def test_sop_registry_flow(tmp_path):
    reg = SopRegistry(path=tmp_path / "sops.json")
    proto = make_protocol(recurring=True, title="batch plate wash")
    sid = reg.propose(proto)
    assert sid.startswith("sop-")
    assert reg.pending()[0]["objective"] == "batch plate wash"
    assert reg.approved(sid) is False
    assert reg.approve("sop-nope") is False
    assert reg.approve(sid, by="director") is True
    assert reg.approved(sid) and reg.pending() == []
    # idempotent: re-propose does not resurrect a pending entry
    reg.propose(proto)
    assert reg.approved(sid)


# ------------------------------------------------------------------ physfail

def test_physfail_signatures():
    assert "96 readings identical" in classify([41200.0] * 96)["evidence"]
    assert classify([41200.0] * 96)["kind"] == "physical"      # saturated
    assert classify([0.0] * 96)["kind"] == "physical"          # dark
    assert classify([100.0, 98.0, -3.0, 102.0])["kind"] == "physical"
    assert classify([0.0] * 95 + [1e6])["kind"] == "physical"  # spill/unit
    assert classify([100.0, 105.0, 98.0, 102.0])["kind"] == "unknown"
    assert classify([])["kind"] == "data"


def test_physfail_errors():
    v = classify([], error="serial timeout on device /dev/ttyUSB0")
    assert v["kind"] == "physical" and "do not retry" in v["action"]
    v = classify([], error="csv line 12: could not parse 'abc' as float")
    assert v["kind"] == "data"


def test_watch_physical_read_short_circuits(tmp_path):
    # a saturated plate must produce a failure-mode, never verdicts
    from bionexus.watch import AutoAnalysisAgent, LabEvent
    agent = AutoAnalysisAgent(notify=lambda m: None, branch_id="gov-watch")
    plate = tmp_path / "plate1.csv"
    rows = ["Well ID,Compound,Conc (uM),RFU"]
    rows += [f"{c}{r},cpd{r},10,50000" for c in "ABCDEFGH" for r in range(1, 13)]
    plate.write_text("\n".join(rows) + "\n")
    out = agent.handle(LabEvent(kind="plate_ready", source="t", path=plate))
    assert out["failure_mode"]["kind"] == "physical"
    assert "do not retry" in out["failure_mode"]["action"]
