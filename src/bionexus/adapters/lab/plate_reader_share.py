"""PlateReaderShare — adapter for network-share plate readers.

Most core-lab plate readers (Biotek Gen5, SoftMax Pro, SpectraMax, ClarioStar)
can be configured to **auto-export every completed read** to a network share.
This adapter treats that share as the device: register the expected run, then
`fetch_results` parses the newest matching export with `labread` (format
autodetect, control discovery, IC50 fit, Z' QC).

Real workflow, zero vendor SDKs. All parsing already exists in `labread`.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from bionexus.core.contracts import (
    AssayResult, Envelope, InstrumentInfo, ProtocolSubmission, RunStatus,
)
from bionexus.labread import read_plate


class PlateReaderShare:
    """LabAdapter over a watched share where the reader drops export files."""

    name = "plate-reader-share"

    def __init__(self, share_dir: str | Path, assay: str = "binding",
                 max_response: float | None = None,
                 wait_secs: int = 300, poll_secs: float = 2.0,
                 suffix: str = ".csv"):
        self.share = Path(share_dir)
        self.share.mkdir(parents=True, exist_ok=True)
        self.assay = assay
        self.max_response = max_response
        self.wait_secs = wait_secs
        self.poll_secs = poll_secs
        self.suffix = suffix
        self._expected: dict[str, tuple[float, ProtocolSubmission]] = {}

    # -- contract -------------------------------------------------------------

    def list_capabilities(self) -> dict[str, Any]:
        return {"kind": "plate_reader", "readout": "auto-export-share",
                "assays": [self.assay],
                "formats": ["csv", "tsv", "xlsx", "grid"],
                "note": "reader must be configured to auto-export to the share"}

    def submit_protocol(self, protocol: ProtocolSubmission) -> str:
        """Register the run; the physical read is triggered by the technician /
        robot deck, and the reader's auto-export lands in the share."""
        run_id = f"share-{protocol.protocol_id[:8]}"
        self._expected[run_id] = (time.time(), protocol)
        return run_id

    def get_status(self, run_id: str) -> str:
        try:
            self._result(run_id)
            return "done"
        except FileNotFoundError:
            age = time.time() - self._expected.get(run_id, (time.time(), None))[0]
            return "failed" if age > self.wait_secs else "running"

    def fetch_results(self, run_id: str) -> AssayResult:
        export, protocol = self._result(run_id)
        plate = read_plate(export, max_response=self.max_response)
        measurements = []
        for sample, r in plate.analysis["compounds"].items():
            if r["ic50_um"] is None:
                continue
            from bionexus.core.contracts import Measurement
            measurements.append(Measurement(
                sample_id=sample, assay_type=self.assay,
                value=r["ic50_um"], unit="uM",
                derived_metrics={"ic50_um": r["ic50_um"],
                                 "z_prime": plate.z_prime},
            ))
        return AssayResult(
            envelope=Envelope(experiment_branch_id="plate-reader-share"),
            protocol_id=protocol.protocol_id,
            instrument=InstrumentInfo(adapter=self.name, instrument_id=str(export),
                                      raw_output_uri=str(export)),
            status=RunStatus.completed,
            measurements=measurements,
            qc={"controls_passed": (plate.z_prime or 0) >= 0.3,
                "z_prime": plate.z_prime},
        )

    def cancel(self, run_id: str) -> None:
        self._expected.pop(run_id, None)

    # -- internals ------------------------------------------------------------

    def _result(self, run_id: str) -> tuple[Path, ProtocolSubmission]:
        if run_id not in self._expected:
            raise KeyError(f"unknown run {run_id}")
        created, protocol = self._expected[run_id]
        candidates = sorted(self.share.glob(f"*{self.suffix}"),
                            key=lambda p: p.stat().st_mtime)
        # newest export created after this run was submitted
        for export in reversed(candidates):
            if export.stat().st_mtime >= created - 1:
                return export, protocol
        age = time.time() - created
        if age > self.wait_secs:
            raise FileNotFoundError(
                f"no export appeared in {self.share} within {self.wait_secs}s")
        raise FileNotFoundError(f"export pending ({age:.0f}s)")
