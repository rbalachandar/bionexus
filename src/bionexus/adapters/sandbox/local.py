"""Local sandbox with copy-on-fork state (P7, degraded mode).

Process isolation, NOT a security boundary: exec() runs commands in a
subprocess whose private temp working directory no other sandbox sees,
but the OS user, network, and resources are unconfined. For real
isolation use DockerSandbox (egress closed, caps dropped, ceilings set)
or AgentENV (VM-level snapshots). Kept as the dev default so workflows
stay sandbox-agnostic and forks deep-copy both state and files.
"""
from __future__ import annotations

import copy
import hashlib
import os
import shutil
import subprocess
import tempfile
import uuid
from typing import Any

from bionexus.core.contracts import EventType
from bionexus.core.interfaces import ProvenanceStore, record_for


class LocalSandbox:
    name = "local"

    def __init__(
        self,
        branch_id: str,
        state: dict[str, Any] | None = None,
        parent_branch_id: str | None = None,
        store: ProvenanceStore | None = None,
        actor: Any = None,
        _snapshots: dict[str, dict[str, Any]] | None = None,
    ):
        self.sandbox_id = f"local-{uuid.uuid4().hex[:8]}"
        self._root = tempfile.mkdtemp(prefix=f"bnx-{self.sandbox_id}-")
        self.workdir = f"{self._root}/work"
        os.makedirs(self.workdir, exist_ok=True)
        self.branch_id = branch_id
        self.parent_branch_id = parent_branch_id
        self.state: dict[str, Any] = state or {}
        self._store = store
        self._actor = actor
        self._snapshots = _snapshots if _snapshots is not None else {}
        self._record(EventType.sandbox_create,
                     {"sandbox_id": self.sandbox_id, "type": "local",
                      "workdir_under": self._root})

    def snapshot(self) -> str:
        snap_id = f"snap-{uuid.uuid4().hex[:8]}"
        self._snapshots[snap_id] = copy.deepcopy(self.state)
        shutil.copytree(self.workdir, f"{self._root}/{snap_id}",
                        dirs_exist_ok=True)
        if self._store and self._actor:
            self._store.append(
                record_for(
                    _env(self.branch_id, self.parent_branch_id),
                    EventType.sandbox_snapshot,
                    self._actor,
                    decision={"snapshot_id": snap_id, "sandbox_id": self.sandbox_id},
                )
            )
        return snap_id

    def fork(self, snapshot_id: str | None = None) -> "LocalSandbox":
        state = copy.deepcopy(self._snapshots[snapshot_id]) if snapshot_id else copy.deepcopy(self.state)
        child_branch = f"{self.branch_id}/f-{uuid.uuid4().hex[:6]}"
        child = LocalSandbox(
            branch_id=child_branch,
            state=state,
            parent_branch_id=self.branch_id,
            store=self._store,
            actor=self._actor,
            _snapshots=self._snapshots,
        )
        src = (f"{self._root}/{snapshot_id}" if snapshot_id
               else self.workdir)
        if os.path.isdir(src):
            shutil.copytree(src, child.workdir, dirs_exist_ok=True)
        if self._store and self._actor:
            self._store.append(
                record_for(
                    _env(child_branch, self.branch_id),
                    EventType.sandbox_fork,
                    self._actor,
                    decision={"parent_sandbox": self.sandbox_id, "child_sandbox": child.sandbox_id},
                )
            )
        return child

    def resume(self, snapshot_id: str | None = None) -> None:
        if snapshot_id:
            self.state = copy.deepcopy(self._snapshots[snapshot_id])

    def exec(self, command: str, *, timeout: float = 60.0) -> str:
        """Run a command in a subprocess inside this sandbox's private
        workdir. Raises on nonzero exit / timeout; either way the attempt
        is provenance-recorded. Process isolation only — see module
        docstring for the security posture."""
        sha = hashlib.sha256(command.encode()).hexdigest()[:16]
        try:
            r = subprocess.run(["sh", "-c", command], cwd=self.workdir,
                               capture_output=True, text=True,
                               timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            self._record(EventType.sandbox_exec,
                         {"sandbox_id": self.sandbox_id,
                          "command_sha256": sha, "timed_out": True,
                          "timeout": timeout})
            raise TimeoutError(f"sandbox exec timed out after {timeout}s")
        self._record(EventType.sandbox_exec,
                     {"sandbox_id": self.sandbox_id, "command_sha256": sha,
                      "exit_code": r.returncode, "timed_out": False,
                      "output_chars": len(r.stdout)})
        if r.returncode != 0:
            raise RuntimeError(
                f"exec failed (exit {r.returncode}): {r.stderr[:200]}")
        return r.stdout.strip()

    def destroy(self) -> None:
        self._record(EventType.sandbox_destroy,
                     {"sandbox_id": self.sandbox_id, "type": "local"})
        self.state = {}
        shutil.rmtree(self._root, ignore_errors=True)


    def _record(self, event, decision: dict) -> None:
        if self._store and self._actor:
            self._store.append(record_for(
                _env(self.branch_id, self.parent_branch_id), event,
                self._actor, decision=decision))


def _env(branch_id: str, parent: str | None):
    from bionexus.core.contracts import Envelope

    return Envelope(experiment_branch_id=branch_id, parent_branch_id=parent)
