"""Robotic arm / plate scheduling adapter — Automata LINQ, HighRes Cellario.

In a multi-device lab, plates must be transported between instruments
(incubator → dispenser → reader → LC-MS). This adapter handles plate
scheduling: it queries device availability, plans the transport route,
and issues REST API commands to robotic arms or track systems.

BioNexus does not replace the lab's scheduling software (Cellario,
Overlord, Velum) — it interfaces with it via REST APIs, sending
`move_plate` commands and monitoring completion.
"""
from __future__ import annotations

import json
import urllib.request
from typing import Any, Protocol


class SchedulerTransport(Protocol):
    def post(self, path: str, body: dict) -> dict: ...
    def get(self, path: str) -> dict: ...


class HTTPScheduler:
    def __init__(self, base_url: str, api_key: str = ""):
        self.base_url = base_url.rstrip("/")
        self.headers = {"Content-Type": "application/json"}
        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"

    def post(self, path: str, body: dict) -> dict:
        req = urllib.request.Request(
            f"{self.base_url}{path}", data=json.dumps(body).encode(),
            headers=self.headers, method="POST")
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())

    def get(self, path: str) -> dict:
        req = urllib.request.Request(
            f"{self.base_url}{path}", headers=self.headers, method="GET")
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())


class RoboticArmScheduler:
    """Schedules plate transport between devices via REST API.

    Connects to centralized scheduling software (Cellario, Overlord,
    Automata LINQ). The agent sends a high-level `transport_plate` command;
    the scheduling software handles robot selection, path planning, and
    collision avoidance.
    """

    name = "robotic-arm-scheduler"

    def __init__(self, transport: SchedulerTransport):
        self.transport = transport

    def move_plate(self, from_device: str, to_device: str,
                   plate_id: str, plate_type: str = "96-well") -> dict:
        """Request a plate transport between two devices."""
        return self.transport.post("/move_plate", {
            "from": from_device, "to": to_device,
            "plate_id": plate_id, "plate_type": plate_type,
        })

    def device_status(self, device_id: str) -> dict:
        return self.transport.get(f"/devices/{device_id}/status")

    def queue_depth(self) -> int:
        """Number of pending transport requests."""
        q = self.transport.get("/queue")
        return len(q.get("queue", []))

    def wait_for_transport(self, move_id: str, timeout: int = 120) -> bool:
        """Block until a transport completes (or timeout)."""
        import time
        deadline = time.time() + timeout
        while time.time() < deadline:
            status = self.transport.get(f"/moves/{move_id}").get("status", "")
            if status in ("completed", "failed"):
                return status == "completed"
            time.sleep(2)
        return False
