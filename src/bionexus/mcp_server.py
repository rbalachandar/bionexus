"""BioNexus MCP server — expose the framework as tools for any MCP client
(Claude Desktop, Cursor, Claude Code...). Stdio transport, newline-delimited
JSON-RPC 2.0, implemented on the stdlib only (P1).

Run:  bn mcp
"""
from __future__ import annotations

import json
import sys
from typing import Any

PROTOCOL_VERSION = "2025-06-18"

TOOLS: list[dict[str, Any]] = [
    {
        "name": "generate_candidates",
        "description": "Generate candidate molecules for a target using the configured model (offline stub unless OPENAI_BASE_URL is set).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target": {"type": "string"},
                "n": {"type": "integer", "minimum": 1, "maximum": 12, "default": 6},
            },
            "required": ["target"],
        },
    },
    {
        "name": "run_assay",
        "description": "Run an assay on the virtual lab (dose-response series, replicates, controls). Returns per-compound responses and fitted IC50 (uM).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "compounds": {"type": "array", "items": {"type": "string"}},
                "assay": {"type": "string", "enum": ["binding", "enzymatic", "cytotoxicity", "counterscreen"]},
                "concentrations": {"type": "array", "items": {"type": "string"},
                                   "default": ["0.5uM", "2uM", "10uM", "40uM"]},
            },
            "required": ["compounds", "assay"],
        },
    },
    {
        "name": "propose_hypothesis",
        "description": "Record a falsifiable hypothesis (proposed state) into the provenance chain.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "statement": {"type": "string"},
                "candidate": {"type": "string"},
                "assay_type": {"type": "string"},
                "predicted": {"type": "string"},
            },
            "required": ["statement", "candidate", "assay_type", "predicted"],
        },
    },
    {
        "name": "list_lab_capabilities",
        "description": "List the virtual lab's instruments, assays, and constraints.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


class McpSession:
    """Request/response handler, separated from the stdio loop for testability."""

    def __init__(self) -> None:
        from bionexus.adapters.lab.simulator import SimulatorLab
        from bionexus.adapters.store.sqlite import SqliteProvenanceStore
        from bionexus.adapters.models.openai_compat import OpenAICompatProvider
        from bionexus.core.hypothesis import HypothesisTracker
        from bionexus.core.interfaces import system_actor
        from bionexus.core.registry import Registry
        from bionexus.core.safety import LabGateway, SafetyEngine

        self.branch = "mcp-session"
        self.store = SqliteProvenanceStore()
        self.actor = system_actor("mcp")
        self.registry = Registry()
        self.registry.register_model(OpenAICompatProvider(), default=True)
        self.gateway = LabGateway(SimulatorLab(seed=42), SafetyEngine(), self.store, self.actor)
        self.tracker = HypothesisTracker(self.store, self.actor)
        self._hypotheses = self.tracker

    # ------------------------------------------------------------ dispatch

    def handle(self, request: dict[str, Any]) -> dict[str, Any]:
        method = request.get("method", "")
        rid = request.get("id")
        try:
            if method == "initialize":
                result = {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "bionexus", "version": _version()},
                }
            elif method == "notifications/initialized":
                return {}  # notification: no response
            elif method == "tools/list":
                result = {"tools": TOOLS}
            elif method == "tools/call":
                result = self._call_tool(request["params"]["name"],
                                         request["params"].get("arguments") or {})
            elif method == "ping":
                result = {}
            else:
                return _error(rid, -32601, f"method not found: {method}")
            return {"jsonrpc": "2.0", "id": rid, "result": result}
        except Exception as exc:  # noqa: BLE001
            return _error(rid, -32000, str(exc))

    # ------------------------------------------------------------ tools

    def _call_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        text = {
            "generate_candidates": self._tool_generate,
            "run_assay": self._tool_assay,
            "propose_hypothesis": self._tool_hypothesis,
            "list_lab_capabilities": self._tool_capabilities,
        }[name](args)
        return {"content": [{"type": "text", "text": text}]}

    def _tool_generate(self, args: dict[str, Any]) -> str:
        from bionexus.core.contracts import Envelope, ToolInvocation

        n = int(args.get("n", 6))
        inv = ToolInvocation(envelope=Envelope(experiment_branch_id=self.branch),
                             tool="c.fm.generate_molecules", args=args)
        out = self.registry.model.generate(inv, f"generate {n} candidates for {args['target']}", n=n)
        return out.output["text"]

    def _tool_assay(self, args: dict[str, Any]) -> str:
        from examples.full_campaign import fit_ic50

        compounds = [str(c) for c in args["compounds"]]
        concs = args.get("concentrations") or ["0.5uM", "2uM", "10uM", "40uM"]
        from bionexus.adapters.lab.simulator import parse_concentration_um
        from bionexus.core.contracts import (
            Envelope, ProtocolOp, ProtocolStep, ProtocolSubmission,
            ReagentSpec, SampleKind, SampleSpec,
        )
        protocol = ProtocolSubmission(
            envelope=Envelope(experiment_branch_id=self.branch),
            title=f"mcp-{args['assay']}",
            assay_type=args["assay"],
            steps=[ProtocolStep(seq=1, op=ProtocolOp.dispense)],
            samples=[SampleSpec(sample_id=c, kind=SampleKind.compound, concentration=cc)
                     for c in compounds for cc in concs]
            + [SampleSpec(sample_id="ctrl-neg", kind=SampleKind.buffer, concentration="10uM")],
            reagents=[ReagentSpec(name="assay-buffer", amount="5 mL", bsl_level=1)],
        )
        run_id, rejection = self.gateway.submit(protocol)
        if rejection:
            return json.dumps({"status": "rejected", "reason": rejection})
        result = self.gateway.results(protocol.envelope, run_id)
        by: dict[str, list[tuple[float, float]]] = {}
        for m in result.measurements:
            if "control" in [f.value for f in m.flags]:
                continue
            by.setdefault(m.sample_id, []).append(
                (parse_concentration_um(m.well.split("-")[-1]), m.value))
        report = {c: {"ic50_um": (round(fit_ic50(pts), 2) if pts else None), "points": pts}
                  for c, pts in by.items()}
        return json.dumps({"run_id": run_id, "results": report}, indent=1)

    def _tool_hypothesis(self, args: dict[str, Any]) -> str:
        h = self.tracker.propose(
            statement=args["statement"], candidate=args["candidate"],
            assay_type=args["assay_type"], predicted=args["predicted"],
        )
        return json.dumps({"hypothesis_id": h.hypothesis_id, "status": h.status})

    def _tool_capabilities(self, args: dict[str, Any]) -> str:
        return json.dumps(self.gateway.capabilities(), indent=1)


def _error(rid: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


def _version() -> str:
    from bionexus import __version__

    return __version__


def serve(stdin: Any = None, stdout: Any = None) -> None:  # pragma: no cover
    """Newline-delimited JSON-RPC loop over stdio."""
    import os

    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    session = McpSession()
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            response = _error(None, -32700, "parse error")
        else:
            response = session.handle(request)
        if response:
            stdout.write(json.dumps(response) + "\n")
            stdout.flush()


if __name__ == "__main__":  # pragma: no cover
    serve()
