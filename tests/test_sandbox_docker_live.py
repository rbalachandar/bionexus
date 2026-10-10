"""S-T3 2b: LIVE docker verification of the sandbox contract — the
mocked-runner era ends here. Every assertion asks the actual kernel/
cgroup/network namespace what it enforces. Skipped without a daemon;
under BN_REQUIRE_DOCKER=1 (CI job sandbox-docker) a missing daemon is
a hard failure: a silent skip is not a pass.
"""
import base64
import os
import shutil
import subprocess

import pytest

from bionexus.adapters.sandbox.docker import DockerSandbox
from bionexus.adapters.store.sqlite import SqliteProvenanceStore
from bionexus.core.interfaces import system_actor

IMAGE = "python:3.12-slim"


def _docker_up() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        r = subprocess.run(["docker", "info", "-f", "{{.ServerVersion}}"],
                           capture_output=True, timeout=60)
        return r.returncode == 0
    except Exception:
        return False


DOCKER = _docker_up()
if os.environ.get("BN_REQUIRE_DOCKER") and not DOCKER:
    raise RuntimeError(
        "BN_REQUIRE_DOCKER is set but no live docker daemon answered — "
        "2b must fail loudly, never skip quietly")

pytestmark = pytest.mark.skipif(
    not DOCKER or bool(os.environ.get("BN_SKIP_DOCKER")),
    reason="live docker daemon required (CI job: sandbox-docker; "
           "BN_SKIP_DOCKER=1 pins the fast jobs offline)")


@pytest.fixture(scope="module")
def image():
    subprocess.run(["docker", "pull", "-q", IMAGE], capture_output=True,
                   timeout=600)
    return IMAGE


def _sbx(branch, store=None, actor=None):
    return DockerSandbox(image=IMAGE, branch_id=branch,
                         store=store or SqliteProvenanceStore(":memory:"),
                         actor=actor or system_actor("live"))


def test_live_exec_runs_in_container(image):
    sbx = _sbx("live-echo")
    try:
        assert sbx.exec("echo ok") == "ok"
        out = sbx.exec("cat /proc/1/cmdline | tr '\\0' ' '")
        assert "sleep" in out           # pid 1 is OUR container, not the host
    finally:
        sbx.destroy()


def test_live_egress_denied_by_default(image):
    """The security aim in one probe: a socket connect out must fail."""
    probe = (
        "import socket\n"
        "s = socket.socket(); s.settimeout(3)\n"
        "try:\n"
        "    s.connect(('1.1.1.1', 443)); print('EGRESS_OK')\n"
        "except OSError:\n"
        "    print('EGRESS_BLOCKED')\n")
    b64 = base64.b64encode(probe.encode()).decode()
    sbx = _sbx("live-egress")
    try:
        out = sbx.exec(f"echo {b64} | base64 -d | python3")
        assert out == "EGRESS_BLOCKED"
    finally:
        sbx.destroy()


def test_live_caps_dropped_and_memory_ceiling(image):
    sbx = _sbx("live-caps")
    try:
        cap = sbx.exec("grep CapEff /proc/self/status")
        eff = cap.split()[-1]
        assert int(eff, 16) == 0, f"capabilities not dropped: {cap}"
        mem = sbx.exec(
            "cat /sys/fs/cgroup/memory.max 2>/dev/null "
            "|| cat /sys/fs/cgroup/memory/memory.limit_in_bytes 2>/dev/null")
        assert int(mem.strip()) == 512 * 1024 * 1024   # 512m ceiling
        # sethostname needs CAP_SYS_ADMIN — must be gone
        probe = ("import socket\n"
                 "try:\n"
                 "    socket.sethostname('escalated')\n"
                 "    print('ESCALATED')\n"
                 "except OSError:\n"
                 "    print('DENIED')\n")
        b64 = base64.b64encode(probe.encode()).decode()
        esc = sbx.exec(f"echo {b64} | base64 -d | python3")
        assert esc == "DENIED"
    finally:
        sbx.destroy()


def test_live_snapshot_fork_copy_on_write(image):
    parent = _sbx("live-parent")
    try:
        parent.exec("echo pinned > note.txt")
        tag = parent.snapshot()
        child = parent.fork(tag)
        try:
            assert child.exec("cat note.txt") == "pinned"   # COW inherited
            child.exec("echo only_child > kid.txt")
            assert "kid.txt" not in parent.exec("ls")       # never flows back
        finally:
            child.destroy()
    finally:
        parent.destroy()


def test_live_provenance_and_cleanup(image):
    store = SqliteProvenanceStore(":memory:")
    sbx = _sbx("live-prov", store=store)
    cid = sbx.container_id
    sbx.exec("echo hi")
    sbx.destroy()
    ev = [r.event_type.value for r in store.branch_records("live-prov")]
    assert "sandbox_create" in ev and "sandbox_exec" in ev \
        and "sandbox_destroy" in ev
    gone = subprocess.run(["docker", "inspect", cid],
                          capture_output=True, text=True)
    assert gone.returncode != 0     # container actually removed from daemon
