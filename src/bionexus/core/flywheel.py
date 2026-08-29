"""Fine-tuning flywheel (T4.4) — turn confirmed assay results into training pairs.

The compounding asset (Cradle-style): every confirmed wet-lab/simulator result
becomes a labeled example for the next model round. Core implementation, stdlib
only; JSONL output is deliberately boring — import into any trainer.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from bionexus.core.contracts import AssayResult, ProtocolSubmission


class FlywheelLog:
    """Append-only JSONL of training pairs. One line per confirmed example."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def submit_example(
        self,
        input_payload: dict[str, Any],
        measured: AssayResult | dict[str, Any],
        model_version: str | None = None,
        branch_id: str | None = None,
    ) -> dict[str, Any]:
        """Record one (input, outcome) pair. `measured` is an AssayResult (the
        primary measurements become labels) or a raw dict."""
        if isinstance(measured, AssayResult):
            labels = [
                {"sample_id": m.sample_id, "assay_type": m.assay_type,
                 "value": m.value, "unit": m.unit}
                for m in measured.measurements
                if "control" not in [f.value for f in m.flags]
            ]
            source = {"run_id": measured.run_id, "instrument": measured.instrument.adapter}
        else:
            labels, source = measured, {"source": "external"}

        example = {
            "ts": time.time(),
            "model_version": model_version,
            "branch_id": branch_id,
            "input": input_payload,
            "labels": labels,
            "source": source,
        }
        with self.path.open("a") as f:
            f.write(json.dumps(example) + "\n")
        return example

    def pair_from_round(self, protocol: ProtocolSubmission, result: AssayResult) -> dict[str, Any]:
        """Convenience: build the input payload from the protocol's samples."""
        return self.submit_example(
            input_payload={
                "protocol_id": protocol.protocol_id,
                "assay_type": protocol.assay_type.value,
                "samples": [s.model_dump(mode="json") for s in protocol.samples],
            },
            measured=result,
            branch_id=protocol.envelope.experiment_branch_id,
        )

    def load(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text().splitlines() if line.strip()]
