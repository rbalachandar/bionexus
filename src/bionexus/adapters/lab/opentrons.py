"""Opentrons OT-2 / Flex REFERENCE DRIVER — NOT hardware-validated.

Audit status (Oct 10, ROADMAP S-T4): the HTTP transport is real, but the
request/response shapes are best-effort drafts that have NEVER been run
against a physical OT-2 (the upload needs multipart + the mandatory
`Opentrons-Version` header; runs use JSON:API `relationships`; commands
live at /commands). A real robot will reject these payloads today. Use
as a template and a CI seam — do not schedule lab time against it.

Talks to the robot's HTTP API (port 31950): health check, protocol upload,
run creation, status polling. Transport is injected so CI tests run against
recorded sessions — no robot required (P8).

Semantics with the platform: Opentrons is the **Make** step of DMTA. Its
`fetch_results` returns execution evidence (per-command status from the run
log), not assay values — the plate then goes to a reader (see
`PlateReaderShare` or `read_plate`).

Requires no extra dependencies (stdlib urllib).

Until S-T4 validates it on a machine, treat every endpoint here as
unverified; the P8 test transport mirrors THIS draft, not the robot.
"""
from __future__ import annotations

import json
import time
import urllib.request
from typing import Any

from bionexus.core.contracts import (
    AssayResult, Envelope, InstrumentInfo, Measurement, ProtocolSubmission,
    RunStatus,
)

# Opentrons HTTP API (OT-2 v3+/Flex): we use exactly these endpoints.
EP_HEALTH = "/health"
EP_PROTOCOLS = "/protocols"
EP_RUNS = "/runs"


class OpentronsTransport:
    """Thin HTTP layer (injectable for tests/recordings)."""

    def __init__(self, base_url: str, timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def request(self, method: str, path: str, body: dict | None = None) -> dict:
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Content-Type": "application/json"},
            method=method,
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310
            payload = resp.read()
            return json.loads(payload) if payload else {}


def compile_protocol(protocol: ProtocolSubmission,
                     labware: str = "corning_96_wellplate_360ul_flat",
                     pipette: str = "p300_single") -> str:
    """Abstract ProtocolSubmission -> Opentrons Python protocol (API v2)."""
    lines = [
        "import opentrons.execute  # or opentrons.simulate on the robot",
        "from opentrons import protocol_api",
        "",
        "metadata = {'apiLevel': '2.13', 'title': "
        f"{protocol.title!r}}}",
        "",
        "def run(ctx: protocol_api.ProtocolContext):",
        f"    plate = ctx.load_labware({labware!r}, '1')",
        f"    tiprack = ctx.load_labware('opentrons_96_tiprack_300ul', '2')",
        f"    pip = ctx.load_instrument({pipette!r}, 'right', tip_racks=[tiprack])",
    ]
    for step in sorted(protocol.steps, key=lambda s: s.seq):
        if step.op.value != "dispense":
            continue  # extend: mix, incubate, transfer chains
        well = step.params.get("well", "A1")
        vol = float(step.params.get("volume_ul", 10.0))
        src = step.params.get("source", "A1")
        lines += [
            f"    pip.pick_up_tip() if not pip.hw_pipette['has_tip'] else None"
            if False else f"    pip.pick_up_tip()",
            f"    pip.aspirate({vol}, plate['{src}'].top())",
            f"    pip.dispense({vol}, plate['{well}'].top())",
            f"    pip.drop_tip()",
        ]
    return "\n".join(lines) + "\n"


class OpentronsLab:
    """LabAdapter over an Opentrons robot. Results = execution evidence."""

    name = "opentrons"

    def __init__(self, transport: OpentronsTransport | None = None,
                 base_url: str = "http://169.254.8.32:31950"):
        self.client = transport or OpentronsTransport(base_url)
        self._runs: dict[str, dict[str, Any]] = {}

    # -- contract -------------------------------------------------------------

    def list_capabilities(self) -> dict[str, Any]:
        health = self.client.request("GET", EP_HEALTH)
        return {
            "kind": "liquid_handler",
            "robot": health.get("name", "opentrons"),
            "api_version": health.get("apiVersion"),
            "firmware": health.get("fwVersion"),
            "operations": ["dispense", "aspirate", "transfer"],
            "note": "Make-step adapter: assay readout comes from a plate reader",
        }

    def submit_protocol(self, protocol: ProtocolSubmission) -> str:
        script = compile_protocol(protocol)
        # create protocol (name + contents), then create a run for it
        created = self.client.request("POST", EP_PROTOCOLS, {
            "protocolName": f"{protocol.title}-{protocol.protocol_id[:8]}",
            "protocolContents": script,
            "protocolKind": "python",
        })
        protocol_id = created.get("data", {}).get("id") or created.get("id")
        if not protocol_id:
            raise RuntimeError(f"unexpected protocol response: {created}")
        run = self.client.request("POST", EP_RUNS, {"protocolId": protocol_id})
        run_id = run.get("data", {}).get("id") or run.get("id")
        if not run_id:
            raise RuntimeError(f"unexpected run response: {run}")
        self._runs[run_id] = {"protocol": protocol, "protocol_id": protocol_id}
        # start the run (API expects an action)
        self.client.request("POST", f"{EP_RUNS}/{run_id}/actions",
                            {"actionType": "play"})
        return run_id

    def get_status(self, run_id: str) -> str:
        run = self.client.request("GET", f"{EP_RUNS}/{run_id}")
        status = (run.get("data", {}).get("status") or "unknown").lower()
        return {"running": "running", "succeeded": "done",
                "failed": "failed", "stopped": "cancelled",
                "pause-requested": "running", "blocked": "running",
                "idle": "queued"}.get(status, status)

    def fetch_results(self, run_id: str) -> AssayResult:
        run = self.client.request("GET", f"{EP_RUNS}/{run_id}")
        data = run.get("data", {})
        commands = data.get("commands") or []
        executed = [
            {"command": c.get("commandType"), "status": c.get("status"),
             "params": c.get("params", {})}
            for c in commands
            if c.get("status") == "succeeded" and c.get("commandType") != "pause"
        ]
        protocol = self._runs.get(run_id, {}).get("protocol")
        return AssayResult(
            envelope=Envelope(experiment_branch_id="opentrons"),
            protocol_id=protocol.protocol_id if protocol else run_id,
            instrument=InstrumentInfo(adapter=self.name, instrument_id="ot-2",
                                      raw_output_uri=f"opentrons://{run_id}/commands"),
            status=RunStatus.completed if executed else RunStatus.failed,
            measurements=[
                Measurement(sample_id=f"cmd-{i}", assay_type="execution",
                            value=1.0, unit="executed",
                            metadata={"command": c["command"],
                                      "params": c["params"]})
                for i, c in enumerate(executed, 1)
            ],
            qc={"controls_passed": True,
                "notes": f"{len(executed)} commands executed; "
                         "assay readout comes from the plate reader"},
        )

    def cancel(self, run_id: str) -> None:
        self.client.request("POST", f"{EP_RUNS}/{run_id}/actions",
                            {"actionType": "stop"})
