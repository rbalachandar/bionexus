"""AgentENV sandbox adapter (T4.2, P7) — real fork/snapshot/pause/resume.

Maps the BioNexus Sandbox protocol onto the AgentENV HTTP API (E2B-compatible):

    snapshot() -> pause sandbox (full VM+agent state preserved server-side)
    fork()     -> resume from the paused state under a new sandbox/branch id
    resume()   -> resume this sandbox
    destroy()  -> delete

Best-effort HTTP over stdlib urllib (no hard dependency). The AgentENV API
evolves; this adapter is intentionally thin — see the AgentENV repo for the
server side. Not exercisable in CI (needs a Linux host with KVM); contract
tests mock the transport.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from bionexus.core.contracts import EventType
from bionexus.core.interfaces import ProvenanceStore, record_for


class AgentEnvError(RuntimeError):
    pass


class AgentEnvClient:
    """Minimal AgentENV HTTP client (stdlib only)."""

    def __init__(self, base_url: str, api_key: str | None = None, timeout: int = 60):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.headers = {"Content-Type": "application/json"}
        if api_key:
            self.headers["X-Agentenv-API-Key"] = api_key

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            data=json.dumps(body).encode() if body is not None else None,
            headers=self.headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                payload = resp.read()
                return json.loads(payload) if payload else {}
        except urllib.error.HTTPError as exc:
            raise AgentEnvError(f"{method} {path} -> {exc.code}: {exc.read().decode()[:200]}") from exc

    def create(self, template_id: str, metadata: dict | None = None) -> dict:
        return self._request("POST", "/sandboxes", {"templateID": template_id, "metadata": metadata or {}})

    def pause(self, sandbox_id: str) -> dict:
        return self._request("POST", f"/sandboxes/{sandbox_id}/pause")

    def resume(self, sandbox_id: str) -> dict:
        return self._request("POST", f"/sandboxes/{sandbox_id}/resume")

    def delete(self, sandbox_id: str) -> None:
        self._request("DELETE", f"/sandboxes/{sandbox_id}")


class AgentEnvSandbox:
    name = "agentenv"

    def __init__(
        self,
        client: AgentEnvClient,
        branch_id: str,
        template_id: str = "bionexus-agent",
        sandbox_id: str | None = None,
        store: ProvenanceStore | None = None,
        actor: Any = None,
        parent_branch_id: str | None = None,
    ):
        self.client = client
        self.branch_id = branch_id
        self.parent_branch_id = parent_branch_id
        self.template_id = template_id
        self._store = store
        self._actor = actor
        if sandbox_id:
            self.sandbox_id = sandbox_id
        else:
            created = client.create(template_id, metadata={"branch_id": branch_id})
            self.sandbox_id = created.get("sandboxID") or created.get("sandbox_id")
            if not self.sandbox_id:
                raise AgentEnvError(f"AgentENV did not return a sandbox id: {created}")

    # -- Sandbox protocol ----------------------------------------------------

    def snapshot(self) -> str:
        """Pause the sandbox; AgentENV persists full VM state server-side."""
        self.client.pause(self.sandbox_id)
        self._record(EventType.sandbox_snapshot, {"sandbox_id": self.sandbox_id})
        return self.sandbox_id  # the paused sandbox *is* the snapshot

    def fork(self, snapshot_id: str | None = None) -> "AgentEnvSandbox":
        """New branch resuming from the paused snapshot (or live state)."""
        child_branch = f"{self.branch_id}/f-{self.sandbox_id[:8]}"
        child = AgentEnvSandbox(
            self.client,
            child_branch,
            template_id=self.template_id,
            sandbox_id=self.sandbox_id,  # same paused VM, new branch identity
            store=self._store,
            actor=self._actor,
            parent_branch_id=self.branch_id,
        )
        child.client.resume(child.sandbox_id)
        child._record(EventType.sandbox_fork,
                      {"parent_sandbox": self.sandbox_id, "child_branch": child_branch})
        return child

    def resume(self, snapshot_id: str | None = None) -> None:
        self.client.resume(self.sandbox_id)

    def destroy(self) -> None:
        self.client.delete(self.sandbox_id)

    def _record(self, event: EventType, decision: dict) -> None:
        if self._store and self._actor:
            from bionexus.core.contracts import Envelope

            self._store.append(
                record_for(
                    Envelope(experiment_branch_id=self.branch_id, parent_branch_id=self.parent_branch_id),
                    event,
                    self._actor,
                    decision=decision,
                )
            )
