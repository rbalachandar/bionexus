"""S-T3 seam: Sandbox.exec contract — local execution, provenance,
isolation, docker hardening args, honest degradation."""
import pytest

from bionexus.adapters.sandbox.agentenv import AgentEnvSandbox
from bionexus.adapters.sandbox.docker import DockerSandbox
from bionexus.adapters.sandbox.local import LocalSandbox
from bionexus.adapters.store.sqlite import SqliteProvenanceStore
from bionexus.core.interfaces import system_actor


@pytest.fixture()
def sa():
    store = SqliteProvenanceStore(":memory:")
    return store, system_actor("t")


def test_local_exec_runs_and_records(sa):
    store, actor = sa
    sb = LocalSandbox(branch_id="root", store=store, actor=actor)
    out = sb.exec("echo hi && pwd")
    assert out.startswith("hi") and "/work" in out
    ev = [r for r in store.branch_records("root")
          if r.event_type.value == "sandbox_exec"]
    assert len(ev) == 1
    d = ev[0].decision
    assert d["exit_code"] == 0 and len(d["command_sha256"]) == 16
    sb.destroy()


def test_local_exec_isolation_between_sandboxes(sa):
    store, actor = sa
    a = LocalSandbox(branch_id="a", store=store, actor=actor)
    b = LocalSandbox(branch_id="b", store=store, actor=actor)
    a.exec("echo secret > token.txt")
    assert b.exec("ls") == ""           # b cannot see a's files
    with pytest.raises(RuntimeError):
        b.exec("cat token.txt")
    a.destroy()
    b.destroy()


def test_local_fork_inherits_files_then_diverges(sa):
    store, actor = sa
    parent = LocalSandbox(branch_id="p", store=store, actor=actor)
    parent.exec("echo base > shared.txt")
    child = parent.fork()
    assert "base" in child.exec("cat shared.txt")
    child.exec("echo mine > only_child.txt")
    assert parent.exec("ls") == "shared.txt"   # writes never flow back
    parent.destroy()
    child.destroy()


def test_local_exec_timeout_raises_and_records(sa):
    store, actor = sa
    sb = LocalSandbox(branch_id="to", store=store, actor=actor)
    with pytest.raises(TimeoutError):
        sb.exec("sleep 5", timeout=0.3)
    ev = [r.decision for r in store.branch_records("to")
          if r.event_type.value == "sandbox_exec"]
    assert ev and ev[-1]["timed_out"] is True
    sb.destroy()


def test_docker_create_args_are_hardened():
    calls = []

    class FakeRunner:
        binary = "docker"

        def run(self, *args, input=None):
            calls.append(list(args))
            return "cont-9"

        def run_with_timeout(self, timeout, *args):
            calls.append(["TIMEOUT", timeout] + list(args))
            return "out"

        def ok(self, *args):
            return True

    store = SqliteProvenanceStore(":memory:")
    actor = system_actor("t")
    sb = DockerSandbox(branch_id="d", store=store, actor=actor,
                       runner=FakeRunner())
    create = calls[0]
    for flag in ("--network", "none", "--memory", "--cpus", "--pids-limit",
                 "--cap-drop", "ALL", "--security-opt", "no-new-privileges"):
        assert flag in create, f"missing {flag}"
    assert [r.event_type.value for r in store.branch_records("d")][0] \
        == "sandbox_create"
    sb.exec("echo hi", timeout=5)
    exec_call = [c for c in calls if c and c[0] == "TIMEOUT"][-1]
    assert exec_call[1] == 5 and "exec" in exec_call
    ev = [r.decision for r in store.branch_records("d")
          if r.event_type.value == "sandbox_exec"]
    assert ev and ev[0]["output_chars"] == 3


def test_agentenv_exec_refuses_loudly():
    class DeadClient:
        def create(self, template_id, metadata=None):
            return {"sandboxID": "x1"}

    sb = AgentEnvSandbox(client=DeadClient(), branch_id="ae")
    with pytest.raises(NotImplementedError):
        sb.exec("echo hi")
