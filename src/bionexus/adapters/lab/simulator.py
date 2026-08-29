"""Virtual Lab Simulator — deterministic, seeded assay outcomes (P4, P8).

Implements LabAdapter. Same contract as any hardware adapter; CI runs this.
Outcome model: per-assay baseline response modulated by a seeded per-sample
factor + gaussian noise, so workflows are reproducible given a seed.
"""
from __future__ import annotations

import hashlib
import random
from typing import Any

from bionexus.core.contracts import (
    AssayResult,
    Envelope,
    InstrumentInfo,
    Measurement,
    ProtocolSubmission,
    RunStatus,
)

# assay -> (baseline_value, unit, noise_std)
ASSAY_PROFILE: dict[str, tuple[float, str, float]] = {
    "binding": (62.0, "percent_inhibition", 8.0),
    "enzymatic": (55.0, "percent_inhibition", 10.0),
    "cytotoxicity": (40.0, "percent_viability", 12.0),
    "adme": (70.0, "permeability_score", 9.0),
    "plate_reader": (60.0, "od450", 0.15),
    "custom": (50.0, "signal", 10.0),
}


class SimulatorLab:
    name = "simulator"

    def __init__(self, seed: int = 7, instruments: dict[str, Any] | None = None):
        self.seed = seed
        self._runs: dict[str, ProtocolSubmission] = {}
        self._capabilities = instruments or {
            "assays": ["binding", "enzymatic", "cytotoxicity", "adme", "plate_reader"],
            "throughput": {"plates_per_day": 20},
            "bsl_max": 2,
        }

    def list_capabilities(self) -> dict[str, Any]:
        return dict(self._capabilities)

    def submit_protocol(self, protocol: ProtocolSubmission) -> str:
        run_id = f"sim-{protocol.protocol_id[:8]}"
        self._runs[run_id] = protocol
        return run_id

    def get_status(self, run_id: str) -> str:
        return "done" if run_id in self._runs else "failed"

    def fetch_results(self, run_id: str) -> AssayResult:
        protocol = self._runs[run_id]
        base, unit, noise = ASSAY_PROFILE.get(protocol.assay_type.value, ASSAY_PROFILE["custom"])
        measurements: list[Measurement] = []
        controls_passed = True
        for i, sample in enumerate(protocol.samples):
            rng = random.Random(self._sample_seed(run_id, sample.sample_id))
            value = base * (0.7 + 0.6 * rng.random()) + rng.gauss(0, noise)
            is_control = sample.kind.value == "buffer" or sample.sample_id.startswith("ctrl")
            if is_control:
                value = base
                if value < base * 0.5:
                    controls_passed = False
            measurements.append(
                Measurement(
                    sample_id=sample.sample_id,
                    well=f"A{i + 1}" if not is_control else f"CTRL{i + 1}",
                    assay_type=protocol.assay_type.value,
                    value=round(value, 3),
                    unit=unit,
                    uncertainty=round(noise / 2, 3),
                    flags=["control"] if is_control else [],
                )
            )
        return AssayResult(
            envelope=Envelope(experiment_branch_id="simulator"),
            protocol_id=protocol.protocol_id,
            instrument=InstrumentInfo(adapter=self.name, instrument_id=f"{self.name}-01"),
            status=RunStatus.completed,
            measurements=measurements,
            qc={"controls_passed": controls_passed},
        )

    def cancel(self, run_id: str) -> None:
        self._runs.pop(run_id, None)

    def _sample_seed(self, run_id: str, sample_id: str) -> int:
        material = f"{self.seed}:{run_id}:{sample_id}".encode()
        return int(hashlib.sha256(material).hexdigest()[:8], 16)
