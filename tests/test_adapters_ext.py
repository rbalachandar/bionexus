import json
from pathlib import Path

import pytest

from bionexus.adapters.lab.recording import PlaybackLab, RecordingLab
from bionexus.adapters.lab.simulator import SimulatorLab
from bionexus.adapters.models.anthropic_provider import AnthropicProvider
from bionexus.adapters.sandbox.agentenv import AgentEnvClient, AgentEnvSandbox
from bionexus.adapters.store.sqlite import SqliteProvenanceStore
from bionexus.core.contracts import (
    Envelope,
    ProtocolOp,
    ProtocolStep,
    ProtocolSubmission,
    ReagentSpec,
    SampleKind,
    SampleSpec,
    ToolInvocation,
)
from bionexus.core.flywheel import FlywheelLog
from bionexus.core.interfaces import system_actor
from bionexus.core.safety import SafetyEngine, LabGateway

BRANCH = "b-ext"
RECORD = Path("tests/_recording.json")


def env() -> Envelope:
    return Envelope(experiment_branch_id=BRANCH)


def make_protocol():
    return ProtocolSubmission(
        envelope=env(),
        title="t",
        assay_type="binding",
        steps=[ProtocolStep(seq=1, op=ProtocolOp.dispense)],
        samples=[SampleSpec(sample_id="C1", kind=SampleKind.compound)],
        reagents=[ReagentSpec(name="buffer", amount="1 mL", bsl_level=1)],
    )


# ---- T3.3 recording / playback (P8) ------------------------------------------

def test_recording_then_playback_identical(tmp_path):
    record_path = tmp_path / "session.json"
    rec = RecordingLab(SimulatorLab(seed=7), record_path)
    gw_rec = LabGateway(rec, SafetyEngine(), SqliteProvenanceStore(), system_actor())
    p = make_protocol()
    run_id, _ = gw_rec.submit(p)
    result_rec = rec.fetch_results(run_id)
    rec.list_capabilities()
    rec.save()

    playback = PlaybackLab(record_path)
    assert playback.list_capabilities() == SimulatorLab(seed=7).list_capabilities()
    assert playback.submit_protocol(p) == run_id
    result_pb = playback.fetch_results(run_id)
    assert [m.value for m in result_pb.measurements] == [m.value for m in result_rec.measurements]


def test_playback_rejects_unrecorded_protocol(tmp_path):
    path = tmp_path / "s.json"
    rec = RecordingLab(SimulatorLab(seed=1), path)
    rec.submit_protocol(make_protocol())
    rec.save()
    playback = PlaybackLab(path)
    with pytest.raises(LookupError):
        playback.submit_protocol(make_protocol())  # different protocol_id


# ---- T4.1 anthropic provider (P3) ---------------------------------------------

def test_anthropic_stub_deterministic():
    provider = AnthropicProvider()  # no api key -> stub
    inv = ToolInvocation(envelope=env(), tool="c.fm.generate_molecules")
    r1 = provider.generate(inv, "prompt", n=2)
    r2 = provider.generate(inv, "prompt", n=2)
    assert r1.output["text"] == r2.output["text"]
    json.loads(r1.output["text"])
    assert r1.model_version == "stub-claude"


# ---- T4.2 AgentENV sandbox (P7) -------------------------------------------------

class _FakeTransport:
    """Contract test stand-in for the AgentENV server."""
    def __init__(self):
        self.calls = []
        self._n = 0

    def _request(self, method, path, body=None):
        self.calls.append((method, path))
        if method == "POST" and path == "/sandboxes":
            self._n += 1
            return {"sandboxID": f"sbx-{self._n}"}
        return {}


def test_agentenv_sandbox_snapshot_fork(monkeypatch):
    from bionexus.adapters.sandbox import agentenv as mod

    store = SqliteProvenanceStore()
    client = AgentEnvClient("http://localhost:0")
    transport = _FakeTransport()
    monkeypatch.setattr(client, "_request", transport._request)

    sbx = AgentEnvSandbox(client, "root", store=store, actor=system_actor())
    snap = sbx.snapshot()
    child = sbx.fork(snap)
    assert child.branch_id.startswith("root/")
    assert ("POST", "/sandboxes/sbx-1/pause") in transport.calls
    assert any(m == "POST" and path.endswith("/resume") for m, path in transport.calls)
    events = {r.event_type for r in store.branch_records(child.branch_id)}
    assert "sandbox_fork" in {e.value for e in events}


# ---- T4.4 flywheel ----------------------------------------------------------------

def test_flywheel_pairs_from_round(tmp_path):
    lab = SimulatorLab(seed=3)
    p = make_protocol()
    result = lab.fetch_results(lab.submit_protocol(p))
    log = FlywheelLog(tmp_path / "train.jsonl")
    example = log.pair_from_round(p, result)
    loaded = log.load()
    assert len(loaded) == 1
    assert example["labels"][0]["value"] == result.measurements[0].value
    assert "protocol_id" in example["input"]


def test_campaign_recording_playbacks(tmp_path):
    """Full-flow field recording replays identically offline (P8)."""
    rec_path = Path("examples/_campaign_recording.json")
    if not rec_path.exists():
        pytest.skip("run examples/full_campaign.py first")
    pb = PlaybackLab(rec_path)
    caps = pb.list_capabilities()
    assert caps["assays"]
    # replay every recorded run
    import json as _json
    entries = _json.loads(rec_path.read_text())
    runs = [e["run_id"] for e in entries if e["op"] == "fetch_results"]
    assert runs
    for run_id in runs:
        result = pb.fetch_results(run_id)
        assert result.measurements


def test_hypothesis_lifecycle_recorded(tmp_path):
    from bionexus.core.hypothesis import HypothesisTracker
    from bionexus.core.contracts import EventType as ET

    store = SqliteProvenanceStore()
    tracker = HypothesisTracker(store, system_actor())
    lab = SimulatorLab(seed=5)
    p = make_protocol()
    result = lab.fetch_results(lab.submit_protocol(p))
    h = tracker.propose("C1 >= 50 binding", candidate="C1", assay_type="binding",
                        predicted=">= 50", predicted_value=50.0)
    tracker.attach_test(h, p, result.run_id)
    h = tracker.verdict(h, result, threshold=50.0)
    assert h.status in ("validated", "invalidated") and h.measured_value is not None
    events = [r.event_type.value for r in store.branch_records(h.branch_id)]
    assert events == ["hypothesis_proposed", "hypothesis_tested",
                      "hypothesis_validated" if h.status == "validated" else "hypothesis_invalidated"]


# ---- domain realism: dose-response, counterscreen, MPO ------------------------

def test_dose_response_monotonic_and_ic50_present():
    from bionexus.adapters.lab.simulator import SimulatorLab
    lab = SimulatorLab(seed=11)
    p = ProtocolSubmission(
        envelope=env(), title="dr", assay_type="binding",
        steps=[ProtocolStep(seq=1, op=ProtocolOp.dispense)],
        samples=[SampleSpec(sample_id="C1", kind=SampleKind.compound, concentration=c)
                 for c in ["1uM", "5uM", "25uM", "50uM"]],
    )
    r = lab.fetch_results(lab.submit_protocol(p))
    vals = [m.value for m in r.measurements]
    assert all(v2 >= v1 - 6 for v1, v2 in zip(vals, vals[1:])), "response grows with dose"
    assert all("ic50_um" in m.derived_metrics for m in r.measurements)


def test_countscreen_flags_interferers():
    from bionexus.adapters.lab.simulator import SimulatorLab
    lab = SimulatorLab(seed=11)
    comps = [f"X{i}" for i in range(12)]
    p = ProtocolSubmission(
        envelope=env(), title="cs", assay_type="counterscreen",
        steps=[ProtocolStep(seq=1, op=ProtocolOp.dispense)],
        samples=[SampleSpec(sample_id=c, kind=SampleKind.compound, concentration="10uM") for c in comps],
    )
    r = lab.fetch_results(lab.submit_protocol(p))
    by = {m.sample_id: m.value for m in r.measurements}
    hits = [c for c, v in by.items() if v > 20]
    assert hits, "seeded interference should catch some compounds"


def test_mpo_score_bounds():
    from examples.full_campaign import mpo_score
    assert mpo_score(0.1, 1.0, 0.9, True) > mpo_score(25.0, 0.2, 0.3, False)
    assert 0.0 <= mpo_score(50, 0.1, 0.1, False) <= 1.0
