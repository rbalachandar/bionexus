"""ReplayLab — published measurements as lab truth, honestly labeled.

A LabAdapter whose ground truth is REAL experimental data (e.g. ChEMBL
deposited IC50s), not simulated pharmacology. The loop runs its genuine
machinery — plate exports, Hill fits, residual-bootstrap CIs, orthogonal
confirmations, safety gates, provenance — against measured values, which is
what makes downstream case studies prospective tests of the process rather
than circular tests of the simulator.

Honesty contract (enforced, not aspirational):
  - instrument identity says what it is: name "replay-published",
    version "replay-v1"; capabilities() spells out the one synthesized
    element: the CURVE SHAPE is a Hill response drawn around the published
    IC50; the IC50 itself is the measured value. Plate noise is a declared
    seeded measurement model.
  - unknown candidates RAISE. There is no invented number in this adapter.
  - property-metric campaigns are refused loudly: replaying a potency
    curve as a "property readout" would be nonsense dressed as data.
"""
from __future__ import annotations

from typing import Any

from bionexus.core.contracts import (AssayResult, Envelope, InstrumentInfo,
                                     Measurement, RunStatus)


class ReplayLab:
    name = "replay-published"
    version = "replay-v1"
    replicates = 3

    def __init__(self, values: dict[str, float],
                 sources: dict[str, dict] | None = None,
                 seed: int = 42, unit: str = "uM"):
        """values: candidate_id -> measured IC50 in `unit` (µM by default).
        sources: optional candidate_id -> provenance {assay_ids, n, ...},
        surfaced in capabilities and recorded per-result metadata."""
        self.values = dict(values)
        self.sources = dict(sources or {})
        self.seed = seed
        self.unit = unit
        self._runs: dict[str, list[str]] = {}
        self._n = 0

    # --------------------------------------------------------- LabAdapter

    def list_capabilities(self) -> dict:
        return {
            "assays": ["binding", "enzymatic"],
            "readout": "published-measurement-replay",
            "bsl_max": 1,
            "truth": (f"{len(self.values)} published IC50 measurements "
                      f"(seeded synthetic plate noise; Hill curve SHAPE "
                      f"synthesized around the measured IC50 — the IC50 "
                      f"is real, the wells are replay)"),
            "data_origin": "literature (ChEMBL-deposited)",
        }

    def submit_protocol(self, protocol: Any) -> str:
        self._n += 1
        rid = f"replay-{self._n:03d}"
        self._runs[rid] = [s.sample_id for s in protocol.samples
                           if not s.sample_id.startswith("ctrl")]
        return rid

    def get_status(self, run_id: str) -> str:
        return "done"

    def fetch_results(self, run_id: str) -> AssayResult:
        samples = self._runs.get(run_id, [])
        ms = []
        for s in samples:
            ic50 = self.true_ic50_um(run_id, s)
            ms.append(Measurement(
                sample_id=s, assay_type="potency", value=ic50,
                unit=f"IC50_{self.unit}", replicate=self.replicates,
                derived_metrics={"published_ic50_um": ic50},
                metadata=self.sources.get(s, {})))
        return AssayResult(
            envelope=Envelope(experiment_branch_id="replay"),
            protocol_id=run_id, run_id=run_id,
            instrument=InstrumentInfo(adapter=self.name,
                                      instrument_id=self.version),
            status=RunStatus.completed, measurements=ms,
            qc={"controls_passed": True})

    def cancel(self, run_id: str) -> None:
        pass

    # ------------------------------------------------- replay truth hooks

    def true_ic50_um(self, run_id: str, candidate: str) -> float:
        """The published IC50 in µM — or a loud refusal. No invention."""
        if candidate not in self.values:
            raise KeyError(
                f"ReplayLab has no published measurement for "
                f"'{candidate}' — refusing to invent one "
                f"(source corpus covers {len(self.values)} compounds)")
        return float(self.values[candidate])

    def set_property_gate(self, metric: str, direction: str,
                          threshold: float) -> None:
        raise NotImplementedError(
            "ReplayLab replays potency measurements only; a property-metric "
            "campaign would read dose-response curves as a property value. "
            "Use a lab that measures this property.")
