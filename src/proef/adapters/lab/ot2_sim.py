"""ot2_sim — a spec-conformant SIMULATED Opentrons robot (S-T4 CI seam).

Implements the documented v3 surface (see opentrons.py docstring for
sources) well enough to REJECT the mistakes a real robot rejects:
missing `Opentrons-Version` -> 400, wrong multipart field -> 422,
runs without a protocolId -> 400, unknown ids -> 404. It also plays
along like a robot: the uploaded Python protocol source is parsed for
pipette calls, and GET /runs/{id}/commands reports exactly those as
succeeded after play + a couple of polls.

This is a test double with teeth, not hardware: it pins the CONTRACT,
the physical robot remains S-T4's confirmation step.
"""
from __future__ import annotations

import json
import re
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class _State:
    def __init__(self):
        self.protocols: dict[str, dict] = {}
        self.runs: dict[str, dict] = {}
        self.requests: list[tuple[str, str]] = []


def make_server() -> tuple[ThreadingHTTPServer, _State]:
    state = _State()

    class Handler(BaseHTTPRequestHandler):
        # -- plumbing -----------------------------------------------------
        def log_message(self, *a):
            pass

        def _send(self, code: int, body: dict):
            raw = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _version_ok(self) -> bool:
            v = self.headers.get("Opentrons-Version")
            return v in ("2", "3", "*")

        def _plan(self, src: str) -> list[dict]:
            """Extract pipette command plan from the uploaded protocol."""
            plan = []
            for m in re.finditer(
                    r"pip\.(pick_up_tip|aspirate|dispense|drop_tip)"
                    r"\(([^)]*)\)?", src):
                plan.append({"id": uuid.uuid4().hex,
                             "commandType": {"pick_up_tip": "pickUpTip",
                                             "aspirate": "aspirate",
                                             "dispense": "dispense",
                                             "drop_tip": "dropTip"}[m.group(1)],
                             "status": "succeeded",
                             "params": {"raw": m.group(2)[:80]}})
            return plan

        # -- routes ---------------------------------------------------------
        def do_GET(self):
            state.requests.append(("GET", self.path))
            if self.path == "/":
                return self._send(200, {
                    "api_version": "v3back", "system_version": "sim-0.1",
                    "firmware_version": "sim-smoothie"})
            m = re.fullmatch(r"/runs/([\w-]+)", self.path)
            if m:
                if not self._version_ok():
                    return self._send(400, {"errors": [{"detail":
                        "Opentrons-Version header required"}]})
                run = state.runs.get(m.group(1))
                if not run:
                    return self._send(404, {"errors": [{"detail": "no run"}]})
                if run["status"] == "running":
                    run["polls"] += 1
                    if run["polls"] >= 2:
                        run["status"] = "finished"
                return self._send(200, {"data": {
                    "id": run["id"], "status": run["status"],
                    "protocolId": run["protocol_id"], "current": True}})
            m = re.fullmatch(r"/runs/([\w-]+)/commands", self.path)
            if m:
                if not self._version_ok():
                    return self._send(400, {"errors": [{"detail": "version"}]})
                run = state.runs.get(m.group(1))
                if not run:
                    return self._send(404, {"errors": [{"detail": "no run"}]})
                return self._send(200, {"data": run["commands"]})
            return self._send(404, {"errors": [{"detail": "no route"}]})

        def do_POST(self):
            state.requests.append(("POST", self.path))
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b""
            if not self._version_ok():
                return self._send(400, {"errors": [{"detail":
                    "Opentrons-Version header is required on "
                    "protocol/run endpoints"}]})
            if self.path == "/protocols":
                ctype = self.headers.get("Content-Type", "")
                if "multipart/form-data" not in ctype:
                    return self._send(422, {"errors": [{"detail":
                        "expected multipart/form-data"}]})
                if b'name="files"' not in raw:      # v3 field name
                    return self._send(422, {"errors": [{"detail":
                        "multipart field must be 'files' (v3)"}]})
                pid = uuid.uuid4().hex
                src = raw.decode("latin-1")
                state.protocols[pid] = {"id": pid, "plan": self._plan(src)}
                return self._send(201, {"data": {
                    "id": pid, "analysisSummaries": [{"id": "a-1"}]}})
            if self.path == "/runs":
                try:
                    body = json.loads(raw or b"{}")
                except json.JSONDecodeError:
                    return self._send(400, {"errors": [{"detail": "json"}]})
                pid = (body.get("data") or {}).get("protocolId")
                if not pid:
                    return self._send(400, {"errors": [{"detail":
                        "data.protocolId required (integration-tools docs)"}]})
                if pid not in state.protocols:
                    return self._send(404, {"errors": [{"detail":
                        "unknown protocolId"}]})
                rid = uuid.uuid4().hex
                state.runs[rid] = {"id": rid, "protocol_id": pid,
                                   "status": "idle", "polls": 0,
                                   "commands": state.protocols[pid]["plan"]}
                return self._send(201, {"data": {"id": rid,
                                                 "status": "idle"}})
            m = re.fullmatch(r"/runs/([\w-]+)/actions", self.path)
            if m:
                run = state.runs.get(m.group(1))
                if not run:
                    return self._send(404, {"errors": [{"detail": "no run"}]})
                action = ((json.loads(raw or b"{}").get("data") or {})
                          .get("actionType"))
                if action not in ("play", "pause", "stop"):
                    return self._send(422, {"errors": [{"detail":
                        "actionType must be play|pause|stop"}]})
                run["status"] = {"play": "running", "pause": "idle",
                                 "stop": "stopped"}[action]
                return self._send(200, {"data": run["commands"]})
            return self._send(404, {"errors": [{"detail": "no route"}]})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    return server, state


class SimulatedRobot:
    """Context manager: run the sim on an ephemeral port in a thread."""

    def __init__(self):
        self.server, self.state = make_server()
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       daemon=True)

    @property
    def base_url(self) -> str:
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}"

    def __enter__(self) -> "SimulatedRobot":
        self.thread.start()
        return self

    def __exit__(self, *a):
        self.server.shutdown()
        self.server.server_close()
