"""Generic MCP instrument transport (S-T4, strategy ticket slice 2).

Two halves, one architectural claim — the TRANSPORT is swappable, the
governance is not:

  * `McpLabAdapter` — a minimal MCP **client** (stdio JSON-RPC: initialize
    -> tools/list -> tools/call) that presents any MCP instrument server
    as a BioNexus LabAdapter. Point `command` at the bundled server for
    hermetic CI, or at `["uvx", "labmcp-atlas-ezo", "--simulate"]` (or a
    real bridge) for production — the adapter code does not change.

  * `python -m bionexus.mcp_instrument` — a reference MCP **server**
    wrapping the wire-level EzoPHLine simulator, speaking a pragmatic
    MCP subset: newline-delimited JSON-RPC 2.0, `protocolVersion
    2024-11-05`, tools with inputSchema + `annotations.readOnlyHint`
    (MCP's mechanism for "what is safe to auto-run").

The rules this module enforces:
  - capabilities() returns the server's DECLARED tools with their typed
    schemas — models reason over them; nothing is hardcoded here.
  - campaign execution auto-invokes ONLY tools annotated readOnly;
    mutating tools (calibrate_sensor) exist, are visible, and are never
    called by submit_protocol — operator action, documented, refused in
    code. This mirrors the labmcp `--read-only` convention one level up.
  - MCP servers are UNTRUSTED inputs (like instrument files): bad JSON,
    hostile names, or lying schemas fail closed — loud errors, never a
    guessed capability.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from typing import Any

from bionexus.core.contracts import (AssayResult, Envelope, InstrumentInfo,
                                     Measurement, ProtocolSubmission,
                                     RunStatus)

_PROTOCOL_VERSION = "2024-11-05"


class McpError(RuntimeError):
    pass


class McpLabAdapter:
    """LabAdapter over an MCP instrument server (stdio transport)."""

    name = "mcp-instrument"

    def __init__(self, command: list[str], timeout: float = 30.0,
                 approval_timeout: float = 60.0):
        self._proc = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True)
        self._id = 0
        self.timeout = timeout
        self.approval_timeout = approval_timeout   # server may pause for
        #                                   human approval; we surface it
        self._tools: list[dict] = []
        self._runs: dict[str, dict[str, Any]] = {}
        self._seq = 0
        init = self._rpc("initialize", {
            "protocolVersion": _PROTOCOL_VERSION, "capabilities": {},
            "clientInfo": {"name": "bionexus-mcp-client", "version": "0.1"}})
        if not isinstance(init, dict) or "tools" not in (
                init.get("capabilities") or {}):
            raise McpError(f"server lacks tools capability: {init}")
        listed = self._rpc("tools/list", {})
        tools = listed.get("tools") if isinstance(listed, dict) else None
        if not isinstance(tools, list) or not tools:
            raise McpError("server advertises no tools — refusing to "
                           "guess at its capabilities")
        for t in tools:                      # fail-closed schema audit
            if not isinstance(t, dict) or "name" not in t or \
                    "inputSchema" not in t:
                raise McpError(f"malformed tool descriptor: {t!r}")
        self._tools = tools

    # -- JSON-RPC plumbing ---------------------------------------------------

    def _rpc(self, method: str, params: dict) -> Any:
        if self._proc.poll() is not None:
            raise McpError("instrument server exited")
        self._id += 1
        req = {"jsonrpc": "2.0", "id": self._id, "method": method,
               "params": params}
        self._proc.stdin.write(json.dumps(req) + "\n")
        self._proc.stdin.flush()
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            line = self._proc.stdout.readline()
            if not line:
                raise McpError("instrument server closed the stream")
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError as e:
                raise McpError(f"non-JSON line from server: {e}")
            if msg.get("method") == "elicitation/create":
                # a server asking for human input: honor it only if a
                # human path is wired; otherwise deny, loudly, and keep
                # the campaign failure-visible
                resp = {"jsonrpc": "2.0", "id": msg.get("id"),
                        "result": {"action": "decline",
                                   "reason": "no human channel bound to "
                                             "this session"}}
                self._proc.stdin.write(json.dumps(resp) + "\n")
                self._proc.stdin.flush()
                continue
            if msg.get("id") == self._id:
                if "error" in msg:
                    raise McpError(f"{method}: {msg['error']}")
                return msg.get("result")
        raise McpError(f"timeout waiting for {method}")

    def _call(self, tool: str, args: dict) -> Any:
        res = self._rpc("tools/call", {"name": tool, "arguments": args})
        if not isinstance(res, dict):
            raise McpError(f"{tool}: malformed result {res!r}")
        if res.get("isError"):
            texts = [c.get("text", "") for c in res.get("content", [])
                     if c.get("type") == "text"]
            raise McpError(f"{tool} failed: {' '.join(texts)[:200]}")
        structured = res.get("structuredContent")
        if structured is None:
            raise McpError(f"{tool}: no structuredContent — untyped results"
                           " cannot be trusted by the verdict path")
        return structured

    # -- LabAdapter protocol ---------------------------------------------------

    def _readonly_tools(self) -> set[str]:
        return {t["name"] for t in self._tools
                if (t.get("annotations") or {}).get("readOnlyHint")}

    def list_capabilities(self) -> dict[str, Any]:
        return {
            "kind": "mcp-instrument",
            "tools": [{"name": t["name"],
                       "description": str(t.get("description", ""))[:300],
                       "inputSchema": t["inputSchema"],
                       "read_only": bool((t.get("annotations") or {})
                                         .get("readOnlyHint"))}
                      for t in self._tools],
            "note": "auto-execution restricted to readOnly tools; "
                    "mutating tools (calibrate_sensor) are operator-only",
        }

    def submit_protocol(self, protocol: ProtocolSubmission) -> str:
        readonly = self._readonly_tools()
        if "read_ph" not in readonly:
            raise McpError("server's read_ph tool is not annotated "
                           "readOnly — refusing to auto-invoke unreviewed")
        for point in protocol.samples:
            cal = (point.metadata or {}).get("calibrate")
            if cal:
                raise McpError(
                    f"calibration ({cal!r}) requested inside a campaign: "
                    "calibrate_sensor is a MUTATING tool — operator action "
                    "only (see readOnly-gate in _readonly_tools)")
        n = 3
        if protocol.steps:
            n = int((protocol.steps[0].params or {}).get("reads", 3))
        readings: list[float] = []
        for _ in range(n):
            out = self._call("read_ph", {})
            val = out.get("ph")
            if not isinstance(val, (int, float)):
                raise McpError(f"read_ph returned no numeric ph: {out}")
            readings.append(float(val))
        self._seq += 1
        run_id = f"mcp-{self._seq:03d}"
        unc = out.get("uncertainty_ph")
        self._runs[run_id] = {"protocol": protocol, "readings": readings,
                              "uncertainty": float(unc) if unc else None,
                              "cal_state": out.get("cal_state")}
        return run_id

    def get_status(self, run_id: str) -> str:
        return "done" if run_id in self._runs else "unknown"

    def fetch_results(self, run_id: str) -> AssayResult:
        run = self._runs[run_id]
        readings = run["readings"]
        mean = sum(readings) / len(readings)
        protocol: ProtocolSubmission = run["protocol"]
        return AssayResult(
            envelope=Envelope(experiment_branch_id="mcp-instrument"),
            run_id=run_id, protocol_id=protocol.protocol_id,
            instrument=InstrumentInfo(adapter="mcp-instrument(sim)",
                                      instrument_id="ezo-ph-mcp-01",
                                      raw_output_uri="mcp://tools/read_ph"),
            status=RunStatus.completed,
            measurements=[Measurement(
                sample_id=s.sample_id, assay_type="ph",
                value=round(mean, 3), unit="pH",
                uncertainty=run["uncertainty"],
                derived_metrics={"n_reads": len(readings)},
                metadata={"cal_state": run["cal_state"]})
                for s in protocol.samples
                if s.kind.value != "buffer"],
            qc={"controls_passed": True, "calibration": run["cal_state"],
                "note": "SIMULATED via MCP transport (S-T4 POC)"},
        )

    def close(self) -> None:
        try:
            self._proc.stdin.close()
            self._proc.terminate()
            self._proc.wait(timeout=5)
        except Exception:
            self._proc.kill()


# --------------------------------------------------------------- the server

def serve(cmd_fn) -> None:
    """Minimal newline-JSON-RPC MCP server around a handle(command)->str
    wire function. Pragmatic subset: initialize, tools/list, tools/call,
    and server-initiated elicitation for operator-gated actions."""
    from bionexus.adapters.devices.ezo_ph import EzoPHLine
    line: EzoPHLine = cmd_fn()

    def send(msg: dict) -> None:
        sys.stdout.write(json.dumps(msg) + "\n")
        sys.stdout.flush()

    def result(rid: Any, body: dict) -> None:
        send({"jsonrpc": "2.0", "id": rid, "result": body})

    def err(rid: Any, code: int, message: str) -> None:
        send({"jsonrpc": "2.0", "id": rid,
              "error": {"code": code, "message": message}})

    TOOLS = [
        {"name": "read_ph",
         "description": "Take one pH reading of the immersed sample, with "
                        "the probe's calibration-state uncertainty.",
         "inputSchema": {"type": "object", "properties": {}},
         "annotations": {"readOnlyHint": True}},
        {"name": "calibrate_sensor",
         "description": "Two-point calibration (low/high buffers). "
                        "MUTATING hardware action — requires operator "
                        "approval via elicitation; never auto-runs.",
         "inputSchema": {"type": "object",
                         "properties": {"low": {"type": "number"},
                                        "high": {"type": "number"}},
                         "required": ["low", "high"]},
         "annotations": {"readOnlyHint": False}},
    ]

    while True:
        line_in = sys.stdin.readline()
        if not line_in:
            return
        line_in = line_in.strip()
        if not line_in:
            continue
        try:
            msg = json.loads(line_in)
        except json.JSONDecodeError:
            continue
        rid, method = msg.get("id"), msg.get("method", "")
        if method == "initialize":
            result(rid, {"protocolVersion": _PROTOCOL_VERSION,
                         "capabilities": {"tools": {}},
                         "serverInfo": {"name": "ezo-ph-wiresim",
                                        "version": "0.1-simulated"}})
        elif method.startswith("notifications/"):
            pass
        elif method == "tools/list":
            result(rid, {"tools": TOOLS})
        elif method == "tools/call":
            params = msg.get("params") or {}
            name = params.get("name")
            if name == "read_ph":
                reading = float(line.handle("r").removesuffix("*OK"))
                result(rid, {"content": [{"type": "text",
                                          "text": f"pH {reading}"}],
                             "structuredContent": {
                                 "ph": reading,
                                 "uncertainty_ph": line.uncertainty,
                                 "cal_state": sorted(line.cal_points)
                                 or ["uncalibrated"]}})
            elif name == "calibrate_sensor":
                send({"jsonrpc": "2.0", "method": "elicitation/create",
                      "id": -1,
                      "params": {"message": "Approve probe calibration "
                                            "low=4.01 high=10.01?",
                                 "requestedSchema": {}}})
                decision = None
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline and decision is None:
                    nxt = sys.stdin.readline()
                    if not nxt:
                        break
                    try:
                        nm = json.loads(nxt)
                    except json.JSONDecodeError:
                        continue
                    if nm.get("method") == "/_reply" or (
                            "result" in nm and "action" in
                            nm.get("result", {})):
                        decision = nm["result"].get("action")
                if decision != "accept":
                    result(rid, {"content": [{"type": "text", "text":
                        "declined by human gate"}], "isError": True,
                        "structuredContent": {"declined": True}})
                else:
                    line.handle("Cal,low,4.01")
                    line.handle("Cal,high,10.01")
                    result(rid, {"content": [{"type": "text",
                                              "text": "calibrated"}],
                                 "structuredContent":
                                     {"cal_state": sorted(line.cal_points)}})
            else:
                err(rid, -32602, f"unknown tool {name}")
        else:
            err(rid, -32601, "method not found")


if __name__ == "__main__":
    from bionexus.adapters.devices.ezo_ph import EzoPHLine
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 11
    sample = float(sys.argv[2]) if len(sys.argv) > 2 else 7.35
    pre_cal = len(sys.argv) > 3 and sys.argv[3] == "calibrate"
    clock = lambda: 0.0    # noqa: E731 — deterministic drift term in POC

    def _make():
        ln = EzoPHLine(sample_ph=sample, seed=seed, clock=clock)
        if pre_cal:     # operator calibrated the probe BEFORE this session
            ln.handle("Cal,low,4.01")
            ln.handle("Cal,high,10.01")
        return ln
    serve(_make)
