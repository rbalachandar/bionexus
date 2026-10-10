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
        """Config validated eagerly; the sandbox itself is created on
        start() — the owner (e.g. run_campaign) binds the final branch."""
        self.mode = mode
        self.kind = sandbox
        self.branch_id = branch_id
        self.store = store
        self.actor = actor
        self.image = image
        self.runner = runner
        self.python = python
        self.sandbox = None
        if mode == "off":
            return
        if mode != "per_experiment":
            raise ValueError(f"unknown sandbox mode '{mode}' "
                             "(off | per_experiment; per_run is roadmap)")
        if sandbox not in ("local", "docker"):
            raise ValueError(
                f"sandbox type '{sandbox}' not supported for execution "
                "(local | docker; agentenv is lifecycle-only, opensandbox "
                "needs a live server) — loud refusal, no silent fallback")

    def start(self, branch_id: str | None = None):
        """Create the sandbox (once); branch defaults to the configured
        one. Returns the session for chaining."""
        if self.mode == "off" or self.sandbox is not None:
            return self
        branch = branch_id or self.branch_id
        if self.kind == "local":
            from bionexus.adapters.sandbox.local import LocalSandbox
            self.sandbox = LocalSandbox(branch_id=branch, store=self.store,
                                        actor=self.actor)
            self.python = self.python or sys.executable
        else:
            from bionexus.adapters.sandbox.docker import DockerSandbox
            self.sandbox = DockerSandbox(
                image=self.image or "python:3.12-slim", branch_id=branch,
                store=self.store, actor=self.actor, runner=self.runner)
            self.python = self.python or "python3"
        return self

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
        data = self.call({"invocation": invocation.model_dump(mode="json")},
                         timeout=invocation.timeout_secs + 15)
        if data is None or "error" in data:
            return ToolResult(
                envelope=invocation.envelope,
                invocation_id=invocation.invocation_id,
                status="failed",
                rejection_reason="sandbox transport: "
                                 + (data or {}).get("error", "no response"))
        try:
            return ToolResult.model_validate(data)
        except Exception as e:
            return ToolResult(
                envelope=invocation.envelope,
                invocation_id=invocation.invocation_id,
                status="failed",
                rejection_reason=f"sandbox transport: bad response ({e})")

    def call(self, request: dict, timeout: float = 75.0) -> dict | None:
        """One transport round-trip: b64-JSON request -> sandbox worker ->
        parsed JSON response. Returns {'error': ...} dict on transport
        failure (never raises), so callers degrade visibly."""
        import base64
        import json
        self.start()
        b64 = base64.b64encode(json.dumps(request).encode()).decode()
        cmd = f"{self.python} -m bionexus.sandboxd --request-b64 {b64}"
        try:
            out = self.sandbox.exec(cmd, timeout=timeout)
            return json.loads(out)
        except (TimeoutError, RuntimeError, json.JSONDecodeError) as e:
            return {"error": f"sandbox transport: {str(e)[:200]}"}

    # ----------------------------------------------------------- lifecycle

    def snapshot(self) -> str | None:
        return self.sandbox.snapshot() if self.sandbox else None

    def fork(self) -> "SandboxSession":
        """per_run mode (roadmap): child experiment runs from this state;
        writes never flow back."""
        self.start()
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


class SandboxedLab:
    """LabAdapter facade (S-T3 1c): every protocol op executes INSIDE the
    session's sandbox via the sandboxd worker. State (seed, queued runs,
    property gate) is carried by the caller between calls, so each op runs
    fresh in-sandbox; results come back as identical pydantic models.

    Supported inner labs: the simulator today. Anything else raises —
    a real robot behind a gateway is the gateway's (physical) trust
    boundary question, not this transport's."""

    def __init__(self, session: SandboxSession, seed: int = 7,
                 inner_kind: str = "simulator"):
        session.start()
        if session.sandbox is None:
            raise ValueError("SandboxedLab needs an active session "
                             "(mode=off has no sandbox)")
        if inner_kind != "simulator":
            raise NotImplementedError(
                f"sandboxed execution for lab '{inner_kind}' is not wired; "
                "supported: simulator (see ROADMAP S-T3)")
        self.session = session
        self.seed = seed
        self.name = f"sandboxed:{inner_kind}"
        self._state: dict | None = None

    def _op(self, op: str, payload: dict | None = None):
        req = {"kind": "lab", "seed": self.seed, "op": op,
               "payload": payload or {}, "lab_state": self._state}
        data = self.session.call(req)
        if data is None or "error" in data:
            raise RuntimeError(
                f"sandboxed lab op '{op}' failed: "
                f"{(data or {}).get('error', 'no response')}")
        self._state = data["lab_state"]
        return data["result"]

    # -- LabAdapter protocol ---------------------------------------------------

    def list_capabilities(self) -> dict:
        return self._op("caps")

    def submit_protocol(self, protocol) -> str:
        return self._op("submit",
                        {"protocol": protocol.model_dump(mode="json")})

    def get_status(self, run_id: str) -> str:
        return self._op("status", {"run_id": run_id})

    def fetch_results(self, run_id: str):
        from bionexus.core.contracts import AssayResult
        return AssayResult.model_validate(
            self._op("fetch", {"run_id": run_id}))

    def set_property_gate(self, metric: str, direction: str,
                          threshold: float) -> None:
        self._op("set_property_gate", {"metric": metric,
                                       "direction": direction,
                                       "threshold": float(threshold)})

    def cancel(self, run_id: str) -> None:
        self._op("cancel", {"run_id": run_id})

    # -- autoloop-visible lab traits (the campaign reads these; mirroring
    #    SimulatorLab's duck-typed surface keeps fidelity inside the box) --

    @property
    def _property_gate(self) -> dict | None:
        return (self._state or {}).get("property_gate")

    @property
    def replicates(self) -> int:
        return (self._state or {}).get("replicates", 3)

    def true_ic50_um(self, run_id: str, sample_id: str) -> float:
        return self._op("true_ic50",
                        {"run_id": run_id, "sample_id": sample_id})

    def _property_true_value(self, run_id: str, sample_id: str) -> float:
        return self._op("prop_true",
                        {"run_id": run_id, "sample_id": sample_id})

    def is_interferer(self, run_id: str, sample_id: str) -> bool:
        return self._op("interferer",
                        {"run_id": run_id, "sample_id": sample_id})
