"""SandboxSession — the opt-in execution boundary for one experiment (S-T3).

cfg: sandbox: {mode: off|per_experiment, type: local|docker}
mode=off (default) changes nothing: registries execute in-process.
mode=per_experiment wraps ONE sandbox around the experiment; every BioTool
invocation routed through session.registry() executes INSIDE the sandbox
via `bn sandboxd` (see sandboxd.py), with create/exec/fork/destroy
provenance recorded by the adapters on the experiment branch.

Failure policy: a sandboxed tool call that cannot be transported returns
a FAILED ToolResult (visible in the chain) — never a silent in-process
fallback, and never an exception that kills the campaign.
"""
from __future__ import annotations

import base64
import json
import sys
from typing import Any

from bionexus.core.contracts import ToolResult


class SandboxSession:
    def __init__(self, mode: str = "per_experiment", sandbox: str = "local",
                 branch_id: str = "campaign", store: Any = None,
                 actor: Any = None, image: str | None = None,
                 python: str | None = None, runner: Any = None):
        self.mode = mode
        self.kind = sandbox
        self.store = store
        self.actor = actor
        self.sandbox = None
        if mode == "off":
            return
        if mode != "per_experiment":
            raise ValueError(f"unknown sandbox mode '{mode}' "
                             "(off | per_experiment; per_run is roadmap)")
        if sandbox == "local":
            from bionexus.adapters.sandbox.local import LocalSandbox
            self.sandbox = LocalSandbox(branch_id=branch_id, store=store,
                                        actor=actor)
            self.python = python or sys.executable
        elif sandbox == "docker":
            from bionexus.adapters.sandbox.docker import DockerSandbox
            self.sandbox = DockerSandbox(
                image=image or "python:3.12-slim", branch_id=branch_id,
                store=store, actor=actor, runner=runner)
            self.python = python or "python3"
        else:
            raise ValueError(
                f"sandbox type '{sandbox}' not supported for execution "
                "(local | docker; agentenv is lifecycle-only, opensandbox "
                "needs a live server) — loud refusal, no silent fallback")

    # ------------------------------------------------------------- routing

    def registry(self, inner: Any = None):
        """Facade over Registry: same surface, invoke() routed through
        the sandbox when enabled."""
        from bionexus.core.registry import Registry
        inner = inner or Registry()
        session = self

        class _SessionRegistry:
            def invoke(self, invocation):
                if session.sandbox is None:
                    return inner.invoke(invocation)
                return session.invoke(invocation)

            def __getattr__(self, item):
                return getattr(inner, item)

        return _SessionRegistry()

    def invoke(self, invocation) -> ToolResult:
        from bionexus.core.contracts import ToolInvocation
        req = {"invocation": invocation.model_dump(mode="json")}
        b64 = base64.b64encode(json.dumps(req).encode()).decode()
        cmd = f"{self.python} -m bionexus.sandboxd --request-b64 {b64}"
        try:
            out = self.sandbox.exec(cmd,
                                    timeout=invocation.timeout_secs + 15)
            data = json.loads(out)
            if "error" in data:
                return ToolResult(
                    envelope=invocation.envelope,
                    invocation_id=invocation.invocation_id,
                    status="failed",
                    rejection_reason=f"sandboxd: {data['error']}")
            return ToolResult.model_validate(data)
        except (TimeoutError, RuntimeError, json.JSONDecodeError) as e:
            return ToolResult(
                envelope=invocation.envelope,
                invocation_id=invocation.invocation_id,
                status="failed",
                rejection_reason=f"sandbox transport: {str(e)[:200]}")

    # ----------------------------------------------------------- lifecycle

    def snapshot(self) -> str | None:
        return self.sandbox.snapshot() if self.sandbox else None

    def fork(self) -> "SandboxSession":
        """per_run mode (roadmap): child experiment runs from this state;
        writes never flow back."""
        if not self.sandbox:
            raise RuntimeError("cannot fork an off-mode session")
        child = SandboxSession(mode="off")
        child.mode = "per_experiment"
        child.kind = self.kind
        child.python = self.python
        child.store, child.actor = self.store, self.actor
        child.sandbox = self.sandbox.fork()
        return child

    def destroy(self) -> None:
        if self.sandbox:
            self.sandbox.destroy()
            self.sandbox = None
