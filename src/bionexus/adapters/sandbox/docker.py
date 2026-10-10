"""Docker sandbox adapter — container-isolated experiment branches.

Maps the BioNexus Sandbox protocol onto Docker:

  create   docker run (detached, keepalive command)
  snapshot docker commit -> image tag (filesystem + process state as config)
  fork     docker run from the committed image
  resume   docker start
  destroy  docker rm -f

Isolation is real (separate filesystem/PID/network namespaces). Provenance is
recorded for every lifecycle transition. Transport is a thin CLI wrapper,
injectable for tests (P8): CI runs against a recorded/mock runner; live Docker
only changes the runner.

Requires Docker on the host; no Python docker SDK needed (stdlib subprocess).
"""
from __future__ import annotations

import json
import subprocess
import uuid
from typing import Any

from bionexus.core.contracts import EventType, Envelope
from bionexus.core.interfaces import ProvenanceStore, record_for


class DockerRunner:
    """Subprocess wrapper around the docker CLI (injectable in tests)."""

    def __init__(self, binary: str = "docker"):
        self.binary = binary

    def run(self, *args: str, input: str | None = None) -> str:
        result = subprocess.run(
            [self.binary, *args],
            input=input, capture_output=True, text=True, check=True)
        return result.stdout.strip()

    def run_capped(self, timeout: float, *args: str,
                   input: str | None = None):
        """Returns (returncode, stdout, client_timed_out); never raises.
        The exec path records outcomes BEFORE raising — failures belong on
        the chain as much as successes do."""
        try:
            r = subprocess.run([self.binary, *args], input=input,
                               capture_output=True, text=True,
                               timeout=timeout)
            return r.returncode, r.stdout.strip(), False
        except subprocess.TimeoutExpired:
            return 124, "", True

    def ok(self, *args: str) -> bool:
        try:
            self.run(*args)
            return True
        except subprocess.CalledProcessError:
            return False


class DockerSandbox:
    name = "docker"

    def __init__(self, image: str = "python:3.12-slim",
                 branch_id: str | None = None,
                 parent_branch_id: str | None = None,
                 store: ProvenanceStore | None = None,
                 actor: Any = None,
                 runner: DockerRunner | None = None,
                 env: dict[str, str] | None = None,
                 container_id: str | None = None,
                 network: str = "none",
                 memory: str = "512m",
                 cpus: str = "1.0",
                 pids_limit: int = 128):
        """Egress is closed by default (network='none'); caps dropped,
        memory/CPU/pid ceilings applied. An operator who needs outbound
        traffic must say so explicitly (network='bridge')."""
        self.runner = runner or DockerRunner()
        self.image = image
        self.network, self.memory, self.cpus, self.pids_limit = \
            network, memory, cpus, pids_limit
        self.branch_id = branch_id or f"docker-{uuid.uuid4().hex[:8]}"
        self.parent_branch_id = parent_branch_id
        self.store = store
        self.actor = actor
        self.env = env or {}
        self.snapshots: dict[str, str] = {}  # snapshot_id -> image tag
        if container_id:
            self.container_id = container_id
        else:
            self.container_id = self.runner.run(
                *self._create_args(image), "sleep", "infinity")
            self._record(EventType.sandbox_create,
                         {"type": "docker", "created": self.container_id,
                          "image": image, "sandbox_id": self.container_id,
                          "network": network, "memory": memory,
                          "cpus": cpus, "pids_limit": pids_limit})

    @property
    def sandbox_id(self) -> str:
        """Protocol identity: the container id *is* the sandbox id."""
        return self.container_id

    def _create_args(self, image: str) -> list[str]:
        args = ["run", "-d", "--rm",
                "--network", self.network,
                "--memory", self.memory,
                "--cpus", self.cpus,
                "--pids-limit", str(self.pids_limit),
                "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges",
                image]
        for k, v in self.env.items():
            args += ["-e", f"{k}={v}"]
        return args

    # -- Sandbox protocol ------------------------------------------------------

    def snapshot(self) -> str:
        """docker commit: the container filesystem becomes an image."""
        tag = f"bionexus/{self.branch_id.replace('/', '-')}:snap-{uuid.uuid4().hex[:8]}"
        self.runner.run("commit", self.container_id, tag)
        self.snapshots[tag] = tag
        self._record(EventType.sandbox_snapshot,
                     {"snapshot_image": tag, "container": self.container_id})
        return tag

    def fork(self, snapshot_id: str | None = None) -> "DockerSandbox":
        """New branch running from the committed snapshot image (or a clone
        of the live container's state via commit-then-run)."""
        image = snapshot_id or self.snapshot()
        child_branch = f"{self.branch_id}/d-{uuid.uuid4().hex[:6]}"
        child = DockerSandbox(
            image=image, branch_id=child_branch,
            parent_branch_id=self.branch_id,
            store=self.store, actor=self.actor, runner=self.runner,
            env=self.env, network=self.network, memory=self.memory,
            cpus=self.cpus, pids_limit=self.pids_limit)
        child._record(EventType.sandbox_fork,
                      {"parent_sandbox": self.container_id,
                       "from_image": image})
        # mirror on THIS branch: the parent's receipt must show its own forks
        self._record(EventType.sandbox_fork,
                     {"child_branch": child_branch,
                      "child_sandbox": child.container_id,
                      "from_image": image})
        return child

    def resume(self, snapshot_id: str | None = None) -> None:
        if snapshot_id:
            # recreate the container from the snapshot image, same hardening
            self.runner.run("rm", "-f", self.container_id)
            self.container_id = self.runner.run(
                *self._create_args(snapshot_id), "sleep", "infinity")
            self._record(EventType.sandbox_snapshot,
                         {"resumed_from": snapshot_id})

    def exec(self, command: str, *, timeout: float = 60.0,
             stdin_data: str | None = None) -> str:
        """Run a command inside the sandbox; returns stdout. An INNER
        `timeout` kills in-container orphans (killing only the docker-exec
        client would leave the process running); the outer client timeout
        is a backstop with grace. Every attempt is recorded BEFORE raising.
        Raises TimeoutError / RuntimeError after sealing."""
        from bionexus.adapters.sandbox import exec_decision
        inner = max(1, int(timeout))
        args = ["exec", *(["-i"] if stdin_data is not None else []),
                self.container_id,
                "timeout", "--kill-after=2", str(inner), "sh", "-c", command]
        rc, out, client_timed = self.runner.run_capped(
            timeout + 8, *args, input=stdin_data)
        timed_out = client_timed or rc == 124
        extra = {}
        if stdin_data is not None:
            import hashlib
            extra["input_sha256"] = hashlib.sha256(
                stdin_data.encode()).hexdigest()[:16]
        self._record(EventType.sandbox_exec,
                     exec_decision(self.sandbox_id, command,
                                   exit_code=rc, timed_out=timed_out,
                                   output=out, timeout=timeout, **extra))
        if timed_out:
            raise TimeoutError(f"sandbox exec timed out after {timeout}s")
        if rc != 0:
            raise RuntimeError(f"exec failed (exit {rc})")
        return out

    def destroy(self) -> None:
        self._record(EventType.sandbox_destroy,
                     {"sandbox_id": self.sandbox_id, "type": "docker",
                      "container": self.container_id})
        self.runner.run("rm", "-f", self.container_id)
        for tag in self.snapshots:
            try:
                self.runner.run("rmi", tag)
            except Exception:
                pass

    # -- provenance --------------------------------------------------------

    def _record(self, event: EventType, decision: dict) -> None:
        if self.store and self.actor:
            self.store.append(record_for(
                Envelope(experiment_branch_id=self.branch_id,
                         parent_branch_id=self.parent_branch_id),
                event, self.actor, decision=decision))
