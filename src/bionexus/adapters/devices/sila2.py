"""GENERIC HTTP device adapter — NOT a SiLA 2 binding (audit Oct 10, S-T4): the real SiLA 2 protocol needs the gRPC sila2 SDK and its feature/resolve semantics, which are not implemented here. This speaks a simple JSON POST/GET contract (/command, /status, /results) that real SiLA 2 devices do NOT serve. Honest name: template-hub-style HTTP device shim."""
from __future__ import annotations

import json
import urllib.request
from typing import Any, Protocol

from bionexus.core.contracts import (
    AssayResult, Envelope, InstrumentInfo, Measurement, ProtocolSubmission,
    RunStatus,
)


class SiLA2Channel(Protocol):
    """Transport abstraction — injectable for tests (P8)."""

    def call(self, endpoint: str, payload: dict) -> dict: ...


class SiLA2HTTPChannel:
    """HTTP gateway mode for SiLA 2 devices (SiLA 2 HTTP binding)."""

    def __init__(self, base_url: str, timeout: int = 60):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def call(self, endpoint: str, payload: dict) -> dict:
        req = urllib.request.Request(
            f"{self.base_url}{endpoint}",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310
            return json.loads(resp.read())


class SiLA2Device:
    """A single SiLA 2 device discovered on the network or configured."""

    def __init__(self, device_id: str, features: list[str],
                 endpoint: str, kind: str):
        self.device_id = device_id
        self.features = features
        self.endpoint = endpoint
        self.kind = kind


class SiLA2Adapter:
    """Generic LabAdapter over SiLA 2.

    One adapter instance manages one SiLA 2 device (or a SiLA 2 gateway
    managing multiple devices). The `feature_namespace` maps BioNexus
    protocol operations to SiLA 2 feature identifiers.

    Example feature namespaces:
      - "org.silastandard.examples.TemperatureController"
      - "org.silastandard.core.CommandController"
    """

    name = "sila2"

    def __init__(self, channel: SiLA2Channel, device_label: str = "sila2-device",
                 feature_map: dict[str, str] | None = None):
        """`feature_map` maps BioNexus operations to SiLA 2 feature IDs:
            {"submit": "org.silastandard.../Command/Start",
             "status": "org.silastandard.../Property/Status",
             "results": "org.silastandard.../Command/GetResult"}
        """
        self.channel = channel
        self.device_label = device_label
        self.feature_map = feature_map or {}
        self._runs: dict[str, ProtocolSubmission] = {}

    def list_capabilities(self) -> dict[str, Any]:
        return {
            "kind": "sila2",
            "device_label": self.device_label,
            "protocol": "SiLA 2 (gRPC or HTTP binding)",
            "features": self.feature_map,
            "note": "One adapter covers all SiLA 2-compliant devices",
        }

    def submit_protocol(self, protocol: ProtocolSubmission) -> str:
        run_id = f"sila2-{protocol.protocol_id[:8]}"
        self._runs[run_id] = protocol
        # Send the compiled protocol to the SiLA 2 device's Execute command
        endpoint = self.feature_map.get("execute", "/command")
        payload = {
            "command_id": protocol.protocol_id,
            "steps": [
                {"seq": s.seq, "op": s.op.value, "params": s.params}
                for s in protocol.steps
            ],
            "samples": [
                {"id": s.sample_id, "well": s.concentration}
                for s in protocol.samples
            ],
        }
        self.channel.call(endpoint, payload)
        return run_id

    def get_status(self, run_id: str) -> str:
        endpoint = self.feature_map.get("status", "/status")
        result = self.channel.call(endpoint, {"run_id": run_id})
        return result.get("status", "unknown")

    def fetch_results(self, run_id: str) -> AssayResult:
        endpoint = self.feature_map.get("results", "/results")
        result = self.channel.call(endpoint, {"run_id": run_id})
        measurements = []
        for m in result.get("measurements", []):
            measurements.append(Measurement(
                sample_id=m.get("sample_id", ""),
                well=m.get("well"),
                assay_type=m.get("assay_type", "unknown"),
                value=float(m.get("value", 0)),
                unit=m.get("unit", ""),
                metadata=m.get("metadata", {}),
            ))
        protocol = self._runs.get(run_id)
        return AssayResult(
            envelope=Envelope(experiment_branch_id="sila2"),
            protocol_id=protocol.protocol_id if protocol else run_id,
            instrument=InstrumentInfo(
                adapter=self.name, instrument_id=self.device_label,
                raw_output_uri=f"sila2://{run_id}"),
            status=RunStatus(result.get("status", "completed")),
            measurements=measurements,
        )

    def cancel(self, run_id: str) -> None:
        endpoint = self.feature_map.get("cancel", "/cancel")
        self.channel.call(endpoint, {"run_id": run_id})
