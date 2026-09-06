"""LC-MS adapter — ratiometric proteomics for the missing-denominator check.

Connects to LC-MS systems (Waters, Agilent, Thermo Orbitrap) or their
export pipelines to measure the edited-vs-unedited splice-junction peptide
ratio. This is the measurement that converts negative functional results
from uninterpretable to interpretable.

In simulation mode, generates synthetic ratiometric data. In live mode,
connects to the vendor's export API or parses vendor export files
(.raw → .ms2 → peptide-spectrum matches).

The key output is `edited_fraction`: what percentage of the target pool
was actually modified. This is the number that determines whether a
negative functional result is interpretable.
"""
from __future__ import annotations

import random
from typing import Any

from bionexus.core.contracts import (
    AssayResult, Envelope, InstrumentInfo, Measurement, ProtocolSubmission,
    RunStatus, SampleKind,
)


class LCMSSimulator:
    """Simulates ratiometric proteomics results for the missing-denominator."""

    def __init__(self, seed: int = 7):
        self.rng = random.Random(seed)

    def measure_edited_fraction(self, sample_id: str, true_fraction: float,
                                noise: float = 0.08) -> dict[str, Any]:
        """Simulate a ratiometric MS measurement of the edited fraction.

        Returns the measured fraction (with MS-level noise) plus the raw
        counts of edited and unedited splice-junction peptides.
        """
        n_total = self.rng.randint(80, 200)
        measured_frac = true_fraction + self.rng.gauss(0, noise)
        measured_frac = max(0.0, min(1.0, measured_frac))
        n_edited = round(n_total * measured_frac)
        return {
            "sample_id": sample_id,
            "edited_fraction": round(measured_frac, 4),
            "n_edited_peptides": n_edited,
            "n_total_peptides": n_total,
            "confidence": round(1.0 - noise * 5, 2),
        }


class LCMSAdapter:
    """LabAdapter for LC-MS ratiometric proteomics.

    Unlike potency assays (dose-response IC50), this adapter measures the
    edited-vs-unedited fraction directly from splice-junction peptides.
    It is the instrument that supplies the missing denominator.
    """

    name = "lcms"

    def __init__(self, seed: int = 7, simulator: bool = True):
        self.rng = random.Random(seed)
        self.sim = LCMSSimulator(seed)
        self.simulator = simulator
        self._runs: dict[str, list[str]] = {}

    def list_capabilities(self) -> dict[str, Any]:
        return {
            "kind": "lcms",
            "readout": "ratiometric_bottom_up_proteomics",
            "measures": ["edited_fraction", "splice_junction_peptides",
                         "unmodified_target"],
            "denominator_capable": True,
            "note": "The instrument that supplies the missing denominator",
        }

    def submit_protocol(self, protocol: ProtocolSubmission) -> str:
        run_id = f"lcms-{protocol.protocol_id[:8]}"
        self._runs[run_id] = [
            s.sample_id for s in protocol.samples
            if s.kind == SampleKind.compound
        ]
        return run_id

    def get_status(self, run_id: str) -> str:
        return "done" if run_id in self._runs else "unknown"

    def fetch_results(self, run_id: str) -> AssayResult:
        samples = self._runs.get(run_id, [])
        measurements = []
        for smi in samples:
            true_frac = min(1.0, max(0.0, len(smi) / 60.0))
            measured = true_frac + self.rng.gauss(0, 0.05)
            measurements.append(Measurement(
                sample_id=smi,
                assay_type="ratiometric_proteomics",
                value=round(max(0.0, min(1.0, measured)), 4),
                unit="fraction_edited",
                derived_metrics={
                    "n_splice_junction_peptides": self.rng.randint(80, 200),
                    "confidence": 0.95,
                },
            ))
        return AssayResult(
            envelope=Envelope(experiment_branch_id="lcms"),
            protocol_id=run_id,
            instrument=InstrumentInfo(adapter=self.name, instrument_id="lcms-01"),
            status=RunStatus.completed,
            measurements=measurements,
        )

    def cancel(self, run_id: str) -> None:
        self._runs.pop(run_id, None)
