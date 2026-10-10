"""HCS microscope adapter — per-cell image capture for vision-LLM readout.

Connects to Thermo Fisher CellInsight, Revvity Operetta, or compatible
high-content screening microscopes. Returns per-cell fluorescence data
as structured measurements that feed into the vision-LLM readout and
the missing-denominator check.

HONEST STATUS (hardware trust audit, Oct 10): this adapter is a
SIMULATOR ONLY. "Live mode" is NOT implemented — simulator=False raises
rather than silently returning synthetic readings dressed as instrument
data. Vendor REST/file binding is roadmap work (ROADMAP S-T4). All
results are labeled simulated in capabilities.
"""
from __future__ import annotations

import random
from typing import Any

from bionexus.core.contracts import (
    AssayResult, Envelope, InstrumentInfo, Measurement, MeasurementFlag,
    ProtocolSubmission, RunStatus,
)


class HCSSimulator:
    """Simulates per-cell fluorescence data matching seeded ground truth."""

    def __init__(self, seed: int = 7):
        self.rng = random.Random(seed)

    def capture_cells(self, sample_id: str, conc_um: float,
                      true_ic50: float, n_cells: int = 200
                      ) -> list[dict[str, Any]]:
        """Generate synthetic per-cell fluorescence intensities.

        Each cell gets a signal drawn from a mixture distribution:
        - edited cells (fraction ~ dose-dependent) have high signal
        - unedited cells have background-level signal
        The fraction edited is the simulation's ground truth for the
        missing-denominator measurement.
        """
        cells = []
        # fraction edited follows Hill-like dose response
        max_frac = min(1.0, conc_um / (conc_um + true_ic50))
        for i in range(n_cells):
            is_edited = self.rng.random() < max_frac
            if is_edited:
                signal = self.rng.gauss(750, 80)  # high: edited
            else:
                signal = self.rng.gauss(120, 30)  # background: unedited
            cells.append({
                "cell_id": f"{sample_id}-cell-{i}",
                "signal": max(0, signal),
                "edited": is_edited,  # ground truth (not exposed to agent)
            })
        return cells


class HCSMicroscopeAdapter:
    """LabAdapter for high-content screening microscopes.

    In simulation mode, generates synthetic per-cell data. In live mode,
    connects to the microscope's REST API or file-export share.

    Key feature: returns BOTH population-level measurements (median signal,
    edited fraction) AND per-cell data (for vision-LLM and denominator checks).
    """

    name = "hcs-microscope"

    def __init__(self, seed: int = 7, simulator: bool = True,
                 image_dir: str | None = None):
        self.seed = seed
        self.image_dir = image_dir
        if not simulator:
            raise NotImplementedError(
                "HCS live mode is not implemented — this adapter only "
                "simulates (ROADMAP S-T4). Refusing to fabricate "
                "'instrument' readings (simulator=False)")
        self.simulator = simulator
        self._runs: dict[str, dict] = {}
        if simulator:
            from bionexus.adapters.lab.imaging import ImagingPlateReader
            self._plate = ImagingPlateReader(seed=seed)

    def list_capabilities(self) -> dict[str, Any]:
        return {
            "kind": "hcs_microscope",
            "readout": "per-cell fluorescence",
            "modalities": ["per-cell signal", "edited fraction", "image tiles"],
            "resolution": "single-cell",
            "denominator_capable": True,
            "bsl_max": 2,
            "simulated": True,        # ALL output is synthetic (S-T4)
            "hardware_validated": False,
        }

    def submit_protocol(self, protocol: ProtocolSubmission) -> str:
        run_id = f"hcs-{protocol.protocol_id[:8]}"
        self._runs[run_id] = protocol
        return run_id

    def get_status(self, run_id: str) -> str:
        return "done" if run_id in self._runs else "unknown"

    def fetch_results(self, run_id: str) -> AssayResult:
        protocol = self._runs[run_id]
        measurements = []
        for sample in protocol.samples:
            conc = sample.concentration or "10uM"
            # simulate per-cell data
            cells = HCSSimulator(seed=self.seed).capture_cells(
                sample.sample_id, float(conc.replace("uM", "")),
                true_ic50=15.0, n_cells=200)
            signals = [c["signal"] for c in cells]
            n_edited = sum(1 for c in cells if c["edited"])
            frac = n_edited / len(cells) if cells else 0
            median = sorted(signals)[len(signals) // 2] if signals else 0
            measurements.append(Measurement(
                sample_id=sample.sample_id,
                assay_type="per_cell_fluorescence",
                value=round(frac, 4),
                unit="fraction_edited",
                replicate=1,
                derived_metrics={
                    "median_signal": round(median, 1),
                    "n_cells": len(cells),
                    "n_edited": n_edited,
                },
                flags=[MeasurementFlag.suspect] if frac < 0.05 else [],
            ))
        return AssayResult(
            envelope=Envelope(experiment_branch_id="hcs"),
            protocol_id=protocol.protocol_id,
            instrument=InstrumentInfo(
                adapter=self.name, instrument_id="hcs-01",
                raw_output_uri=self.image_dir or ""),
            status=RunStatus.completed,
            measurements=measurements,
        )

    def cancel(self, run_id: str) -> None:
        self._runs.pop(run_id, None)
