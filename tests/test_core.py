import json

import pytest

from bionexus.adapters.lab.simulator import SimulatorLab
from bionexus.adapters.models.openai_compat import OpenAICompatProvider
from bionexus.adapters.sandbox.local import LocalSandbox
from bionexus.adapters.store.sqlite import SqliteProvenanceStore
from bionexus.core.contracts import (
    Actor,
    Envelope,
    EventType,
    ProtocolOp,
    ProtocolStep,
    ProtocolSubmission,
    ReagentSpec,
    SampleKind,
    SampleSpec,
    ToolInvocation,
)
from bionexus.core.interfaces import system_actor
from bionexus.core.registry import Registry
from bionexus.core.safety import (
    ForbiddenComboRule,
    LabGateway,
    MaxBslRule,
    MaxStepsRule,
    SafetyEngine,
)
from bionexus.core.workflow import HypothesisTournament, StageGraph, TournamentConfig

BRANCH = "b-test"


def env() -> Envelope:
    return Envelope(experiment_branch_id=BRANCH)


def make_protocol(reagents=None, steps=1):
    return ProtocolSubmission(
        envelope=env(),
        title="t",
        assay_type="binding",
        steps=[ProtocolStep(seq=i + 1, op=ProtocolOp.dispense) for i in range(steps)],
        samples=[SampleSpec(sample_id="C1", kind=SampleKind.compound)],
        reagents=reagents or [ReagentSpec(name="buffer", amount="1 mL", bsl_level=1)],
    )


# ---- contracts ---------------------------------------------------------------

def test_envelope_and_ids_unique():
    a, b = env(), env()
    assert a.contract_id != b.contract_id
    assert a.schema_version == "v1"


def test_tool_name_registry_covers_all_blocks():
    from bionexus.core.contracts import ToolName
    vals = {t.value for t in ToolName}
    assert {v for v in vals if v.startswith("c.")}, "block C tools present"
    assert {v for v in vals if v.startswith("d.")}, "block D tools present"
    assert {v for v in vals if v.startswith("e.")}, "block E tools present"


# ---- provenance (P5) -----------------------------------------------------------

def test_provenance_hash_chain():
    from bionexus.core.contracts import Artifact, ArtifactKind
    from bionexus.core.interfaces import record_for

    store = SqliteProvenanceStore()
    actor = system_actor()
    r1 = store.append(record_for(env(), EventType.artifact_created, actor,
                                 artifact=Artifact(artifact_id="a1", kind=ArtifactKind.molecule, uri="mem://a1")))
    r2 = store.append(record_for(env(), EventType.artifact_created, actor,
                                 artifact=Artifact(artifact_id="a2", kind=ArtifactKind.report, uri="mem://a2")))
    assert r1.record_hash and r2.record_hash
    assert r2.prev_record_hash == r1.record_hash
    assert len(store.branch_records(BRANCH)) == 2


# ---- safety (P6) ----------------------------------------------------------------

def test_safety_blocks_bsl_and_combos():
    engine = SafetyEngine(rules=[MaxBslRule(1), ForbiddenComboRule([("acid*", "*hypochlorite*")])])
    ok, reason = engine.check(make_protocol())
    assert ok and reason is None
    ok, reason = engine.check(make_protocol([ReagentSpec(name="toxin", amount="1", bsl_level=3)]))
    assert not ok and "BSL" in reason
    ok, reason = engine.check(make_protocol([
        ReagentSpec(name="acid chloride", amount="1", bsl_level=1),
        ReagentSpec(name="sodium hypochlorite", amount="1", bsl_level=1),
    ]))
    assert not ok and "forbidden" in reason


def test_max_steps_rule():
    ok, reason = SafetyEngine(rules=[MaxStepsRule(2)]).check(make_protocol(steps=5))
    assert not ok


def test_lab_gateway_blocks_unsafe_and_records_runs():
    store = SqliteProvenanceStore()
    actor = system_actor()
    gw = LabGateway(SimulatorLab(), SafetyEngine(rules=[ForbiddenComboRule([("a", "b")])]), store, actor)
    run_id, reason = gw.submit(make_protocol([ReagentSpec(name="a", amount="1", bsl_level=1),
                                              ReagentSpec(name="b", amount="1", bsl_level=1)]))
    assert run_id is None and "forbidden" in reason
    run_id, reason = gw.submit(make_protocol())
    assert run_id and reason is None
    events = {r.event_type for r in store.branch_records(BRANCH)}
    assert EventType.lab_run in events


# ---- simulator (P4/P8) ----------------------------------------------------------

def test_simulator_deterministic_per_sample():
    lab_a, lab_b = SimulatorLab(seed=7), SimulatorLab(seed=7)
    p = make_protocol()
    ra, rb = lab_a.fetch_results(lab_a.submit_protocol(p)), lab_b.fetch_results(lab_b.submit_protocol(p))
    assert [m.value for m in ra.measurements] == [m.value for m in rb.measurements]
    assert ra.qc.controls_passed


# ---- sandbox fork/snapshot (P7) ---------------------------------------------------

def test_local_sandbox_fork_isolation():
    store = SqliteProvenanceStore()
    parent = LocalSandbox("root", state={"hits": ["A"]}, store=store, actor=system_actor())
    snap = parent.snapshot()
    child = parent.fork(snap)
    child.state["hits"].append("B")
    assert parent.state["hits"] == ["A"]
    assert child.parent_branch_id == "root"
    events = {r.event_type for r in store.branch_records(child.branch_id)}
    assert EventType.sandbox_fork in events


# ---- tournament (workflow) ---------------------------------------------------------

def test_tournament_ranks_and_prunes():
    cfg = TournamentConfig(population=6, survivors=2, waves=2)
    t = HypothesisTournament(model=None, config=cfg)
    pool = [{"id": i, "score": float(i)} for i in range(6)]
    survivors = t.run("b", {}, generate_fn=lambda ctx: pool, score_fn=lambda p: p["score"])
    assert [s["id"] for s in survivors] == [5, 4]


# ---- model adapter (P3) --------------------------------------------------------------

def test_stub_provider_deterministic_offline():
    provider = OpenAICompatProvider()  # no base_url -> stub mode
    inv = ToolInvocation(envelope=env(), tool="c.fm.generate_molecules")
    r1 = provider.generate(inv, "prompt-x", n=3)
    r2 = provider.generate(inv, "prompt-x", n=3)
    assert r1.output["text"] == r2.output["text"]
    assert r1.model_version == provider.model_version
    json.loads(r1.output["text"])  # valid JSON proposals


# ---- anti-bloat guardrail (P1): core imports only pydantic ---------------------------

def test_core_has_no_heavy_imports():
    import pathlib
    forbidden = ("requests", "numpy", "pandas", "torch", "langchain", "httpx", "sqlalchemy")
    core = pathlib.Path(__file__).parent.parent / "src" / "bionexus" / "core"
    for py in core.rglob("*.py"):
        src = py.read_text()
        for bad in forbidden:
            assert f"import {bad}" not in src, f"{py.name} imports forbidden '{bad}'"
