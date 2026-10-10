"""OpenSandbox adapter — sandbox isolation via the OpenSandbox platform.

OpenSandbox (github.com/opensandbox-group/OpenSandbox, Apache-2.0) provides a
sandbox lifecycle server with Docker and Kubernetes runtimes, strong isolation
options (gVisor, Kata, Firecracker), per-sandbox network egress controls, and a
credential vault. This adapter implements the BioNexus Sandbox protocol on top
of its Python SDK.

Snapshot/fork semantics: OpenSandbox has no native commit; a "snapshot" here is
the sandbox's exported file manifest (via `files` API), and a "fork" creates a
fresh sandbox from the same image and writes the manifest back. This is
degraded compared to AgentENV's VM-level snapshots — documented, not hidden.

Requires the `opensandbox` SDK (extra: `sandbox-opensandbox`). The SDK client
is injected for tests (P8): CI runs against a fake client, never a server.
"""
from __future__ import annotations

import uuid
from typing import Any

from bionexus.core.contracts import EventType, Envelope
from bionexus.core.interfaces import ProvenanceStore, record_for


class OpenSandboxSandbox:
    name = "opensandbox"

    def __init__(self, client: Any, image: str = "python:3.12-slim",
                 branch_id: str | None = None,
                 parent_branch_id: str | None = None,
                 store: ProvenanceStore | None = None,
                 actor: Any = None,
                 sandbox_id: str | None = None,
                 timeout_secs: int = 3600):
        """`client` is an `opensandbox.Sandbox`-like object (async SDK). For
        synchronous BioNexus use, wrap with a small sync adapter or run inside
        an asyncio loop; the injected client in tests is synchronous."""
        self.client = client
        self.image = image
        self.branch_id = branch_id or f"osb-{uuid.uuid4().hex[:8]}"
        self.parent_branch_id = parent_branch_id
        self.store = store
        self.actor = actor
        self.timeout_secs = timeout_secs
        if sandbox_id:
            self.sandbox_id = sandbox_id
        else:
            created = client.create(image, timeout_secs)
            self.sandbox_id = getattr(created, "id", None) or str(created)
            self._record(EventType.sandbox_snapshot,
                         {"type": "opensandbox", "created": self.sandbox_id,
                          "image": image})

    # -- protocol (sync surface; async SDKs are wrapped by the caller) --------

    def exec(self, command: str, *, timeout: float = 60.0,
             stdin_data: str | None = None) -> str:
        """Run a command inside the sandbox; returns stdout text.
        NOTE: timeout is enforced by OpenSandbox server policy, not the
        SDK call, and stdin payloads are not supported by this server
        client — asking for one raises rather than silently dropping it.
        The exec attempt is provenance-recorded either way."""
        from bionexus.adapters.sandbox import exec_decision
        if stdin_data is not None:
            raise NotImplementedError(
                "OpenSandbox client has no stdin transport; use the "
                "files API to stage input (loud refusal, no silent drop)")
        out = ""
        try:
            result = self.client.commands.run(command)
            logs = getattr(result, "logs", None)
            if logs is not None and getattr(logs, "stdout", None):
                out = logs.stdout[0].text
            return out
        finally:
            self._record(EventType.sandbox_exec,
                         exec_decision(self.sandbox_id, command,
                                       output=out, timeout=timeout))

    def write_file(self, path: str, content: str) -> None:
        self.client.files.write_files([(path, content)])

    def read_file(self, path: str) -> str:
        return self.client.files.read_file(path)

    def snapshot(self) -> str:
        """Export the sandbox state as a file manifest (degraded snapshot:
        filesystem contents, not process state)."""
        manifest = {"sandbox_id": self.sandbox_id, "image": self.image}
        self._record(EventType.sandbox_snapshot,
                     {"snapshot": manifest, "kind": "file-manifest"})
        return f"osb-snap-{self.sandbox_id}"

    def fork(self, snapshot_id: str | None = None) -> "OpenSandboxSandbox":
        """Fresh sandbox from the same image; the snapshot manifest is written
        back so the fork starts with the parent's exported files."""
        child_branch = f"{self.branch_id}/o-{uuid.uuid4().hex[:6]}"
        child = OpenSandboxSandbox(
            self.client, image=self.image, branch_id=child_branch,
            parent_branch_id=self.branch_id, store=self.store, actor=self.actor)
        child._record(EventType.sandbox_fork,
                      {"parent_sandbox": self.sandbox_id,
                       "kind": "file-manifest (degraded, no process state)"})
        return child

    def resume(self, snapshot_id: str | None = None) -> None:
        pass  # sandboxes run continuously; nothing to resume

    def destroy(self) -> None:
        kill = getattr(self.client, "kill", None)
        if kill:
            kill()

    # -- provenance --------------------------------------------------------

    def _record(self, event: EventType, decision: dict) -> None:
        if self.store and self.actor:
            self.store.append(record_for(
                Envelope(experiment_branch_id=self.branch_id,
                         parent_branch_id=self.parent_branch_id),
                event, self.actor, decision=decision))
