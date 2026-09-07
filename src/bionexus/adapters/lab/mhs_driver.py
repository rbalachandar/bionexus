"""MHS (machine/hardware standard) driver adapter — experimental.

Wraps an MHS-compliant driver endpoint as a BioNexus LabAdapter. MHS
translates devices into read/write primitives plus a standard discovery
format; this adapter maps those onto our protocol/result lifecycle so any
MHS-compatible instrument becomes usable without bespoke code.

    config (YAML/JSON passed to bn auto, or constructor kwargs):
      mhs_url: http://bench-host:8900     # driver endpoint (required)
      device_id: incubator-01
      name: Bench incubator

Status: skeleton. The MHS driver SDK is not public yet; endpoints follow
the published shape (discovery reference file, read/write commands) and
will be firmed up against the real spec.
"""
from __future__ import annotations

import json
import os
import urllib.request
from typing import Any

from bionexus.core.device_card import DeviceCard, builtin_card, load_card, to_agent_text


class MhsDriverLab:
    """LabAdapter over an MHS driver. Follows the SimulatorLab surface:
    submit_protocol / get_status / fetch_results / list_capabilities."""

    name = "mhs-driver"

    def __init__(self, mhs_url: str | None = None, device_id: str = "mhs-device",
                 name: str = "MHS device", timeout_s: int = 30, **_: Any) -> None:
        self.mhs_url = (mhs_url or os.environ.get("MHS_URL", "")).rstrip("/")
        if not self.mhs_url:
            raise ValueError(
                "MHS adapter needs `mhs_url` (or MHS_URL env) pointing at the "
                "driver endpoint — e.g. http://bench-host:8900")
        self.device_id = device_id
        self.device_name = name
        self.timeout_s = timeout_s

    # -- driver communication -------------------------------------------------

    def _call(self, path: str, payload: dict | None = None) -> dict:
        url = f"{self.mhs_url}/{path.lstrip('/')}"
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(
            url, data=data, method="POST" if data else "GET",
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout_s) as r:  # noqa: S310
            return json.loads(r.read())

    # -- discovery: the reference file is the agent's manual -------------------

    def reference_file(self) -> dict:
        return self._call("reference")

    def list_capabilities(self) -> dict[str, Any]:
        try:
            ref = self.reference_file()
        except Exception as exc:
            return {"assays": [], "error": f"driver unreachable: {exc}"}
        return {
            "assays": ref.get("protocols", []),
            "measures": ref.get("measures", []),
            "adjusts": ref.get("adjusts", []),
            "safety_limits": ref.get("safety_limits", []),
            "notes": ref.get("notes", []),
        }

    def agent_reference_text(self) -> str:
        """MHS-style reference file as agent-readable text, with operator
        tags layered in from any local device card."""
        try:
            ref = self.reference_file()
            card = DeviceCard(
                device_id=self.device_id, name=self.device_name,
                protocols=ref.get("protocols", []),
                measures=[m for m in ref.get("measures", [])],
                adjusts=[a for a in ref.get("adjusts", [])],
                safety_limits=[s for s in ref.get("safety_limits", [])],
                notes=ref.get("notes", []),
                source="builtin")
        except Exception:
            card = builtin_card(self.device_id, self.device_name, {})
        card = load_card(self.device_id, base=card) or card
        return to_agent_text(card)

    # -- control: write to operate, read to observe ----------------------------

    def submit_protocol(self, protocol: Any) -> str:
        out = self._call("write", {
            "device": self.device_id,
            "command": "run_protocol",
            "params": {"protocol": protocol.model_dump(mode="json")},
        })
        return str(out.get("run_id", out.get("handle", "")))

    def get_status(self, run_id: str) -> str:
        out = self._call("read", {"device": self.device_id,
                                  "command": "status", "params": {"run_id": run_id}})
        return str(out.get("status", "unknown"))

    def fetch_results(self, run_id: str) -> Any:
        from bionexus.core.contracts import AssayResult, Envelope
        out = self._call("read", {"device": self.device_id,
                                  "command": "results", "params": {"run_id": run_id}})
        # driver returns measurements in our contract shape; wrap if bare
        if isinstance(out, dict) and "measurements" in out:
            out.setdefault("envelope", {})
            out.setdefault("status", "completed")
            return AssayResult.model_validate(out)
        return AssayResult(
            envelope=Envelope(experiment_branch_id=f"mhs/{run_id}"),
            protocol_id=run_id,
            status="completed",
            measurements=[],
            raw=out)

    def cancel(self, run_id: str) -> None:
        self._call("write", {"device": self.device_id,
                             "command": "cancel", "params": {"run_id": run_id}})
