"""S-T3 phase 1: SandboxSession routes tool invocations through a
sandboxed worker (bn sandboxd) — routing, provenance, and failure
honesty, on the dev-default LocalSandbox."""
import importlib.util

import pytest

from bionexus.adapters.store.sqlite import SqliteProvenanceStore
from bionexus.core.contracts import Envelope, ToolInvocation, ToolName
from bionexus.core.interfaces import system_actor
from bionexus.sandbox_session import SandboxSession


def _inv(smiles="CCO"):
    return ToolInvocation(
        envelope=Envelope(experiment_branch_id="prob-e2e"),
        tool=ToolName.fm_predict_property,
        args={"smiles": [smiles, "badsml"]})


def test_local_session_invokes_tool_e2e():
    store = SqliteProvenanceStore(":memory:")
    actor = system_actor("t")
    s = SandboxSession(mode="per_experiment", sandbox="local",
                       branch_id="prob-e2e", store=store, actor=actor)
    res = s.invoke(_inv())
    if importlib.util.find_spec("rdkit"):
        assert res.status == "succeeded"
        blob = str(res.output or {})
        assert "mol_wt" in blob and "CCO" in blob
    else:
        # rdkit-less venv: the worker must REJECT HONESTLY through the
        # transport — which still proves the round-trip end to end
        assert res.status == "rejected" and "rdkit" in (res.rejection_reason or "")
    events = {r.event_type.value for r in store.branch_records("prob-e2e")}
    assert {"sandbox_create", "sandbox_exec"} <= events
    s.destroy()


def test_registry_facade_routes_and_passthrough_matches():
    from bionexus.core.registry import Registry
    from bionexus.adapters.bio.rdkit_ops import MoleculeDescriptors
    inner = Registry()
    inner.register_tool(MoleculeDescriptors())
    store = SqliteProvenanceStore(":memory:")
    s = SandboxSession(mode="per_experiment", sandbox="local",
                       branch_id="prob-f", store=store,
                       actor=system_actor("t"))
    facaded = s.registry(inner)
    via_box = facaded.invoke(_inv("c1ccccc1"))
    direct = inner.invoke(_inv("c1ccccc1"))
    assert via_box.status == direct.status      # same outcome in or out
    assert via_box.output == direct.output
    if importlib.util.find_spec("rdkit"):
        assert via_box.status == "succeeded"
    off = SandboxSession(mode="off").registry(inner)
    assert off.invoke(_inv()).status == via_box.status  # same policy,
    # in-process and sandboxed — whatever rdkit availability dictates
    s.destroy()


def test_unknown_capability_fails_visibly_not_silently():
    store = SqliteProvenanceStore(":memory:")
    s = SandboxSession(mode="per_experiment", sandbox="local",
                       branch_id="prob-u", store=store,
                       actor=system_actor("t"))
    inv = ToolInvocation(
        envelope=Envelope(experiment_branch_id="prob-u"),
        tool=ToolName.fm_predict_property, args={"smiles": []})
    # force a lookup failure inside the worker: empty smiles -> succeeds
    # trivially, so instead break the transport: bogus python
    s.python = "/nonexistent/python"
    res = s.invoke(inv)
    assert res.status == "failed"
    assert "sandbox transport" in (res.rejection_reason or "")
    s.sandbox = None  # already dead exec env; skip destroy cleanup


def test_bad_sandbox_type_refuses_loudly():
    with pytest.raises(ValueError, match="lifecycle-only"):
        SandboxSession(mode="per_experiment", sandbox="agentenv")


def test_sandboxed_lab_matches_direct_simulator_exactly():
    from bionexus.adapters.lab.simulator import SimulatorLab
    from bionexus.core.contracts import (ProtocolOp, ProtocolStep,
                                         ProtocolSubmission, ReagentSpec,
                                         SampleKind, SampleSpec)
    from bionexus.sandbox_session import SandboxedLab
    proto = ProtocolSubmission(
        envelope=Envelope(experiment_branch_id="prob-l"), title="t",
        assay_type="binding",
        steps=[ProtocolStep(seq=1, op=ProtocolOp.dispense)],
        samples=[SampleSpec(sample_id="C1", kind=SampleKind.compound,
                            concentration="10 uM"),
                 SampleSpec(sample_id="C2", kind=SampleKind.compound,
                            concentration="1 uM")],
        reagents=[ReagentSpec(name="buffer", amount="1 mL", bsl_level=1)])

    direct = SimulatorLab(seed=11)
    rid = direct.submit_protocol(proto)
    ref = direct.fetch_results(rid)

    store = SqliteProvenanceStore(":memory:")
    s = SandboxSession(mode="per_experiment", sandbox="local",
                       branch_id="prob-l", store=store,
                       actor=system_actor("t"))
    box = SandboxedLab(s, seed=11)
    caps = box.list_capabilities()
    assert "binding" in caps["assays"]
    rid2 = box.submit_protocol(proto)
    assert rid2 == rid                       # deterministic ids match
    got = box.fetch_results(rid2)
    d1, d2 = got.model_dump(mode="json"), ref.model_dump(mode="json")
    for volatile in ("run_id", "envelope"):     # per-object uuids differ
        d1.pop(volatile), d2.pop(volatile)
    assert d1 == d2                             # measurements/QC: exact match
    assert box.get_status(rid2) == "done"
    # the chain saw every op — with the payload hashed, since the
    # COMMAND is constant now that the transport rides stdin
    ev = [r.decision for r in store.branch_records("prob-l")
          if r.event_type.value == "sandbox_exec"]
    assert len(ev) >= 3
    assert len({d.get("input_sha256") for d in ev}) >= 3
    s.destroy()


def test_sandboxed_lab_mirrors_autoloop_probe_surface():
    # regression: the campaign reads lab.true_ic50_um/_property_gate/
    # replicates when synthesizing plate exports; if these silently
    # disappear into the proxy, ground truth collapses to a constant
    # ladder and verdicts drift (caught by the host-vs-sandbox diff)
    from bionexus.adapters.lab.simulator import SimulatorLab
    from bionexus.core.contracts import (ProtocolOp, ProtocolStep,
                                         ProtocolSubmission, ReagentSpec,
                                         SampleKind, SampleSpec)
    from bionexus.sandbox_session import SandboxedLab
    proto = ProtocolSubmission(
        envelope=Envelope(experiment_branch_id="prob-p"), title="t",
        assay_type="binding",
        steps=[ProtocolStep(seq=1, op=ProtocolOp.dispense)],
        samples=[SampleSpec(sample_id="C1", kind=SampleKind.compound)],
        reagents=[ReagentSpec(name="buffer", amount="1 mL", bsl_level=1)])
    s = SandboxSession(mode="per_experiment", sandbox="local",
                       branch_id="prob-p", store=SqliteProvenanceStore(
                           ":memory:"), actor=system_actor("t"))
    box = SandboxedLab(s, seed=42)
    rid = box.submit_protocol(proto)
    assert box.true_ic50_um(rid, "C1") == \
        SimulatorLab(seed=42).true_ic50_um(rid, "C1")
    assert box.is_interferer(rid, "C1") == \
        SimulatorLab(seed=42).is_interferer(rid, "C1")
    assert box.replicates == 3
    assert box._property_gate is None
    box.set_property_gate("potency", "max", 0.8)
    assert box._property_gate == {"metric": "potency", "direction": "max",
                                  "threshold": 0.8}
    direct = SimulatorLab(seed=42)
    direct.set_property_gate("potency", "max", 0.8)
    assert box._property_true_value(rid, "C1") == \
        direct._property_true_value(rid, "C1")
    s.destroy()



def test_fork_diverges_and_session_cleans_up():
    store = SqliteProvenanceStore(":memory:")
    actor = system_actor("t")
    s = SandboxSession(mode="per_experiment", sandbox="local",
                       branch_id="prob-k", store=store, actor=actor)
    child = s.fork()
    assert child.sandbox is not s.sandbox
    child.sandbox.exec("echo x > f.txt")
    assert "f.txt" in child.sandbox.exec("ls")
    assert s.sandbox.exec("ls") == ""       # writes never flow back
    s.destroy()
    child.destroy()


def test_sandbox_receipt_read_model():
    from bionexus.views import _sandbox_summary
    store = SqliteProvenanceStore(":memory:")
    s = SandboxSession(mode="per_experiment", sandbox="local",
                       branch_id="prob-r", store=store,
                       actor=system_actor("t"))
    s.start()
    s.sandbox.exec("echo hi")
    s.destroy()
    info = _sandbox_summary(store.branch_records("prob-r"))
    assert info and info["type"] == "local" and info["execs"] >= 1
    assert info["destroyed"] and info["policy"] == {}
    # an ordinary chain without sandboxes renders nothing
    from bionexus.core.hypothesis import ProblemStatement
    assert _sandbox_summary(store.branch_records("nonexistent")) is None


def test_docker_transport_failure_never_kills_caller():
    # review fix: CalledProcessError-era escape hatch closed — rc!=0 AND
    # timeout both surface as FAILED results, and BOTH are recorded first
    from bionexus.core.contracts import (Envelope, ToolInvocation, ToolName)
    calls = []

    class FailingRunner:
        def run(self, *a, input=None):
            calls.append(list(a))
            return "cont-f"

        def run_capped(self, timeout, *a, input=None):
            return (1, "", False)

        def ok(self, *a):
            return True

    store = SqliteProvenanceStore(":memory:")
    s = SandboxSession(mode="per_experiment", sandbox="docker",
                       branch_id="prob-df", store=store,
                       actor=system_actor("t"), runner=FailingRunner())
    inv = ToolInvocation(
        envelope=Envelope(experiment_branch_id="prob-df"),
        tool=ToolName.fm_predict_property, args={"smiles": ["CCO"]})
    res = s.invoke(inv)
    assert res.status == "failed" and "exec failed" in res.rejection_reason
    ev = [r.decision for r in store.branch_records("prob-df")
          if r.event_type.value == "sandbox_exec"]
    assert ev and ev[-1]["exit_code"] == 1        # failure sealed BEFORE raise
    s.destroy()


def test_lab_state_honours_nondefault_config():
    # review fix: wrapping must not silently reset replicates/interference
    from bionexus.adapters.lab.simulator import SimulatorLab
    from bionexus.core.contracts import (ProtocolOp, ProtocolStep,
                                         ProtocolSubmission, ReagentSpec,
                                         SampleKind, SampleSpec)
    from bionexus.sandbox_session import SandboxedLab
    proto = ProtocolSubmission(
        envelope=Envelope(experiment_branch_id="prob-st"), title="t",
        assay_type="binding",
        steps=[ProtocolStep(seq=1, op=ProtocolOp.dispense)],
        samples=[SampleSpec(sample_id="C1", kind=SampleKind.compound,
                            concentration="10 uM")],
        reagents=[ReagentSpec(name="buffer", amount="1 mL", bsl_level=1)])
    real = SimulatorLab(seed=42, replicates=5, interference_rate=0.9)
    s = SandboxSession(mode="per_experiment", sandbox="local",
                       branch_id="prob-st", store=SqliteProvenanceStore(
                           ":memory:"), actor=system_actor("t"))
    box = SandboxedLab(s, lab=real)
    rid = box.submit_protocol(proto)
    got = box.fetch_results(rid).model_dump(mode="json")
    ref = real.fetch_results(real.submit_protocol(proto)).model_dump(mode="json")
    for volatile in ("run_id", "envelope"):
        got.pop(volatile), ref.pop(volatile)
    assert got == ref            # replicates=5, interference=0.9 carried in
    assert real.replicates == 5  # sanity: the config WAS non-default
    s.destroy()


def test_lab_wrapper_refuses_labs_it_cannot_transport():
    from bionexus.sandbox_session import SandboxedLab
    s = SandboxSession(mode="per_experiment", sandbox="local")
    s.start()

    class Robot:
        name = "opentrons"

    with pytest.raises(NotImplementedError, match="refusing to substitute"):
        SandboxedLab(s, lab=Robot())
    s.destroy()


def test_fork_appears_on_parent_receipt():
    from bionexus.views import _sandbox_summary
    store = SqliteProvenanceStore(":memory:")
    s = SandboxSession(mode="per_experiment", sandbox="local",
                       branch_id="prob-pf", store=store,
                       actor=system_actor("t"))
    s.start()
    s.fork()
    info = _sandbox_summary(store.branch_records("prob-pf"))
    assert info["forks"] >= 1
    s.destroy()


def test_stdin_transport_survives_big_payload():
    # review fix: payloads ride stdin, not argv — no ARG_MAX cliff
    from bionexus.core.contracts import (Envelope, ToolInvocation, ToolName)
    big = "C" * 200_000
    s = SandboxSession(mode="per_experiment", sandbox="local",
                       branch_id="prob-big",
                       store=SqliteProvenanceStore(":memory:"),
                       actor=system_actor("t"))
    inv = ToolInvocation(
        envelope=Envelope(experiment_branch_id="prob-big"),
        tool=ToolName.fm_predict_property, args={"smiles": [big]})
    res = s.invoke(inv)
    # whether rdkit exists or not, the TRANSPORT must have round-tripped:
    assert res.status in ("succeeded", "rejected") and "transport" not in (
        res.rejection_reason or "")
    s.destroy()
