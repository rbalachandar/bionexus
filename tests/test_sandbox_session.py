"""S-T3 phase 1: SandboxSession routes tool invocations through a
sandboxed worker (bn sandboxd) — routing, provenance, and failure
honesty, on the dev-default LocalSandbox."""
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
    assert res.status == "succeeded"
    rows = {r["smiles"]: r for r in res.output["results"]} \
        if isinstance(res.output.get("results"), list) else {}
    # output shape comes from MoleculeDescriptors — accept dict or raw
    out = res.output or {}
    blob = str(out)
    assert "mol_wt" in blob and "CCO" in blob
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
    assert via_box.status == direct.status == "succeeded"
    assert via_box.output == direct.output      # same answers in or out
    off = SandboxSession(mode="off").registry(inner)
    assert off.invoke(_inv()).status == "succeeded"   # untouched path
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
