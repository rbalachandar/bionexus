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


def run(request_json: str) -> str:
    try:
        from bionexus.core.contracts import ToolInvocation, ToolResult
        req = json.loads(request_json)
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
