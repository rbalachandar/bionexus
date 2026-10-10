"""Atlas Scientific EZO pH probe — wire-level LabAdapter proof (S-T4 POC).

THE PATTERN under test here: fine-grained instrument verbs (Cal, r, sleep...)
live at the WIRE; the agent surface speaks ProtocolSubmission; the gateway
decides in between. A raw command is NEVER offered as a tool — a datasheet-
faithful wire simulator lets the same adapter run against a real UART bridge
by changing the transport only.

Provenance, stated honestly:
  * Command/reply grammar (*OK / *ER / ?i,pH,2.16, wake-on-first-char *WA,
    calibration ladder) per the public Atlas Scientific EZO-pH(J) datasheets.
  * The simulator is a hermetic stand-in for K-Dense LabMCP's
    labmcp_atlas_ezo.EZOSimulator (Apache-2.0,
    github.com/K-Dense-AI/lab-instrument-mcps) — notably its calibration-
    reduces-error fidelity. PRODUCTION PATH: import that simulator (or a
    real serial bridge) behind the same `_tx` seam; this in-repo copy exists
    so CI stays hermetic (P8) and NOT to own an instrument manual.
  * Status: SIMULATED. Never hardware-confirmed. hardware_validated=False
    is surfaced in capabilities and must survive into any UI rendering.
"""
from __future__ import annotations

import random
import re
import time
from typing import Any, Callable

from bionexus.core.contracts import (AssayResult, Envelope, InstrumentInfo,
                                     Measurement, ProtocolSubmission,
                                     RunStatus)


class EzoPHLine:
    """Wire-level EZO-pH UART simulator: bytes in, bytes out.

    `handle(command)` returns the device's raw reply. The uncertainty a
    real probe advertises is a FUNCTION of calibration state — that
    fidelity (borrowed from LabMCP's simulator) is the whole point: it
    lets CI prove our verdict physics degrades honestly with uncalibrated
    hardware, instead of pretending every reading is equally trustworthy.
    """

    _FIRMWARE = "2.16"
    # (uncertainty when NO calibration, with mid only, full 2/3-pt)
    _ERR = {"none": 0.120, "mid": 0.030, "buffered": 0.005}

    def __init__(self, sample_ph: float = 7.20, seed: int = 7,
                 clock: Callable[[], float] = time.monotonic):
        self.sample_ph = sample_ph
        self.rng = random.Random(seed)
        self.clock = clock
        self.t0 = clock()
        self.cal_points: set[str] = set()
        self.continuous = 0          # datasheet ships 1; adapter sends C,0
        self.asleep = False
        self.log: list[tuple[str, str]] = []

    @property
    def uncertainty(self) -> float:
        if not self.cal_points:
            return self._ERR["none"]
        if self.cal_points & {"low", "high"}:
            return self._ERR["buffered"]
        return self._ERR["mid"]

    def _reading(self) -> str:
        drift = 0.004 * ((self.clock() - self.t0) / 60.0)   # slow wander
        noise = self.rng.gauss(0.0, 0.002)
        return f"{self.sample_ph + drift + noise:.3f}"

    def handle(self, command: str) -> str:
        cmd = command.strip()
        if cmd == "":
            return ""
        if self.asleep:
            self.asleep = False       # first character wakes; command lost
            return self._logq(cmd, "*WA")
        reply = self._dispatch(cmd)
        return self._logq(cmd, reply)

    def _logq(self, cmd: str, reply: str) -> str:
        self.log.append((cmd, reply))
        return reply

    def _dispatch(self, cmd: str) -> str:
        parts = [p.strip() for p in cmd.split(",")]
        head = parts[0].lower()
        if head == "i" and len(parts) == 1:
            return f"?i,pH,{self._FIRMWARE}*OK"
        if head == "r" and len(parts) == 1:
            return f"{self._reading()}*OK"
        if head == "c" and len(parts) == 2:
            n = parts[1]
            if not n.isdigit() or not 0 <= int(n) <= 99:
                return "*ER"
            self.continuous = int(n)
            return "*OK"
        if head == "cal":
            return self._cal(parts[1:])
        if head == "status":
            return "?Status,P,5.038*OK"
        if head == "sleep":
            self.asleep = True
            return "*SL"
        if head == "factory":
            self.cal_points.clear()
            return "*OK*RS*RE"
        return "*ER"                  # unknown command, per datasheet

    def _cal(self, args: list[str]) -> str:
        if not args:
            return "*ER"
        if args[0] == "?":
            return f"?Cal,{len(self.cal_points)}*OK"
        if args[0] == "clear":
            self.cal_points.clear()
            return "*OK"
        if len(args) != 2 or args[0] not in {"low", "mid", "high"}:
            return "*ER"
        try:
            float(args[1])
        except ValueError:
            return "*ER"
        if args[0] == "mid":
            self.cal_points = {"mid"}   # datasheet: mid clears the others
        else:
            self.cal_points.add(args[0])
        return "*OK"


class EzoPHProbe:
    """BioNexus LabAdapter: a sensor, not an assay robot.

    Protocol semantics: each submission declares probe points as samples;
    optional calibration via reagent metadata. submit_protocol compiles
    that to wire commands (r, Cal,...) — the compilation step is exactly
    what keeps `Cal` OUT of any agent's tool list.
    """

    name = "ezo_ph"

    def __init__(self, line: EzoPHLine | None = None,
                 address: str = "serial:///dev/ttyUSB0?baud=115200"):
        self.line = line or EzoPHLine()
        self.address = address
        self._runs: dict[str, dict[str, Any]] = {}
        self._seq = 0

    # -- transport seam: production swaps this for a real serial bridge ---

    def _tx(self, command: str, retries: int = 2) -> str:
        reply = self.line.handle(command)
        # datasheet wake quirk: retry ONCE after *WA — this discipline is
        # WHY the wire sim exists; mocks that skip quirks teach lies
        for _ in range(retries):
            if reply == "*WA":
                reply = self.line.handle(command)
            else:
                break
        if reply.endswith("*ER") or reply == "*ER":
            raise RuntimeError(f"probe rejected command {command!r}: {reply}")
        return reply

    # -- LabAdapter protocol ------------------------------------------------

    def list_capabilities(self) -> dict[str, Any]:
        """For planner/readiness: WHAT the instrument can report, never
        HOW to command it."""
        return {
            "kind": "sensor",
            "readout": "pH",
            "range_ph": [0.0, 14.0],
            "resolution": 0.001,
            "interface": self.address,
            "calibration": {
                "states": ["uncalibrated", "mid", "buffered"],
                "uncertainty_ph": {"uncalibrated": EzoPHLine._ERR["none"],
                                   "mid": EzoPHLine._ERR["mid"],
                                   "buffered": EzoPHLine._ERR["buffered"]},
            },
            "simulated": True,
            "hardware_validated": False,
            "provenance": "wire grammar per EZO-pH(J) datasheets; simulator "
                          "stands in for labmcp_atlas_ezo (K-Dense, "
                          "Apache-2.0); production = real bridge or import",
        }

    def submit_protocol(self, protocol: ProtocolSubmission) -> str:
        for point in protocol.samples:
            cal = (point.metadata or {}).get("calibrate")
            if cal:                      # operator-declared calibration
                if cal == "clear":
                    self._tx("Cal,clear")
                else:                    # e.g. "mid,7.00"
                    self._tx(f"Cal,{cal}")
        self._tx("c,0")                  # stop continuous mode (deterministic)
        n = max(1, int((protocol.steps[0].params or {}).get("reads", 3))
                if protocol.steps else 3)
        readings = [self._read() for _ in range(n)]
        self._seq += 1
        run_id = f"ezo-{self._seq:03d}"
        self._runs[run_id] = {
            "protocol": protocol, "readings": readings,
            "uncertainty": self.line.uncertainty,
            "cal_state": sorted(self.line.cal_points) or ["uncalibrated"],
            "log_len": len(self.line.log),
        }
        return run_id

    def _read(self) -> float:
        reply = self._tx("r")
        m = re.fullmatch(r"([-+]?\d+\.\d+)\*OK", reply)
        if not m:
            raise RuntimeError(f"unparsable probe reply: {reply!r}")
        return float(m.group(1))

    def get_status(self, run_id: str) -> str:
        return "done" if run_id in self._runs else "unknown"

    def fetch_results(self, run_id: str) -> AssayResult:
        run = self._runs[run_id]
        readings: list[float] = run["readings"]
        mean = sum(readings) / len(readings)
        sd = (sum((r - mean) ** 2 for r in readings)
              / max(1, len(readings) - 1)) ** 0.5
        protocol: ProtocolSubmission = run["protocol"]
        return AssayResult(
            envelope=Envelope(experiment_branch_id="ezo_ph"),
            run_id=run_id,
            protocol_id=protocol.protocol_id,
            instrument=InstrumentInfo(
                adapter="ezo_ph(sim)", instrument_id="ezo-ph-sim-01",
                raw_output_uri=f"wire-log://{run_id}?entries={run['log_len']}"),
            status=RunStatus.completed,
            measurements=[Measurement(
                sample_id=s.sample_id, assay_type="ph",
                value=round(mean, 3), unit="pH",
                uncertainty=round(run["uncertainty"], 3),
                derived_metrics={"n_reads": len(readings),
                                 "sd_reads": round(sd, 4)},
                metadata={"cal_state": run["cal_state"]})
                for s in protocol.samples
                if s.kind.value != "buffer"] or [Measurement(
                sample_id="probe", assay_type="ph", value=round(mean, 3),
                unit="pH", uncertainty=round(run["uncertainty"], 3),
                metadata={"cal_state": run["cal_state"]})],
            qc={"controls_passed": True,
                "calibration": run["cal_state"],
                "note": "SIMULATED instrument (S-T4 POC); uncertainty is the "
                        "probe's calibration-state error, not fitted noise"},
        )
