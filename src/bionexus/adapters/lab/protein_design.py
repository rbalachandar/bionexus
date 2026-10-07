"""ProteinDesignLabAdapter — protein binder design as a BioNexus LabAdapter.

Wraps BindCraft (Make: generation) and Boltz-1 (Test: interface screening)
behind the LabAdapter protocol so the DMTA loop orchestrates protein design
through the same gateway → provenance → verdict pipeline as small molecules.

The agent proposes a hypothesis ("design a binder to PD-L1 hotspot 56");
this adapter executes it; BioNexus's verdict machinery scores the results.
Every design is provenance-chained. Every refusal is recorded. The agent
never touches BindCraft directly.

Mock mode: deterministic pseudo-designs for CI — no GPU, no BindCraft.
"""
from __future__ import annotations

import hashlib
import random
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from bionexus.core.contracts.models import (
    AssayResult, ArtifactKind, Envelope, InstrumentInfo, Measurement,
    MeasurementFlag, ProtocolSubmission, QCInfo, RunStatus,
)


class ProteinDesignLabAdapter:
    """LabAdapter for in-silico protein binder design (BindCraft + Boltz)."""

    name = "protein-design"

    def __init__(self, bindcraft_dir: str | None = None,
                 boltz_venv: str | None = None,
                 work_dir: str | None = None,
                 mock: bool = False, seed: int = 42):
        self.bindcraft_dir = bindcraft_dir
        self.boltz_venv = boltz_venv
        self.work_dir = Path(work_dir or tempfile.mkdtemp(prefix="prot-design-"))
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.mock = mock
        self.seed = seed
        self._runs: dict[str, dict] = {}

    def list_capabilities(self) -> dict[str, Any]:
        return {
            "assays": ["protein_binder_design"],
            "modalities": ["protein"],
            "make_tool": "BindCraft (AlphaFold2 backprop + ProteinMPNN)",
            "test_tool": "Boltz-1 (interface confidence)",
            "design_throughput": "~8 designs/hour on RTX 3090",
            "constraints": {
                "max_binder_length": 250,
                "single_chain": True,
                "target_input": "PDB structure",
            },
        }

    def submit_protocol(self, protocol: ProtocolSubmission) -> str:
        run_id = protocol.protocol_id
        self._runs[run_id] = {"status": "queued", "protocol": protocol,
                              "results": None}
        return run_id

    def get_status(self, run_id: str) -> str:
        return self._runs.get(run_id, {}).get("status", "unknown")

    def cancel(self, run_id: str) -> None:
        if run_id in self._runs:
            self._runs[run_id]["status"] = "cancelled"

    def execute(self, run_id: str, target_pdb: str,
                hotspot_residues: str = "56",
                binder_lengths: tuple[int, int] = (70, 120),
                n_designs: int = 20,
                iptm_threshold: float = 0.7) -> AssayResult:
        """Run the full design → screen pipeline for one target.

        This is the Make→Test cycle: BindCraft generates, Boltz screens.
        Returns an AssayResult with per-design measurements.
        """
        run = self._runs.get(run_id)
        if not run:
            raise ValueError(f"unknown run_id: {run_id}")
        run["status"] = "running"

        designs = self._generate(run_id, target_pdb, hotspot_residues,
                                 binder_lengths, n_designs)
        screened = self._screen(designs, target_pdb, iptm_threshold)

        measurements = []
        for d in screened:
            m = Measurement(
                sample_id=d["name"],
                assay_type="protein_binder_design",
                value=d.get("iptm", d.get("plddt", 0.0)),
                unit="iptm",
                uncertainty=d.get("uncertainty"),
            )
            if d.get("extrapolation"):
                m.flags = [MeasurementFlag.suspect]
            measurements.append(m)

        n_pass = sum(1 for d in screened if d.get("iptm", 0) >= iptm_threshold)
        qc = QCInfo(
            controls_passed=n_pass > 0,
            notes=f"{n_pass}/{len(screened)} designs above ipTM {iptm_threshold}",
        )

        result = AssayResult(
            envelope=Envelope(experiment_branch_id=f"design/{run_id}"),
            protocol_id=run_id,
            instrument=InstrumentInfo(
                adapter=self.name,
                instrument_id="bindcraft+boltz",
                raw_output_uri=str(self.work_dir / run_id),
            ),
            status=RunStatus.completed if screened else RunStatus.failed,
            measurements=measurements,
            qc=qc,
        )
        run["status"] = "done"
        run["results"] = result
        return result

    def _generate(self, run_id: str, target_pdb: str, hotspot: str,
                  lengths: tuple[int, int], n: int) -> list[dict[str, Any]]:
        """Make step: generate binder designs. Mock or BindCraft subprocess."""
        if self.mock:
            return self._mock_generate(run_id, n)
        # real BindCraft call: subprocess to bindcraft.py
        # (settings JSON written, bindcraft.py invoked with conda env)
        return self._bindcraft_generate(target_pdb, hotspot, lengths, n)

    def _screen(self, designs: list[dict], target_pdb: str,
                threshold: float) -> list[dict[str, Any]]:
        """Test step: Boltz-1 interface confidence per design."""
        if self.mock:
            return self._mock_screen(designs, threshold)
        return self._boltz_screen(designs, target_pdb, threshold)

    def _mock_generate(self, run_id: str, n: int) -> list[dict[str, Any]]:
        rng = random.Random(self.seed)
        designs = []
        for i in range(n):
            length = rng.randint(70, 120)
            aa = "ACDEFGHIKLMNPQRSTVWY"
            seq = "".join(rng.choice(aa) for _ in range(length))
            designs.append({"name": f"mock-{run_id}-{i:03d}", "sequence": seq,
                            "plddt": round(0.5 + rng.random() * 0.5, 3)})
        return designs

    def _mock_screen(self, designs: list[dict], threshold: float) -> list[dict]:
        rng = random.Random(self.seed + 1)
        for d in designs:
            d["iptm"] = round(rng.random(), 3)
            d["plddt"] = round(rng.random() * 100, 1)
            d["extrapolation"] = rng.random() < 0.2
            d["uncertainty"] = round(rng.random() * 0.1, 4)
        return designs

    def _bindcraft_generate(self, *args, **kwargs) -> list[dict]:
        if not self.bindcraft_dir:
            raise RuntimeError("BindCraft not configured — set bindcraft_dir")
        # subprocess invocation: same pattern as autoloop's Make step
        raise NotImplementedError("real BindCraft integration: see runpack/jobrunner.py")

    def _boltz_screen(self, *args, **kwargs) -> list[dict]:
        if not self.boltz_venv:
            raise RuntimeError("Boltz venv not configured — set boltz_venv")
        raise NotImplementedError("real Boltz screening: see runpack/jobrunner.py")
