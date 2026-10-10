"""bn sandboxd — the in-sandbox tool worker (S-T3).

Reads one ToolInvocation request, executes the resolved BioTool INSIDE
this process (and therefore inside the sandbox), and writes one ToolResult
JSON line to stdout. The transport (request b64, output stdout) is
shell-safe across LocalSandbox.exec and DockerSandbox.exec alike.

Request JSON: {"invocation": <ToolInvocation model_dump>}
Response JSON: <ToolResult model_dump>, or {"error": ...} on protocol
failure (never a partial success dressed up as a result).
"""
from __future__ import annotations

import base64
import json
import sys


def _build_registry():
    from bionexus.core.registry import Registry
    reg = Registry()
    reg.load_entry_points()
    from bionexus.adapters.bio.rdkit_ops import MoleculeDescriptors
    reg.register_tool(MoleculeDescriptors())
    return reg


def _lab(req: dict) -> str:
    """Kind 'lab': stateless-by-handoff execution of one simulator op.
    Caller carries lab_state between calls (SandboxedLab), so every op
    still runs FRESH inside the sandbox."""
    from bionexus.adapters.lab.simulator import SimulatorLab
    from bionexus.core.contracts import ProtocolSubmission
    try:
        st = req.get("lab_state")
        lab = (SimulatorLab.import_state(st) if st
               else SimulatorLab(seed=req.get("seed", 7)))
        op, pl = req["op"], req.get("payload", {})
        if op == "caps":
            result: object = lab.list_capabilities()
        elif op == "submit":
            result = lab.submit_protocol(
                ProtocolSubmission.model_validate(pl["protocol"]))
        elif op == "status":
            result = lab.get_status(pl["run_id"])
        elif op == "fetch":
            result = lab.fetch_results(pl["run_id"]).model_dump(mode="json")
        elif op == "cancel":
            result = lab.cancel(pl["run_id"])
        elif op == "true_ic50":
            result = lab.true_ic50_um(pl["run_id"], pl["sample_id"])
        elif op == "prop_true":
            result = lab._property_true_value(pl["run_id"], pl["sample_id"])
        elif op == "interferer":
            result = lab.is_interferer(pl["run_id"], pl["sample_id"])
        elif op == "set_property_gate":
            result = lab.set_property_gate(pl["metric"], pl["direction"],
                                           pl["threshold"])
        else:
            return json.dumps({"error": f"unknown lab op '{op}'"})
        return json.dumps({"result": result,
                           "lab_state": lab.export_state()})
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def run(request_json: str) -> str:
    try:
        req = json.loads(request_json)
        if req.get("kind") == "lab":
            return _lab(req)
        from bionexus.core.contracts import ToolInvocation, ToolResult
        inv = ToolInvocation.model_validate(req["invocation"])
        try:
            result = _build_registry().invoke(inv)
        except LookupError as e:
            result = ToolResult(envelope=inv.envelope,
                                invocation_id=inv.invocation_id,
                                status="rejected",
                                rejection_reason=str(e))
        return result.model_dump_json()
    except Exception as e:  # protocol-level failure stays loud
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) >= 2 and argv[0] == "--request-b64":
        request = base64.b64decode(argv[1]).decode()
    else:
        request = sys.stdin.read()
    sys.stdout.write(run(request))
    return 0


if __name__ == "__main__":
    sys.exit(main())
