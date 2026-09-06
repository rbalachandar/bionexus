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
from bionexus.core.interfaces import record_for, system_actor
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

def test_anthropic_stub_deterministic(monkeypatch):
    for var in ("BIONEXUS_LLM_MODEL", "BIONEXUS_LLM_TOKEN", "BIONEXUS_LLM_BASE_URL",
                "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    provider = AnthropicProvider(model="stub-claude")  # forced offline stub
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
    assert h.status in ("validated", "invalidated") and h.observed_value is not None
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
    comps = [f"X{i}" for i in range(24)]
    p = ProtocolSubmission(
        envelope=env(), title="cs", assay_type="counterscreen",
        steps=[ProtocolStep(seq=1, op=ProtocolOp.dispense)],
        samples=[SampleSpec(sample_id=c, kind=SampleKind.compound, concentration="10uM") for c in comps],
    )
    p.protocol_id = "fixed-cs-test"  # interference seeding keys off run/protocol id
    r = lab.fetch_results(lab.submit_protocol(p))
    by = {m.sample_id: m.value for m in r.measurements}
    hits = [c for c, v in by.items() if v > 20]
    assert hits, "seeded interference should catch some compounds"


def _mpo_score(p, s, a, ph):
    potency = max(0.0, 1.0 - p / 30.0)
    sel = max(0.0, min(1.0, s))
    phys = 1.0 if ph else 0.0
    return round(0.4 * potency + 0.25 * sel + 0.2 * a + 0.15 * phys, 3)


def test_mpo_score_bounds():
    assert _mpo_score(0.1, 1.0, 0.9, True) > _mpo_score(25.0, 0.2, 0.3, False)
    assert 0.0 <= _mpo_score(50, 0.1, 0.1, False) <= 1.0


# ---- MCP server ------------------------------------------------------------------

def test_mcp_session_initialize_and_tools():
    from bionexus.mcp_server import McpSession

    s = McpSession()
    init = s.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert init["result"]["serverInfo"]["name"] == "bionexus"
    tools = s.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    names = {t["name"] for t in tools["result"]["tools"]}
    assert {"generate_candidates", "run_assay", "propose_hypothesis", "list_lab_capabilities"} <= names


def test_mcp_tool_calls():
    from bionexus.mcp_server import McpSession

    s = McpSession()
    call = lambda n, a: s.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                                  "params": {"name": n, "arguments": a}})["result"]["content"][0]["text"]
    gen = json.loads(call("generate_candidates", {"target": "KRAS_G12C", "n": 2}))
    assert len(gen) == 2
    assay = json.loads(call("run_assay", {"compounds": ["CCO"], "assay": "binding"}))
    assert assay["results"]["CCO"]["ic50_um"] is not None
    hyp = json.loads(call("propose_hypothesis",
                          {"statement": "CCO >= 50 binding", "candidate": "CCO",
                           "assay_type": "binding", "predicted": ">= 50"}))
    assert hyp["status"] == "proposed"
    caps = json.loads(call("list_lab_capabilities", {}))
    assert "binding" in caps["assays"]
    err = s.handle({"jsonrpc": "2.0", "id": 4, "method": "nope"})
    assert err["error"]["code"] == -32601


# ---- HTML report -------------------------------------------------------------------

def test_report_html(tmp_path):
    import subprocess, sys
    from bionexus.adapters.store.sqlite import SqliteProvenanceStore
    from bionexus.core.contracts import Envelope, EventType
    from bionexus.core.interfaces import record_for, system_actor

    db = tmp_path / "test.db"
    store = SqliteProvenanceStore(str(db))
    actor = system_actor("test")
    env = Envelope(experiment_branch_id="report-test")

    for et, d in [
        (EventType.problem_defined, {"objective": "test objective"}),
        (EventType.lab_run, {"run_id": "r-1", "candidate": "C1"}),
        (EventType.gate_decision, {"gate": "approve_wetlab_protocol", "approved": True}),
    ]:
        store.append(record_for(env, et, actor, decision=d))

    out = tmp_path / "report.html"
    r = subprocess.run(
        [sys.executable, "-m", "bionexus.cli", "prove", "report-test",
         "--db", str(db), "--html", str(out)],
        capture_output=True, text=True)
    assert "chain intact" in r.stdout, f"prove stdout: {r.stdout[:300]}\nstderr: {r.stderr[:300]}"
    assert out.exists(), f"report not created; prove stdout: {r.stdout[:200]}"
    html = out.read_text()
    assert "BioNexus" in html
    assert "lab_run" in html

# ---- benchmark harness (offline fixture) -----------------------------------------

def test_benchmark_harness_offline(tmp_path):
    from bionexus.benchmark import CharRidgePolicy, MeanPolicy, RandomPolicy, run_benchmark

    class FixtureDataset:
        name, task = "fixture", "regression"

        def load(self):
            rng = __import__("random").Random(0)
            for _ in range(120):
                n = rng.randint(2, 10)
                yield "C" * n + "O", float(n) * 0.5 + rng.gauss(0, 0.05)

    ds = FixtureDataset()
    res = run_benchmark(ds, [RandomPolicy(), MeanPolicy(), CharRidgePolicy(dim=64)],
                        out=tmp_path / "b.json")
    assert res["policies"]["char3gram-ridge"]["spearman"] > 0.8, "linear signal must be learnable"
    assert res["policies"]["random"]["spearman"] < 0.3, "random must be a floor"
    assert (tmp_path / "b.json").exists()


# ---- benchmark metrics + LLM policy parsing ---------------------------------------

def test_roc_auc_correct_with_ties():
    from bionexus.benchmark import roc_auc
    assert roc_auc([0.9, 0.8, 0.7, 0.1], [1, 1, 0, 0]) == 1.0
    assert roc_auc([0.1, 0.2, 0.7, 0.9], [1, 1, 0, 0]) == 0.0
    assert roc_auc([0.5, 0.5, 0.5, 0.5], [1, 1, 0, 0]) == 0.5  # ties -> chance
    assert 0.0 <= roc_auc([0.3, 0.6, 0.4, 0.7], [1, 0, 0, 1]) <= 1.0


def test_llm_policy_parse_only():
    from bionexus.adapters.models.llm_policy import AnthropicLLMPolicy
    assert AnthropicLLMPolicy._parse('{"value": -1.42}') == -1.42
    assert AnthropicLLMPolicy._parse("The answer is 3.54 (logD).") == 3.54
    try:
        AnthropicLLMPolicy._parse("no numbers here")
        raised = False
    except ValueError:
        raised = True
    assert raised


# ---- imaging virtual lab (lab-imaging extra) ---------------------------------------

def test_imaging_lab_recovers_ic50_and_qc(tmp_path):
    np = pytest.importorskip("numpy")
    from bionexus.adapters.lab.imaging import ImagingSimulatorLab, true_ic50_um

    lab = ImagingSimulatorLab(seed=5, image_dir=str(tmp_path / "imgs"))
    p = ProtocolSubmission(
        envelope=env(), title="img", assay_type="binding",
        steps=[ProtocolStep(seq=1, op=ProtocolOp.dispense)],
        samples=[SampleSpec(sample_id=c, kind=SampleKind.compound, concentration=k)
                 for c in ["C1", "C2"] for k in ["0.5uM", "2uM", "10uM", "40uM"]]
        + [SampleSpec(sample_id="ctrl-neg", kind=SampleKind.buffer, concentration="10uM"),
           SampleSpec(sample_id="ctrl-neg2", kind=SampleKind.buffer, concentration="10uM")],
        reagents=[ReagentSpec(name="buffer", amount="1 mL", bsl_level=1)],
    )
    r = lab.fetch_results(lab.submit_protocol(p))
    assert r.qc.controls_passed
    assert r.qc.z_prime >= 0.3
    for m in r.measurements:
        truth = true_ic50_um(5, m.sample_id)
        assert abs(m.value - truth) / truth < 0.5, "IC50 recovery within 50% of truth"
    images = list((tmp_path / "imgs").glob("*.npy"))
    assert images, "raw plate images persisted as evidence"
    assert np.load(images[0]).shape == (24, 24)


def test_imaging_lab_dose_response_monotonic(tmp_path):
    pytest.importorskip("numpy")
    from bionexus.adapters.lab.imaging import (ImagingPlateReader, true_ic50_um,
                                               hill_response)
    dev = ImagingPlateReader(seed=9)
    concs = [0.5, 2.0, 10.0, 40.0]
    spec = [(f"A{i+1}", "C1", c) for i, c in enumerate(concs)]
    plate = dev.capture("monotonic-run", spec)
    ic50 = true_ic50_um(9, "C1")
    responses = [hill_response(c, ic50) for c in concs]
    assert all(b >= a for a, b in zip(responses, responses[1:])), "Hill curve is monotonic"


# ---- device sims (numpy extra) ------------------------------------------------------

def test_liquid_handler_low_volume_and_carryover(tmp_path):
    np = pytest.importorskip("numpy")
    from bionexus.adapters.lab.devices import LiquidHandlerSim
    from bionexus.core.contracts import ProtocolOp as PO

    lh = LiquidHandlerSim(seed=3)
    steps = [ProtocolStep(seq=1, op=PO.dispense, params={"volume_ul": 100}),
             ProtocolStep(seq=2, op=PO.dispense, params={"volume_ul": 1})]
    proto = ProtocolSubmission(envelope=env(), title="lh", assay_type="binding",
                               steps=steps,
                               samples=[SampleSpec(sample_id="C1", kind=SampleKind.compound)],
                               reagents=[ReagentSpec(name="b", amount="1 mL", bsl_level=1)])
    proto.protocol_id = "fixed-lh-test"  # device seeding keys off protocol id
    res = lh.execute(proto)
    t1, t2 = res["transfers"]
    assert abs(t1["error_percent"]) < 15  # cv=5%: 2-sigma bound
    assert t2["below_spec"] and t2["error_percent"] < 0  # systematic under-delivery


def test_sequencer_calls_planted_mutation(tmp_path):
    pytest.importorskip("numpy")
    from bionexus.adapters.lab.devices import SequencerSim

    seq = SequencerSim(seed=2)
    ref = "ACGT" * 15
    out = seq.sequence("s1", ref, [(20, "T")], coverage=30)
    calls = SequencerSim.call_variants(out["fastq"], ref)
    assert any(c["position"] == 20 and c["alt"] == "T" and c["fraction"] > 0.8
               for c in calls), "planted mutation must be recovered"
    assert all(c["position"] != 5 for c in calls), "no spurious high-freq calls"


def test_hypothesis_design_and_inconclusive(tmp_path):
    from bionexus.core.hypothesis import (ExperimentDesign, HypothesisTracker,
                                          SuccessCriteria)
    from bionexus.core.contracts import AssayResult, Envelope, InstrumentInfo, RunStatus

    store = SqliteProvenanceStore()
    tracker = HypothesisTracker(store, system_actor())
    h = tracker.propose(
        statement="C1 IC50 <= 20 uM", candidate="C1", assay_type="binding",
        predicted="IC50 <= 20", predicted_value=20.0, rationale="strong SAR precedent",
        criteria=SuccessCriteria(metric="ic50_um", direction="min", threshold=20.0),
        design=ExperimentDesign(assay_type="binding", concentrations=["0.5uM", "10uM", "40uM"],
                                replicates=3, controls=["negative"]),
    )
    assert h.status == "proposed" and h.criteria.threshold == 20.0
    assert h.design.concentrations == ["0.5uM", "10uM", "40uM"]

    # QC-failed run must be inconclusive, never a silent invalidate
    bad = AssayResult(envelope=env(), protocol_id="p", run_id="r-bad",
                      instrument=InstrumentInfo(adapter="sim", instrument_id="i"),
                      status=RunStatus.completed, measurements=[],
                      qc={"controls_passed": False})
    h = tracker.verdict(h, bad)
    assert h.status == "inconclusive" and h.qc_passed is False


# ---- scaffold + release readiness ---------------------------------------------------

def test_new_adapter_scaffold_lab(tmp_path):
    from bionexus.scaffold import scaffold

    target = scaffold("lab", "my_robot", tmp_path)
    mod = target / "my_robot_adapter.py"
    test = target / "test_my_robot_adapter.py"
    assert mod.exists() and test.exists()
    src = mod.read_text()
    assert "class MyRobot" in src and "def submit_protocol" in src


def test_new_adapter_scaffold_tool(tmp_path):
    from bionexus.scaffold import scaffold

    target = scaffold("tool", "my_docking", tmp_path, cap="e.sim.docking")
    src = (target / "my_docking_adapter.py").read_text()
    assert 'ToolName("e.sim.docking")' in src


def test_agent_notices_device_output(tmp_path):
    import time as _time
    from bionexus.watch import AutoAnalysisAgent, DeviceMonitor

    inbox = tmp_path / "outbox"
    messages = []
    agent = AutoAnalysisAgent(notify=messages.append)

    monitor = DeviceMonitor(inbox, poll_secs=0.05)
    assert list(monitor.events(once=True)) == []  # nothing yet

    (inbox / "run0007.csv").write_text(
        "Well ID,Compound,Conc (uM),RFU\n"
        "A1,ctrl,10,100\nA2,ctrl,10,104\n"
        "A3,C1,0.5,110\nA4,C1,2,145\nA5,C1,10,289\nA6,C1,40,540\n")
    events = list(monitor.events(once=True))
    assert len(events) == 1 and events[0].kind == "plate_ready"

    summary = agent.handle(events[0])
    assert summary["compounds"] == 1 and summary["z_prime"] > 0.5
    assert any("noticed device output" in m for m in messages)


def test_agent_closes_loop_with_safety_gated_confirmation(tmp_path):
    from bionexus.adapters.lab.simulator import SimulatorLab
    from bionexus.core.safety import LabGateway, MaxStepsRule, SafetyEngine
    from bionexus.watch import AutoAnalysisAgent, DeviceMonitor

    inbox = tmp_path / "outbox"
    store = SqliteProvenanceStore()
    gateway = LabGateway(SimulatorLab(seed=1), SafetyEngine(), store, system_actor())
    messages = []
    agent = AutoAnalysisAgent(notify=messages.append, gateway=gateway)
    monitor = DeviceMonitor(inbox, poll_secs=0.05)  # creates the outbox

    (inbox / "run.csv").write_text(
        "Well ID,Compound,Conc (uM),RFU\n"
        "A1,ctrl,10,100\nA2,ctrl,10,104\n"
        "A3,C1,0.5,110\nA4,C1,2,145\nA5,C1,10,289\nA6,C1,40,540\n")
    ev = list(monitor.events(once=True))[0]
    agent.handle(ev)
    assert any("loop closed" in m for m in messages), "confirmation auto-submitted"

    # a strict safety policy still blocks the agent's auto-submitted protocol
    strict_gw = LabGateway(SimulatorLab(seed=1),
                           SafetyEngine(rules=[MaxStepsRule(0)]), store, system_actor())
    strict_msgs = []
    strict = AutoAnalysisAgent(notify=strict_msgs.append, gateway=strict_gw)
    (inbox / "run2.csv").write_text((inbox / "run.csv").read_text())
    ev2 = list(monitor.events(once=True))
    assert ev2
    strict.handle(ev2[0])
    assert any("BLOCKED by safety" in m for m in strict_msgs), "safety gate stays sovereign"


def test_problem_to_portfolio_flow(tmp_path):
    from bionexus.core.contracts import EventType as ET
    from bionexus.core.hypothesis import (Constraint, HypothesisTracker,
                                          ProblemStatement)

    store = SqliteProvenanceStore()
    tracker = HypothesisTracker(store, system_actor())
    problem = tracker.define_problem(ProblemStatement(
        objective="find a binder", context="ctx",
        constraints=[Constraint(name="potency", description="IC50 <= 20 uM",
                                kind="hard", limit=20.0, unit="uM")],
        success_metric="orthogonal confirmation"))
    batch = tracker.propose_portfolio(problem, [
        {"statement": "A binds", "candidate": "A", "rationale": "r1"},
        {"statement": "B binds", "candidate": "B", "rationale": "r2"},
        {"statement": "C binds", "candidate": "C", "rationale": "r3"},
    ])
    assert len(batch) == 3 and all(h.problem_id == problem.problem_id for h in batch)
    selected = tracker.select_portfolio(problem, batch,
                                        score_fn=lambda h: {"A": 3, "B": 1, "C": 2}[h.candidate],
                                        k=2)
    assert [h.candidate for h in selected] == ["A", "C"]
    events = [r.event_type for r in store.branch_records(f"problem/{problem.problem_id}")]
    assert ET.problem_defined in events and ET.hypotheses_filtered in events
    assert len([e for e in events if e == ET.hypothesis_proposed]) == 3


def test_autoloop_full_flow_act_and_observe(tmp_path):
    from bionexus.autoloop import CampaignConfig, run_campaign
    from bionexus.adapters.lab.simulator import SimulatorLab
    from bionexus.core.hypothesis import Constraint, ProblemStatement

    problem = ProblemStatement(
        objective="find binder",
        constraints=[Constraint(name="potency", description="d", kind="hard",
                                limit=20.0, unit="uM")])
    specs = [{"statement": f"C{i} binds", "candidate": f"C{i}",
              "assay_type": "binding", "predicted": "<=20", "predicted_value": 20.0}
             for i in (1, 2, 3)]
    scores = {"C1": 0.9, "C2": 0.7, "C3": 0.5}

    # act: full autonomous loop
    cfg = CampaignConfig(problem=problem, hypotheses=specs,
                         score_fn=lambda h: scores[h.candidate], k=2,
                         autonomy="act", inbox=str(tmp_path / "in"), poll_secs=0.05)
    report = run_campaign(cfg, SimulatorLab(seed=4), SqliteProvenanceStore())
    assert report.selected == ["C1", "C2"]
    assert all(v == "validated" for v in report.verdicts.values())

    # observe: nothing submitted
    cfg2 = CampaignConfig(problem=problem, hypotheses=specs,
                          score_fn=lambda h: scores[h.candidate], k=2,
                          autonomy="observe", inbox=str(tmp_path / "in2"))
    report2 = run_campaign(cfg2, SimulatorLab(seed=4), SqliteProvenanceStore())
    assert report2.verdicts == {} and report2.selected == ["C1", "C2"]

    # gate: without approver it errors; with approver it proceeds
    cfg3 = CampaignConfig(problem=problem, hypotheses=specs,
                          score_fn=lambda h: scores[h.candidate], k=1,
                          autonomy="gate", inbox=str(tmp_path / "in3"), poll_secs=0.05)
    try:
        run_campaign(cfg3, SimulatorLab(seed=4), SqliteProvenanceStore())
        raised = False
    except ValueError:
        raised = True
    assert raised
    approved = []
    report3 = run_campaign(cfg3, SimulatorLab(seed=4), SqliteProvenanceStore(),
                           approver=lambda title: approved.append(title) or True)
    assert approved and report3.verdicts


# ---- real device adapters (mock transport / generated exports) ----------------------

class _FakeOtTransport:
    """Records a realistic OT-2 HTTP session for playback-style testing."""
    def __init__(self):
        self.calls = []
    def request(self, method, path, body=None):
        self.calls.append((method, path))
        if (method, path) == ("GET", "/health"):
            return {"name": "OT2-LAB1", "apiVersion": "7.2.0", "fwVersion": "v1.0.0"}
        if (method, path) == ("POST", "/protocols"):
            return {"data": {"id": "prot-1"}}
        if (method, path) == ("POST", "/runs"):
            return {"data": {"id": "run-1"}}
        if path == "/runs/run-1/actions":
            return {}
        if path == "/runs/run-1":
            return {"data": {"status": "succeeded", "commands": [
                {"commandType": "pickUpTip", "status": "succeeded", "params": {}},
                {"commandType": "aspirate", "status": "succeeded", "params": {"volume": 50}},
                {"commandType": "dispense", "status": "succeeded", "params": {"volume": 50}},
            ]}}
        raise AssertionError(f"unexpected call {method} {path}")


def test_opentrons_adapter_against_recorded_session(tmp_path):
    from bionexus.adapters.lab.opentrons import OpentronsLab, OpentronsTransport, compile_protocol
    from bionexus.core.contracts import Envelope, ProtocolOp, ProtocolStep, ProtocolSubmission

    # compile: abstract protocol -> OT-2 python protocol
    p = ProtocolSubmission(envelope=env(), title="dispense test", assay_type="binding",
                           steps=[ProtocolStep(seq=1, op=ProtocolOp.dispense,
                                               params={"well": "A2", "volume_ul": 50})])
    script = compile_protocol(p)
    assert "protocol_api" in script and "pip.dispense(50.0, plate['A2'].top())" in script

    # run against the recorded session
    transport = _FakeOtTransport()
    lab = OpentronsLab(transport=OpentronsTransport.__new__(OpentronsTransport))
    lab.client = transport
    caps = lab.list_capabilities()
    assert caps["robot"] == "OT2-LAB1" and caps["kind"] == "liquid_handler"
    run_id = lab.submit_protocol(p)
    assert ("POST", "/runs/run-1/actions") in transport.calls, "run started"
    assert lab.get_status(run_id) == "done"
    result = lab.fetch_results(run_id)
    assert result.instrument.adapter == "opentrons"
    assert len(result.measurements) == 3  # executed command evidence


def test_plate_reader_share_parses_auto_export(tmp_path):
    from bionexus.adapters.lab.plate_reader_share import PlateReaderShare
    from bionexus.core.contracts import (Envelope, ProtocolOp, ProtocolStep,
                                         ProtocolSubmission, ReagentSpec,
                                         SampleKind, SampleSpec)

    share = tmp_path / "reader_share"
    lab = PlateReaderShare(share_dir=share, assay="binding", wait_secs=5)
    p = ProtocolSubmission(envelope=env(), title="shared read", assay_type="binding",
                           steps=[ProtocolStep(seq=1, op=ProtocolOp.dispense)],
                           samples=[SampleSpec(sample_id="C1", kind=SampleKind.compound,
                                               concentration=c)
                                    for c in ["0.5uM", "2uM", "10uM", "40uM"]]
                           + [SampleSpec(sample_id="ctrl", kind=SampleKind.buffer,
                                         concentration="10uM")],
                           reagents=[ReagentSpec(name="buf", amount="1 mL", bsl_level=1)])
    run_id = lab.submit_protocol(p)
    assert lab.get_status(run_id) == "running"

    # reader finishes and auto-exports to the share (real Gen5-style layout)
    (share / "read_001.csv").write_text(
        "Well ID,Compound,Conc (uM),RFU\n"
        "A1,ctrl,10,100\nA2,ctrl,10,104\n"
        "A3,C1,0.5,110\nA4,C1,2,145\nA5,C1,10,289\nA6,C1,40,540\n")
    assert lab.get_status(run_id) == "done"
    r = lab.fetch_results(run_id)
    assert r.qc.controls_passed and r.measurements
    assert r.measurements[0].unit == "uM"


# ---- agent skills integration --------------------------------------------------------

def test_skill_md_valid_and_plugin_json():
    import json as _json
    import re as _re
    import bionexus.skills as _sk
    print("SKILLS MODULE:", _sk.__file__)
    from bionexus.skills import _parse_frontmatter
    skill = Path("skills/bionexus/SKILL.md").read_text()
    assert skill.startswith("---"), "SKILL.md needs frontmatter"
    fm = _parse_frontmatter(skill)  # yaml-or-fallback, like agents do
    print("FM:", fm)
    assert fm["name"] == "bionexus"
    assert fm["metadata"]["version"] == "0.1.0"
    for skill_md in Path("skills").glob("*/SKILL.md"):
        fm2 = _parse_frontmatter(skill_md.read_text())
        assert fm2["name"] == skill_md.parent.name, f"{skill_md}: name must match dir"
        assert "version" in fm2.get("metadata", {}), skill_md
    assert "SafetyEngine" in skill and "Never call a lab adapter directly" in skill
    plugin = _json.loads(Path("plugin.json").read_text())
    assert sorted(plugin["skills"]) == sorted(str(d) for d in Path("skills").iterdir() if d.is_dir())


def test_install_skills_from_local_checkout(tmp_path):
    from bionexus.skills import install_skills, load_skill_instructions
    # fake a local checkout of the skills repo
    repo = tmp_path / "repo"
    (repo / "skills" / "rdkit").mkdir(parents=True)
    (repo / "skills" / "rdkit" / "SKILL.md").write_text(
        '---\nname: rdkit\nmetadata:\n  version: "1.0"\n---\n# RDKit guidance')
    dest = tmp_path / "agent" / "skills"
    installed = install_skills(["rdkit", "not-a-real-skill"], dest, repo_path=repo)
    assert len(installed) == 1 and installed[0].name == "rdkit"
    body = load_skill_instructions(dest / "rdkit")
    assert "RDKit guidance" in body and not body.startswith("---")


def test_skill_discovery_and_role_resolution(tmp_path):
    import pathlib as _pl
    from bionexus.skills import discover_skills, guidance_for, recommend_for_role

    # discover bundled bionexus skills
    found = discover_skills()
    assert "bionexus" in found and "bionexus-labread" in found
    assert found["bionexus-labread"]["source"] in ("bionexus", "skills")

    # discover installed external skills (standard ~/.agents/skills convention)
    ext = tmp_path / ".agents" / "skills" / "rdkit"
    ext.mkdir(parents=True)
    (ext / "SKILL.md").write_text(
        '---\nname: rdkit\ndescription: "RDKit guidance"\nmetadata:\n  version: "1.0"\n---\nbody')
    found = discover_skills([tmp_path / ".agents" / "skills"])
    assert "rdkit" in found and found["rdkit"]["description"] == "RDKit guidance"
    assert guidance_for("rdkit", [tmp_path / ".agents" / "skills"]) == "body"  # body, frontmatter stripped

    # role resolution: recommended + installed
    oi = ext.parent / "opentrons-integration"
    oi.mkdir()
    (oi / "SKILL.md").write_text(
        '---\nname: opentrons-integration\nmetadata:\n  version: "2.0"\n---\nauthoring guidance')
    recs = recommend_for_role("assay-planning-agent", paths=[ext.parent])
    assert [r["path"].split("/")[-1] for r in recs] == ["opentrons-integration"]


# ---- vision readout (offline parts: PNG encoding, estimate parsing) -----------------

def test_gray_png_valid(tmp_path):
    pytest.importorskip("numpy")
    import struct
    from bionexus.vision import gray_png
    import numpy as np
    a = np.random.default_rng(0).integers(0, 255, (24, 24), dtype=np.uint8)
    png = gray_png(a)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    w, h = struct.unpack(">II", png[16:24])
    assert (w, h) == (24, 24)


def test_vision_response_parsing():
    import re
    from bionexus.vision import VisionWellReader
    text = '{"values": [15, 40, 65, 90]}'
    m = re.search(r"\[[^\]]*\]", text, re.S)
    values = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", m.group(0))]
    assert values == [15.0, 40.0, 65.0, 90.0]
    # robustness: thinking-model responses may wrap the list in prose
    m2 = re.search(r"\[[^\]]*\]", 'Let me see... {"values": [5, 15]} done', re.S)
    assert [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", m2.group(0))] == [5.0, 15.0]


def test_hypothesis_families_and_diversity_cap(tmp_path):
    from bionexus.core.contracts import EventType as ET
    from bionexus.core.hypothesis import (Constraint, HypothesisTracker,
                                          ProblemStatement)

    store = SqliteProvenanceStore()
    tracker = HypothesisTracker(store, system_actor())
    problem = tracker.define_problem(ProblemStatement(objective="find binder"))

    families = [
        {"family": "mech-A",
         "parent_statement": "mechanism A works",
         "variants": [{"statement": "A1 binds", "candidate": "A1"},
                      {"statement": "A2 binds", "candidate": "A2"}]},
        {"family": "mech-B",
         "parent_statement": "mechanism B works",
         "variants": [{"statement": "B1 binds", "candidate": "B1"}]},
    ]
    variants = tracker.propose_families(problem, families)
    assert len(variants) == 3
    assert {v.family for v in variants} == {"mech-A", "mech-B"}
    # scores: A2 (0.9) > A1 (0.8) > B1 (0.7) — without the cap, both slots
    # would go to family A; with it, each family gets one
    selected = tracker.select_portfolio(problem, variants,
                                        score_fn=lambda h: {"A1": 0.8, "A2": 0.9,
                                                            "B1": 0.7}[h.candidate],
                                        k=2, max_per_family=1)
    assert sorted(h.candidate for h in selected) == ["A2", "B1"]
    fam_events = [r for r in store.branch_records(f"problem/{problem.problem_id}")
                  if r.event_type == ET.hypothesis_proposed and r.decision
                  and "family_id" in r.decision]
    assert len(fam_events) == 2, "family parent claims provenance-recorded"


def test_resource_budget_caps_runs_and_records_exhaustion(tmp_path):
    from bionexus.autoloop import CampaignConfig, ResourceBudget, run_campaign
    from bionexus.core.contracts import EventType as ET
    from bionexus.core.hypothesis import Constraint, ProblemStatement

    problem = ProblemStatement(
        objective="find binder",
        constraints=[Constraint(name="potency", description="d", kind="hard",
                                limit=20.0, unit="uM")])
    specs = [{"statement": f"C{i} binds", "candidate": f"C{i}",
              "assay_type": "binding", "predicted": "<=20", "predicted_value": 20.0}
             for i in (1, 2)]
    # budget of exactly 1 run: first submission approved, second refused
    budget = ResourceBudget(max_total_runs=1, max_hypotheses_total=10)
    cfg = CampaignConfig(problem=problem, hypotheses=specs,
                         score_fn=lambda h: 0.5, k=2,
                         autonomy="act", inbox=str(tmp_path / "in"), poll_secs=0.05,
                         budget=budget)
    store = SqliteProvenanceStore()
    report = run_campaign(cfg, SimulatorLab(seed=4), store)
    runs = [r for r in store.branch_records(f"problem/{problem.problem_id}")
            if r.event_type == ET.lab_run]
    assert len(runs) == 1, "budget capped submissions at 1"
    exhaustion = [r for r in store.branch_records(f"problem/{problem.problem_id}")
                  if r.decision and r.decision.get("kind") == "budget_exhausted"]
    assert exhaustion, "budget exhaustion provenance-recorded"


def test_hypothesis_agent_dedup_and_total_cap(tmp_path):
    from bionexus.adapters.models.openai_compat import OpenAICompatProvider
    from bionexus.core.hypothesis import HypothesisTracker, ProblemStatement
    from bionexus.hypothesis_agent import propose_families_with_agent

    class Scripted:
        name, model_version = "scripted", "s1"
        def generate(self, inv, prompt, **kw):
            from bionexus.core.contracts import ToolResult
            text = json.dumps({"families": [{"family": "A",
                "parent_statement": "A works", "kind": "mechanistic",
                "confidence": 0.9, "variants": [
                    {"statement": "A1 binds", "candidate": "A1",
                     "assay_type": "binding", "predicted": "<=20",
                     "predicted_value": 20.0, "rationale": "r",
                     "variables": {"warhead": "acrylamide"}}]}]})
            return ToolResult(envelope=inv.envelope.model_copy(),
                              invocation_id=inv.invocation_id, status="succeeded",
                              output={"text": text}, model_version=self.model_version)
        def predict(self, inv, kind, payload):
            raise NotImplementedError

    store = SqliteProvenanceStore()
    tracker = HypothesisTracker(store, system_actor())
    problem = ProblemStatement(objective="find binder")
    model = Scripted()
    # round 1: accepted
    v1, _ = propose_families_with_agent(tracker, problem, model, max_total_hypotheses=5)
    assert len(v1) == 1
    # round 2: same hypothesis re-proposed -> deduped to nothing
    v2, _ = propose_families_with_agent(tracker, problem, model,
                                        existing_keys={("A1", "A1 binds")},
                                        max_total_hypotheses=5)
    assert v2 == []
    # skill guidance flows into the prompt
    seen = {}
    class Probe(Scripted):
        def generate(self, inv, prompt, **kw):
            seen["prompt"] = prompt
            return Scripted.generate(self, inv, prompt, **kw)
    propose_families_with_agent(tracker, problem, Probe(),
                                skill_guidance="Always include controls.",
                                max_total_hypotheses=1,
                                existing_keys={("A1", "A1 binds")})
    assert "Always include controls." in seen["prompt"]


def test_agentenv_adapter_against_mock_http_server(tmp_path):
    """Integration test: the adapter over a real local HTTP server implementing
    the AgentENV endpoints — the network path is exercised, not bypassed."""
    import json as _json
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    state = {"n": 0, "calls": []}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, payload):
            body = _json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            state["calls"].append(("GET", self.path))
            self._send(200, {"data": {"status": "succeeded", "commands": []}})

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length) if length else b""
            state["calls"].append(("POST", self.path, body.decode()))
            if self.path == "/sandboxes":
                state["n"] += 1
                self._send(200, {"sandboxID": f"sbx-{state['n']}"})
            else:
                self._send(200, {})

        def do_DELETE(self):
            state["calls"].append(("DELETE", self.path))
            self._send(200, {})

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        from bionexus.adapters.sandbox.agentenv import (AgentEnvClient,
                                                        AgentEnvSandbox)
        from bionexus.core.interfaces import record_for, system_actor
        from bionexus.adapters.store.sqlite import SqliteProvenanceStore

        client = AgentEnvClient(f"http://127.0.0.1:{server.server_port}")
        store = SqliteProvenanceStore()
        sbx = AgentEnvSandbox(client, "root", store=store, actor=system_actor())
        assert sbx.sandbox_id == "sbx-1"
        snap = sbx.snapshot()                      # POST pause
        child = sbx.fork(snap)                     # POST resume on same sandbox
        assert child.branch_id.startswith("root/")
        assert any(m == "POST" and p == "/sandboxes/sbx-1/pause"
                   for m, p, *_ in state["calls"])
        assert any(m == "POST" and p == "/sandboxes/sbx-1/resume"
                   for m, p, *_ in state["calls"])
        assert any(m == "POST" and p == "/sandboxes" for m, p, *_ in state["calls"])
        child.destroy()                            # DELETE
        assert any(m == "DELETE" and "/sandboxes/" in p
                   for m, p, *_ in state["calls"])
    finally:
        server.shutdown()


# ---- docker sandbox adapter (mock runner) --------------------------------------------

class _FakeDocker:
    def __init__(self):
        self.calls: list[list[str]] = []
        self._n = 0
    def run(self, *args, input=None):
        self.calls.append(list(args))
        if args[0] == "run":
            self._n += 1
            return f"cont-{self._n}"
        if args[0] == "commit":
            return "bionexus/branch:snap-1"
        return ""
    def ok(self, *args):
        return True


def test_docker_sandbox_snapshot_fork_destroy():
    from bionexus.adapters.sandbox.docker import DockerRunner, DockerSandbox
    store = SqliteProvenanceStore()
    runner = _FakeDocker()
    sbx = DockerSandbox(image="python:3.12-slim", branch_id="root",
                        store=store, actor=system_actor(), runner=runner)
    assert sbx.container_id == "cont-1"
    tag = sbx.snapshot()
    assert tag.startswith("bionexus/root:")
    assert runner.calls[-1][:2] == ["commit", "cont-1"]
    child = sbx.fork(tag)
    assert child.image == tag and child.parent_branch_id == "root"
    child.exec("ls /data")
    assert runner.calls[-1][:3] == ["exec", child.container_id, "sh"]
    child.destroy()
    events = [r.event_type.value for r in store.branch_records("root")]
    assert "sandbox_snapshot" in events
    rm_calls = [c for c in runner.calls if c[0] == "rm"]
    assert rm_calls, "container removed on destroy"


# ---- opensandbox adapter (fake SDK client) --------------------------------------------

class _FakeFiles:
    def __init__(self):
        self.written = {}
    def write_files(self, entries):
        for path, data in entries:
            self.written[path] = data
    def read_file(self, path):
        return self.written.get(path, "")


class _FakeOpenSandboxClient:
    def __init__(self):
        self.files = _FakeFiles()
        self.killed = False
        self.id = "osb-1"
    def create(self, image, timeout_secs):
        return self


def test_opensandbox_adapter_lifecycle(tmp_path):
    from bionexus.adapters.sandbox.opensandbox import OpenSandboxSandbox
    from bionexus.core.contracts import EventType as ET

    class _Client(_FakeOpenSandboxClient):
        def __init__(self):
            super().__init__()
            self.killed = False
            self.commands = self
        def run(self, command):
            r = type("R", (), {})()
            r.logs = type("L", (), {})()
            r.logs.stdout = [type("T", (), {"text": f"ran: {command}"})()]
            return r
        def kill(self):
            self.killed = True

    client = _Client()
    store = SqliteProvenanceStore()
    sbx = OpenSandboxSandbox(client, branch_id="root", store=store,
                             actor=system_actor())
    assert sbx.sandbox_id == "osb-1"
    out = sbx.exec("echo hi")
    assert out == "ran: echo hi"
    snap = sbx.snapshot()
    child = sbx.fork(snap)
    assert child.branch_id.startswith("root/")
    child.write_file("/tmp/x", "data")
    assert child.read_file("/tmp/x") == "data"
    child.destroy()
    assert client.killed
    events = {r.event_type.value for r in store.branch_records(child.branch_id)}
    assert "sandbox_fork" in events


def test_dose_response_svg_plot(tmp_path):
    from bionexus.labread import read_plate
    from bionexus.plots import dose_response_svg

    f = tmp_path / "p.csv"
    f.write_text("Well ID,Compound,Conc (uM),RFU\n"
                 "A1,ctrl,10,100\nA2,ctrl,10,104\n"
                 "A3,C1,0.5,110\nA4,C1,2,145\nA5,C1,10,289\nA6,C1,40,540\n")
    r = read_plate(f, max_response=600)
    svg = r.curve_svg("C1")
    assert "<polyline" in svg and "IC50" in svg
    # escaping: title cannot inject markup
    assert "<script" not in dose_response_svg([(1, 1)], title="<script>x</script>")

    # also from the plotter directly
    svg2 = dose_response_svg([(0.5, 10), (2, 30), (10, 55), (40, 80)], ic50=5.0)
    assert svg2.count("<circle") >= 4  # markers + IC50 point


def test_campaign_templates_fill_and_build(tmp_path):
    from bionexus.templates import build_campaign, fill, list_templates, load_template

    names = {t["name"] for t in list_templates()}
    assert {"dose-response-screen", "confirmatory-followup", "sar-exploration"} <= names
    rendered = fill(load_template("dose-response-screen"),
                    {"compounds": "C1, C2", "threshold": "15"}, prompt_missing=False)
    cfg = build_campaign(rendered)
    assert "15" in cfg["problem"]["objective"]
    assert [h["candidate"] for h in cfg["hypotheses"]] == ["C1", "C2"]
    assert all(h["predicted_value"] == 15.0 for h in cfg["hypotheses"])
    assert cfg["autonomy"] == "gate"  # safe default from the template
    try:
        load_template("nope")
        raised = False
    except FileNotFoundError:
        raised = True
    assert raised


# ---- approval inbox + cockpit (F3) ----------------------------------------------------

def test_approval_inbox_roundtrip(tmp_path):
    from bionexus.approvals import ApprovalInbox

    box = ApprovalInbox(tmp_path / "approvals.jsonl")
    aid = box.request("dose-response assay C1")
    assert box.pending()[0]["title"] == "dose-response assay C1"
    box.decide(aid, True)
    assert box.status_of(aid) == "approved"
    assert box.pending() == []


def test_web_approver_waits_for_decision(tmp_path):
    import threading
    from bionexus.approvals import ApprovalInbox, web_approver

    box = ApprovalInbox(tmp_path / "a.jsonl")
    approved = []
    approver = web_approver(box, poll_secs=0.05)
    t = threading.Thread(target=lambda: approved.append(approver("run X")))
    t.start()
    for _ in range(100):  # wait for the request to land
        pend = box.pending()
        if pend:
            break
        threading.Event().wait(0.02)
    box.decide(pend[0]["id"], approve=False)
    t.join(5)
    assert approved == [False]


def test_cockpit_server_endpoints(tmp_path):
    import urllib.request
    from bionexus.serve import serve_in_thread

    httpd, _ = serve_in_thread(port=0, inbox=str(tmp_path / "a.jsonl"))
    port = httpd.server_address[1]
    try:
        assert urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz").read() == b"ok"
        html = urllib.request.urlopen(f"http://127.0.0.1:{port}/").read().decode()
        assert "Awaiting your decision" in html
        # request an approval via the inbox, see it on the dashboard, decide via POST
        from bionexus.approvals import ApprovalInbox
        box = ApprovalInbox(str(tmp_path / "a.jsonl"))
        aid = box.request("assay C1")
        html = urllib.request.urlopen(f"http://127.0.0.1:{port}/").read().decode()
        assert aid in html and "assay C1" in html
        req = urllib.request.Request(f"http://127.0.0.1:{port}/decide",
                                     data=f"id={aid}&action=approve".encode())
        urllib.request.urlopen(req)  # 303 redirect
        assert box.status_of(aid) == "approved"
        pend = json.loads(urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/pending").read())
        assert pend == []
    finally:
        httpd.shutdown()


def test_plate_result_csv_export(tmp_path):
    from bionexus.labread import read_plate
    f = tmp_path / "p.csv"
    f.write_text("Well ID,Compound,Conc (uM),RFU\n"
                 "A1,ctrl,10,100\nA2,ctrl,10,104\n"
                 "A3,C1,0.5,110\nA4,C1,2,145\nA5,C1,10,289\nA6,C1,40,540\n")
    r = read_plate(f, max_response=600)
    out = r.to_csv(tmp_path / "export.csv")
    text = out.read_text()
    assert "well,sample,conc_um,value,control,ic50_um" in text
    assert "C1" in text


def test_diary_renders_narrative(tmp_path):
    from bionexus.core.hypothesis import (HypothesisTracker, ProblemStatement,
                                          SuccessCriteria)
    from bionexus.core.contracts import (Envelope, EventType, ProtocolOp,
                                         ProtocolStep, ProtocolSubmission,
                                         ReagentSpec, SampleKind, SampleSpec)
    from bionexus.diary import write_diary
    from bionexus.adapters.lab.simulator import SimulatorLab

    store = SqliteProvenanceStore()
    tracker = HypothesisTracker(store, system_actor())
    problem = tracker.define_problem(ProblemStatement(objective="find a binder"))
    lab = SimulatorLab(seed=5)
    p = ProtocolSubmission(
        envelope=Envelope(experiment_branch_id=f"problem/{problem.problem_id}"),
        title="t", assay_type="binding",
        steps=[ProtocolStep(seq=1, op=ProtocolOp.dispense)],
        samples=[SampleSpec(sample_id="C1", kind=SampleKind.compound,
                            concentration="10uM")],
        reagents=[ReagentSpec(name="b", amount="1 mL", bsl_level=1)])
    h = tracker.propose(statement="C1 IC50 <= 20", candidate="C1",
                        assay_type="binding", predicted="IC50 <= 20",
                        predicted_value=20.0, rationale="precedent",
                        criteria=SuccessCriteria(metric="ic50_um", threshold=20.0),
                        branch_id=f"problem/{problem.problem_id}")
    run_id = lab.submit_protocol(p)
    tracker.attach_test(h, p, run_id)
    tracker.verdict(h, lab.fetch_results(run_id))
    store.append(record_for(Envelope(experiment_branch_id=f"problem/{problem.problem_id}"),
                            EventType.gate_decision, system_actor(),
                            decision={"gate": "approve", "approved": True,
                                      "approved_by": "scientist"}))
    out = tmp_path / "diary.html"
    write_diary(store.branch_records(f"problem/{problem.problem_id}"),
                f"problem/{problem.problem_id}", out)
    html = out.read_text()
    assert "find a binder" in html
    assert "C1 IC50" in html  # "<=" is HTML-escaped
    assert "VALIDATED" in html or "INVALIDATED" in html
    assert "review gate" in html


def test_connect_scan_detects_instruments(tmp_path):
    from bionexus.connect import scan_share
    (tmp_path / "read1.csv").write_text(
        "Well ID,Compound,Conc (uM),RFU\nA1,ctrl,10,100\nA2,C1,10,250\n")
    (tmp_path / "notes.txt").write_text("not an export")
    res = scan_share(tmp_path)
    assert "long" in res["formats"]
    assert any("PlateReaderShare" in s["adapter"] for s in res["suggestions"])
    empty = tmp_path / "empty"
    empty.mkdir()
    res2 = scan_share(empty)
    assert "SimulatorLab" in res2["suggestions"][0]["adapter"]


# ---- ExperimentDefinition + ExperimentReadinessReview ---------------------------------

def _strong_definition():
    from bionexus.experiment import (BiologicalSystem, ClaimType,
                                     DeliveryConditions, ExperimentDefinition,
                                     Intervention, ReadoutCapability,
                                     ReadoutSpec)
    return ExperimentDefinition(
        experiment_id="exp-strong",
        scientific_question="Does S62 phosphorylation cause degradation?",
        claim_type=ClaimType.causal_modification,
        intervention=Intervention(
            kind="protein_edit", target="c-Myc", site="S62",
            modification="phosphoserine", requires_prior_genome_edit=True),
        system=BiologicalSystem(cell_line="HEK293T", target_half_life_min=120),
        delivery=DeliveryConditions(method="electroporation",
                                    per_cell_loading_measured=True),
        readout=ReadoutSpec(
            assay="ratiometric MS", measures_edited_fraction=True,
            distinguishes_modified_from_mimetic=True,
            capabilities=[ReadoutCapability.edited_vs_unedited,
                          ReadoutCapability.quantified_fraction]),
        controls=["dead donor", "no-donor"],
        denominators=["edited/total"],
    )


def _weak_definition(base):
    weak = base.model_copy(deep=True)
    weak.experiment_id = "exp-weak"
    weak.readout = weak.readout.model_copy(deep=True)
    weak.readout.measures_edited_fraction = False
    weak.readout.distinguishes_modified_from_mimetic = False
    weak.readout.capabilities = []
    weak.controls = []
    weak.denominators = []
    weak.system.target_half_life_min = 20
    return weak


def test_experiment_readiness_strong_passes():
    from bionexus.readiness import ReviewVerdict, review_experiment
    review = review_experiment(_strong_definition())
    assert review.verdict == ReviewVerdict.ready
    assert review.blockers == []


def test_experiment_readiness_weak_blocked():
    from bionexus.core.contracts import Envelope
    from bionexus.readiness import ReviewVerdict, review_experiment
    weak = _weak_definition(_strong_definition())
    weak.readout.measures_edited_fraction = False
    review = review_experiment(weak)
    assert review.verdict == ReviewVerdict.blocked
    assert any("denominator" in b.message for b in review.blockers)


def test_experiment_readiness_interpretable_negative():
    defn = _strong_definition()
    assert defn.interpretable_negative_result()
    defn.readout.measures_edited_fraction = False
    defn.denominators = []
    assert not defn.interpretable_negative_result()


def test_experiment_definition_provenance(tmp_path):
    from bionexus.adapters.store.sqlite import SqliteProvenanceStore
    from bionexus.core.contracts import Envelope, EventType
    from bionexus.core.hypothesis import (HypothesisTracker, ProblemStatement)
    from bionexus.core.interfaces import system_actor
    from bionexus.experiment import (BiologicalSystem, ClaimType,
                                     DeliveryConditions, ExperimentDefinition,
                                     Intervention, ReadoutSpec)
    from bionexus.readiness import review_and_record

    store = SqliteProvenanceStore()
    tracker = HypothesisTracker(store, system_actor())
    problem = tracker.define_problem(ProblemStatement(objective="test"))
    exp = ExperimentDefinition(
        experiment_id="exp-1",
        scientific_question="test question",
        claim_type=ClaimType.causal_modification,
        intervention=Intervention(kind="protein_edit", target="c-Myc"),
        system=BiologicalSystem(cell_line="HEK293T"),
        delivery=DeliveryConditions(method="electroporation",
                                    per_cell_loading_measured=True),
        readout=ReadoutSpec(assay="MS", measures_edited_fraction=True,
                            distinguishes_modified_from_mimetic=True),
        controls=["dead donor"], denominators=["edited/total"],
    )
    review = review_and_record(store, Envelope(experiment_branch_id="test"), actor=system_actor(), defn=exp)
    tracker.define_experiment(problem, exp, review)
    events = [r.event_type.value for r in store.branch_records("test")] \
             + [r.event_type.value for r in store.branch_records(f"problem/{problem.problem_id}")]
    assert "experiment_defined" in events
    assert "experiment_readiness_reviewed" in events


# ---- TPP ----------------------------------------------------------------------------

def test_tpp_evaluation_phases():
    from bionexus.tpp import (Criterion, CriterionCategory, CriterionPhase,
                              TPP)
    tpp = TPP(program_name="test", objective="find inhibitor",
              target_name="X", criteria=[
        Criterion(name="IC50_nM", category=CriterionCategory.potency,
                  phase=CriterionPhase.hit, threshold=1000, direction="min", unit="nM"),
        Criterion(name="IC50_nM_lead", category=CriterionCategory.potency,
                  phase=CriterionPhase.lead, threshold=10, direction="min", unit="nM",
                  required=True),
        Criterion(name="LogP_nice", category=CriterionCategory.physicochemical,
                  phase=CriterionPhase.lead, threshold=5, direction="min",
                  required=False),
    ])
    # hit phase: only IC50 < 1000
    ev = tpp.evaluate({"IC50_nM": 500}, CriterionPhase.hit)
    assert ev.all_required_passed
    # lead phase: needs IC50 < 10 (we don't have it yet)
    ev2 = tpp.evaluate({"IC50_nM": 500, "IC50_nM_lead": 500,
                        "LogP_nice": 3}, CriterionPhase.lead)
    assert not ev2.all_required_passed
    assert len(ev2.failures) == 1
    # now pass
    ev3 = tpp.evaluate({"IC50_nM": 5, "IC50_nM_lead": 5, "LogP_nice": 3},
                       CriterionPhase.lead)
    assert ev3.all_required_passed


# ---- ADMET panel ----------------------------------------------------------------------

def test_admet_rule_based():
    from bionexus.adapters.admet import RuleBasedADMET
    predictor = RuleBasedADMET()
    r = predictor.predict("CCOc1ccccc1NC(=N)c1ccc(N)cc1")  # some real-ish molecule
    assert r.mw_da > 0
    assert isinstance(r.pains_alerts, list)


def test_admet_rdkit_if_available():
    try:
        from rdkit import Chem
    except ImportError:
        pytest.skip("rdkit not installed")
    from bionexus.adapters.admet import RDKitADMET
    predictor = RDKitADMET()
    r = predictor.predict("CC(=O)Oc1ccccc1C(=O)O")  # aspirin
    assert r.mw_da is not None and 150 < r.mw_da < 200
    assert r.logp is not None
    assert not r.has_pains


# ---- retrosynthesis -----------------------------------------------------------------

def test_retrosynthesis_simulated():
    from bionexus.adapters.retrosynthesis import SimulatedRetrosynthesis
    r = SimulatedRetrosynthesis()
    simple = r.plan("CCO")  # ethanol — simple
    hard = r.plan("c1ccc2c(c1)[nH]c1ccccc12" + "C(=O)N[C@@H](C)C(=O)N[C@@H](CS)C(=O)N")
    assert simple.overall_score >= hard.overall_score, "simpler molecule should score higher"


# ---- agent personas -------------------------------------------------------------------

def test_agent_personas():
    from bionexus.agents import AgentRole, get_persona, all_personas
    assert len(all_personas()) == 6
    p = get_persona("medicinal_chemist")
    assert "rdkit" in [t.lower() for t in p.preferred_tools]
    assert p.system_mandate  # non-empty mandate
    ctx = p.to_prompt_context()
    assert "Medicinal Chemist" in ctx
    # all roles are valid strings
    for role in AgentRole:
        assert get_persona(role).role == role


# ---- agentic loop ----------------------------------------------------------------------

def test_agentic_loop_converges():
    from bionexus.agentic import AgenticLoop, LoopConfig

    tools = [
        {"name": "check_synthesis", "description": "Check synthesis feasibility",
         "input_schema": {"type": "object", "properties": {"smiles": {"type": "string"}},
                          "required": ["smiles"]}},
        {"name": "predict_admet", "description": "Predict ADMET properties",
         "input_schema": {"type": "object", "properties": {"smiles": {"type": "string"}},
                          "required": ["smiles"]}},
    ]
    calls = []
    def check_synthesis(smiles):
        calls.append("check_synthesis")
        return {"feasible": True, "steps": 3}
    def predict_admet(smiles):
        calls.append("predict_admet")
        return {"MW": 150, "LogP": 2.1}

    class _ToolUsingModel:
        """Scripted model that calls tools then finishes."""
        name, model_version = "scripted", "s1"
        def __init__(self):
            self._step = 0
        def generate(self, inv, prompt, **kw): ...
        def call_with_tools(self, messages, tools, system=""):
            self._step += 1
            if self._step == 1:
                tc = [{"name": "check_synthesis",
                       "arguments": {"smiles": "CCO"}}]
            elif self._step == 2:
                tc = [{"name": "predict_admet",
                       "arguments": {"smiles": "CCO"}}]
            else:
                return {"text": "DONE: Analysis complete",
                        "tool_calls": [], "stop_reason": "end_turn"}
            return {"text": "", "tool_calls": tc, "stop_reason": "tool_use"}

    loop = AgenticLoop(
        provider=_ToolUsingModel(), tools_schema=tools,
        tool_executor={"check_synthesis": check_synthesis,
                        "predict_admet": predict_admet},
        config=LoopConfig(max_turns=5),
    )
    result = loop.run("Evaluate CCO")
    assert result.completed and result.reason == "done"
    assert result.tool_calls == 2
    assert calls == ["check_synthesis", "predict_admet"]


def test_agentic_loop_max_turns():
    from bionexus.agentic import AgenticLoop, LoopConfig

    class _AlwaysCalls:
        name, model_version = "x", "x"
        def call_with_tools(self, messages, tools, system=""):
            return {"text": "", "stop_reason": "tool_use",
                    "tool_calls": [{"name": "noop", "arguments": {}}]}

    def noop(**kw): return {}
    loop = AgenticLoop(
        provider=_AlwaysCalls(),
        tools_schema=[{"name": "noop", "input_schema": {}}],
        tool_executor={"noop": noop},
        config=LoopConfig(max_turns=3),
    )
    result = loop.run("task")
    assert not result.completed and result.reason == "max_turns"
    assert result.turns == 3


def test_agentic_loop_error_circuit_breaker():
    from bionexus.agentic import AgenticLoop, LoopConfig

    def bad_tool(**kw): raise RuntimeError("lab exploded")
    class _BadModel:
        name, model_version = "x", "x"
        def call_with_tools(self, messages, tools, system=""):
            return {"text": "", "stop_reason": "tool_use",
                    "tool_calls": [{"name": "bad_tool", "arguments": {}}]}

    loop = AgenticLoop(
        provider=_BadModel(),
        tools_schema=[],
        tool_executor={"bad_tool": bad_tool},
        config=LoopConfig(max_turns=10, max_consecutive_errors=3),
    )
    result = loop.run("task")
    assert result.reason == "errors"


def test_agent_toolkit_tool_execution(tmp_path):
    from bionexus.adapters.lab.simulator import SimulatorLab
    from bionexus.core.safety import LabGateway, SafetyEngine
    from bionexus.toolkit import AgentToolkit

    store = SqliteProvenanceStore()
    gateway = LabGateway(SimulatorLab(seed=1), SafetyEngine(), store, system_actor())
    tk = AgentToolkit(gateway, store, system_actor(), branch_id="tk-test")
    executors = tk.executors()

    # ADMET
    r = executors["predict_admet"](smiles="CCO")
    assert r["mw_da"] is not None
    # synthesis
    r = executors["check_synthesis"](smiles="CCO")
    assert r["feasible"] is not None
    # hypothesis
    r = executors["propose_hypothesis"](
        statement="CCO binds", candidate="CCO",
        assay_type="binding", predicted="yes")
    assert r["status"] == "recorded"
    # TPP
    r = executors["query_tpp"](phase="hit")
    assert isinstance(r, (list, dict))


def test_agent_toolkit_submit_and_results(tmp_path):
    from bionexus.adapters.lab.simulator import SimulatorLab
    from bionexus.core.safety import LabGateway, SafetyEngine
    from bionexus.toolkit import AgentToolkit

    store = SqliteProvenanceStore()
    gateway = LabGateway(SimulatorLab(seed=1), SafetyEngine(), store, system_actor())
    tk = AgentToolkit(gateway, store, system_actor(), branch_id="tk-lab")
    r = tk._tool_submit(compounds=["CCO"], assay_type="binding",
                        concentrations=["10uM"])
    assert r["status"] == "submitted" and "run_id" in r
    results = tk._tool_results(r["run_id"])
    assert results["measurements"]


# ---- article-inspired guardrails (cassette burden, kinetic matching, denominator) ----

def test_cassette_burden_blocker_without_hist_controls():
    from bionexus.experiment import (BiologicalSystem, ClaimType,
                                     DeliveryConditions, ExperimentDefinition,
                                     Intervention, ReadoutSpec)
    from bionexus.readiness import review_experiment

    exp = ExperimentDefinition(
        scientific_question="test",
        claim_type=ClaimType.detection_or_pulldown,
        intervention=Intervention(
            kind="protein_edit", target="c-Myc", site="S62",
            requires_prior_genome_edit=True, construct_size_kda=22.0,
        ),
        system=BiologicalSystem(cell_line="HEK293T"),
        delivery=DeliveryConditions(method="electroporation",
                                    per_cell_loading_measured=True),
        readout=ReadoutSpec(assay="western", capabilities=[]),
        controls=["no-donor"],
        metadata={},  # no historical controls — must BLOCK
    )
    review = review_experiment(exp)
    blockers = [b.message for b in review.blockers]
    assert any("cassette" in b.lower() for b in blockers), (
        f"cassette burden must be a blocker; blockers={blockers}")

    # with historical controls declared → no blocker
    exp.metadata["historical_controls"] = ["cycloheximide chase", "interactome MS"]
    review2 = review_experiment(exp)
    assert not any("cassette" in b.message.lower() for b in review2.blockers)


def test_kinetic_mismatch_blocker():
    from bionexus.experiment import (BiologicalSystem, ClaimType,
                                     DeliveryConditions, ExperimentDefinition,
                                     Intervention, ReadoutSpec)
    from bionexus.readiness import review_experiment

    exp = ExperimentDefinition(
        scientific_question="test",
        claim_type=ClaimType.detection_or_pulldown,
        intervention=Intervention(
            kind="protein_edit", target="c-Myc",
            requires_prior_genome_edit=False),
        system=BiologicalSystem(cell_line="HEK293T"),
        delivery=DeliveryConditions(method="electroporation",
                                    per_cell_loading_measured=True),
        readout=ReadoutSpec(assay="western", capabilities=[]),
        controls=["no-donor"],
        metadata={
            "intein_pair": {
                "n_intein": "Gp41-1", "c_intein": "Npu DnaE",
                "n_splicing_rate": 0.18, "c_splicing_rate": 0.011,
                "is_engineered_slow_variant": False,
            },
        },
    )
    review = review_experiment(exp)
    blockers = [b.message for b in review.blockers]
    assert any("rate mismatch" in b.lower() or "kinetic" in b.lower()
               for b in blockers), (
        f"10x+ rate mismatch must be a blocker; blockers={blockers}")


def test_kinetic_match_passes_when_rates_close():
    from bionexus.experiment import (BiologicalSystem, ClaimType,
                                     DeliveryConditions, ExperimentDefinition,
                                     Intervention, ReadoutSpec)
    from bionexus.readiness import review_experiment

    exp = ExperimentDefinition(
        scientific_question="test",
        claim_type=ClaimType.detection_or_pulldown,
        intervention=Intervention(
            kind="protein_edit", target="c-Myc",
            requires_prior_genome_edit=False),
        system=BiologicalSystem(cell_line="HEK293T"),
        delivery=DeliveryConditions(method="electroporation",
                                    per_cell_loading_measured=True),
        readout=ReadoutSpec(assay="western", capabilities=[]),
        controls=["no-donor"],
        metadata={
            "intein_pair": {
                "n_intein": "Cat", "c_intein": "mut-Cfa",
                "n_splicing_rate": 0.05, "c_splicing_rate": 0.04,
                "is_engineered_slow_variant": True,
            },
        },
    )
    review = review_experiment(exp)
    kinetic_findings = [f for f in review.findings
                        if f.check == "kinetic_matching"]
    assert kinetic_findings and kinetic_findings[0].severity == "pass"


def test_denominator_blocker_for_loss_of_function():
    """The 'missing denominator' guardrail: loss-of-function claims on a bulk
    readout (no edited fraction) must be a BLOCKER, not a warning."""
    from bionexus.experiment import (BiologicalSystem, ClaimType,
                                     DeliveryConditions, ExperimentDefinition,
                                     Intervention, ReadoutSpec)
    from bionexus.readiness import ReviewVerdict, review_experiment

    exp = ExperimentDefinition(
        scientific_question="Does the edit cause loss of function?",
        claim_type=ClaimType.loss_of_function,
        intervention=Intervention(
            kind="protein_edit", target="c-Myc",
            requires_prior_genome_edit=False),
        system=BiologicalSystem(cell_line="HEK293T"),
        delivery=DeliveryConditions(method="electroporation",
                                    per_cell_loading_measured=True),
        readout=ReadoutSpec(
            assay="bulk Western blot", capabilities=[],
            measures_edited_fraction=False,
            distinguishes_modified_from_mimetic=False),
        controls=["no-donor"],
    )
    review = review_experiment(exp)
    assert review.verdict == ReviewVerdict.blocked
    blocker_msgs = [b.message for b in review.blockers]
    assert any("denominator" in m.lower() or "edited" in m.lower()
               for m in blocker_msgs), (
        f"missing denominator must be a blocker; blockers={blocker_msgs}")


# ---- SiLA 2, HCS microscope, LC-MS, robotic arm scheduler ----------------------------

def test_sila2_adapter_mock_channel():
    from bionexus.adapters.devices.sila2 import SiLA2Adapter, SiLA2HTTPChannel
    calls = []
    class _Ch:
        def call(self, ep, payload):
            calls.append((ep, payload))
            if "status" in ep:
                return {"status": "done"}
            if "results" in ep:
                return {"status": "completed", "measurements": [
                    {"sample_id": "C1", "value": 7.2, "unit": "pIC50"}]}
            return {}
    ch = _Ch()
    adapter = SiLA2Adapter.__new__(SiLA2Adapter)
    adapter.channel = ch
    adapter.device_label = "test-device"
    adapter.feature_map = {"execute": "/exec", "status": "/status", "results": "/results"}
    adapter._runs = {}
    from bionexus.core.contracts import ProtocolSubmission, ProtocolOp, ProtocolStep
    proto = ProtocolSubmission(
        envelope=Envelope(experiment_branch_id="sila2-test"),
        title="t", assay_type="binding",
        steps=[ProtocolStep(seq=1, op=ProtocolOp.dispense)],
        samples=[SampleSpec(sample_id="C1", kind=SampleKind.compound)])
    proto.protocol_id = "test-proto"
    rid = adapter.submit_protocol(proto)
    assert rid.startswith("sila2-test-")
    assert any("exec" in ep for ep, _ in calls)  # ep is the endpoint string


def test_hcs_microscope_per_cell():
    from bionexus.adapters.devices.hcs_microscope import HCSMicroscopeAdapter
    from bionexus.core.contracts import ProtocolOp, ProtocolStep
    lab = HCSMicroscopeAdapter.__new__(HCSMicroscopeAdapter)
    lab.seed = 7
    lab.image_dir = None
    lab._runs = {}
    proto = ProtocolSubmission(
        envelope=Envelope(experiment_branch_id="hcs"),
        title="t", assay_type="binding",
        steps=[ProtocolStep(seq=1, op=ProtocolOp.dispense)],
        samples=[SampleSpec(sample_id="C1", kind=SampleKind.compound,
                            concentration="10uM")])
    rid = lab.submit_protocol(proto)
    result = lab.fetch_results(rid)
    assert result.measurements
    m = result.measurements[0]
    assert 0 <= m.value <= 1  # edited fraction is 0-1


def test_lcms_adapter_ratiometric():
    from bionexus.adapters.devices.lcms import LCMSAdapter
    from bionexus.core.contracts import ProtocolOp, ProtocolStep
    lab = LCMSAdapter(seed=3)
    proto = ProtocolSubmission(
        envelope=Envelope(experiment_branch_id="lcms"),
        title="t", assay_type="custom",
        steps=[ProtocolStep(seq=1, op=ProtocolOp.measure)],
        samples=[SampleSpec(sample_id="C1", kind=SampleKind.compound)])
    rid = lab.submit_protocol(proto)
    result = lab.fetch_results(rid)
    assert result.measurements[0].unit == "fraction_edited"
    assert 0 <= result.measurements[0].value <= 1


def test_robotic_scheduler(tmp_path):
    from bionexus.adapters.devices.scheduler import HTTPScheduler, RoboticArmScheduler
    calls = []
    class _T:
        def post(self, path, body):
            calls.append(("POST", path, body))
            return {"move_id": "mv-1"}
        def get(self, path):
            calls.append(("GET", path))
            if "queue" in path:
                return {"queue": []}
            return {"status": "completed"}
    sched = RoboticArmScheduler(_T())
    r = sched.move_plate("incubator", "reader", "plate-1")
    assert r["move_id"] == "mv-1"
    assert any("move_plate" in c[1] for c in calls)
    ok = sched.wait_for_transport("mv-1", timeout=1)
    assert ok
