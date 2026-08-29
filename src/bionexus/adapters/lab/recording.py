"""Recording / playback harness for hardware adapters (T3.3, P8).

Record real lab interactions once, replay them forever in CI:

    real = MyRobotLab(api_key=...)
    rec  = RecordingLab(real, "robot-session.json")   # wrap & record
    # ... run workflows through the LabGateway with `rec` ...

    ci_lab = PlaybackLab("robot-session.json")        # replays identically, offline

Playback determinism is the point: a hardware bug captured in the field is a
regression test forever.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from bionexus.core.contracts import (
    AssayResult,
    Envelope,
    InstrumentInfo,
    ProtocolSubmission,
    RunStatus,
)


class RecordingLab:
    """Wraps a LabAdapter; records every call + return value to JSON."""

    name = "recording"

    def __init__(self, inner: Any, path: str | Path):
        self.inner = inner
        self.path = Path(path)
        self._log: list[dict[str, Any]] = []

    def list_capabilities(self) -> dict[str, Any]:
        caps = self.inner.list_capabilities()
        self._log.append({"op": "list_capabilities", "result": caps})
        return caps

    def submit_protocol(self, protocol: ProtocolSubmission) -> str:
        run_id = self.inner.submit_protocol(protocol)
        self._log.append({
            "op": "submit_protocol",
            "protocol": protocol.model_dump(mode="json"),
            "result": run_id,
        })
        return run_id

    def get_status(self, run_id: str) -> str:
        status = self.inner.get_status(run_id)
        self._log.append({"op": "get_status", "run_id": run_id, "result": status})
        return status

    def fetch_results(self, run_id: str) -> AssayResult:
        result = self.inner.fetch_results(run_id)
        self._log.append({
            "op": "fetch_results",
            "run_id": run_id,
            "result": result.model_dump(mode="json"),
        })
        return result

    def cancel(self, run_id: str) -> None:
        self._log.append({"op": "cancel", "run_id": run_id})
        self.inner.cancel(run_id)

    def save(self) -> Path:
        self.path.write_text(json.dumps(self._log, indent=1))
        return self.path


class PlaybackLab:
    """Replays a recording. Offline, deterministic, identical results."""

    name = "playback"

    def __init__(self, path: str | Path, seed_branch: str = "playback"):
        entries = json.loads(Path(path).read_text())
        self._capabilities: dict[str, Any] = {}
        self._submit_by_protocol: dict[str, str] = {}  # protocol_id -> run_id
        self._status: dict[str, str] = {}
        self._results: dict[str, dict] = {}
        for e in entries:
            if e["op"] == "list_capabilities":
                self._capabilities = e["result"]
            elif e["op"] == "submit_protocol":
                self._submit_by_protocol[e["protocol"]["protocol_id"]] = e["result"]
            elif e["op"] == "get_status":
                self._status[e["run_id"]] = e["result"]
            elif e["op"] == "fetch_results":
                self._results[e["run_id"]] = e["result"]

    def list_capabilities(self) -> dict[str, Any]:
        return dict(self._capabilities)

    def submit_protocol(self, protocol: ProtocolSubmission) -> str:
        run_id = self._submit_by_protocol.get(protocol.protocol_id)
        if run_id is None:
            raise LookupError(
                f"protocol {protocol.protocol_id} not in recording — "
                "recorded sessions are replay-only, not simulated"
            )
        return run_id

    def get_status(self, run_id: str) -> str:
        return self._status.get(run_id, "failed")

    def fetch_results(self, run_id: str) -> AssayResult:
        data = self._results.get(run_id)
        if data is None:
            raise LookupError(f"run {run_id} not in recording")
        return AssayResult.model_validate(data)

    def cancel(self, run_id: str) -> None:
        pass  # nothing to cancel in playback
