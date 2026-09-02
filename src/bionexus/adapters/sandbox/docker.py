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
                 container_id: str | None = None):
        self.runner = runner or DockerRunner()
        self.image = image
        self.branch_id = branch_id or f"docker-{uuid.uuid4().hex[:8]}"
        self.parent_branch_id = parent_branch_id
        self.store = store
        self.actor = actor
        self.env = env or {}
        self.snapshots: dict[str, str] = {}  # snapshot_id -> image tag
        if container_id:
            self.container_id = container_id
        else:
            args = ["run", "-d", "--rm", image]
            for k, v in self.env.items():
                args += ["-e", f"{k}={v}"]
            args += ["sleep", "infinity"]
            self.container_id = self.runner.run(*args)
            self._record(EventType.sandbox_fork if parent_branch_id
                         else EventType.sandbox_snapshot,
                         {"created": self.container_id})

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
            env=self.env)
        child._record(EventType.sandbox_fork,
                      {"parent_sandbox": self.container_id,
                       "from_image": image})
        return child

    def resume(self, snapshot_id: str | None = None) -> None:
        if snapshot_id:
            # recreate the container from the snapshot image
            self.runner.run("rm", "-f", self.container_id)
            self.container_id = self.runner.run(
                "run", "-d", "--rm", snapshot_id, "sleep", "infinity")
            self._record(EventType.sandbox_snapshot,
                         {"resumed_from": snapshot_id})

    def exec(self, command: str) -> str:
        """Run a command inside the sandbox; returns stdout."""
        return self.runner.run("exec", self.container_id, "sh", "-c", command)

    def destroy(self) -> None:
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
