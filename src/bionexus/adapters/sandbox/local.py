"""Local in-process sandbox with copy-on-fork state (P7, degraded mode).

Real fork/snapshot comes from the AgentENV adapter (roadmap T4.2). This adapter
keeps the interface honest so workflows are sandbox-agnostic, and deep-copies
user state on fork/snapshot so experiments remain isolated in tests.
"""
from __future__ import annotations

import copy
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
        self.branch_id = branch_id
        self.parent_branch_id = parent_branch_id
        self.state: dict[str, Any] = state or {}
        self._store = store
        self._actor = actor
        self._snapshots = _snapshots if _snapshots is not None else {}

    def snapshot(self) -> str:
        snap_id = f"snap-{uuid.uuid4().hex[:8]}"
        self._snapshots[snap_id] = copy.deepcopy(self.state)
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

    def destroy(self) -> None:
        self.state = {}


def _env(branch_id: str, parent: str | None):
    from bionexus.core.contracts import Envelope

    return Envelope(experiment_branch_id=branch_id, parent_branch_id=parent)
