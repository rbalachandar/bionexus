"""Simulated lab devices with image-based readouts (optional extra: numpy).

Layered realism — raw data first, analysis second:

  1. DEVICE: `ImagingPlateReader` exposes a 96-well plate. Each well is a
     synthetic fluorescence micrograph (tile x tile pixels) whose intensity
     encodes the seeded, dose-dependent ground truth (Hill curve over IC50),
     plus noise, vignetting, and per-well artifacts (edge effect, pipetting
     spike, bubble).
  2. ANALYSIS: `analyze_plate` computes per-well background-corrected median
     intensity, fits dose-response IC50 per compound, and computes assay QC.

`ImagingSimulatorLab` implements the LabAdapter contract on top, so agents get
AssayResults whose raw evidence is an actual image file — same shape as a real
plate reader with image capture.

Requires numpy (extra: `pip install bionexus[lab-imaging]`).
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

try:
    import numpy as np
except ImportError as exc:  # pragma: no cover
    raise ImportError("lab-imaging extra requires numpy: pip install bionexus[lab-imaging]") from exc

from bionexus.adapters.lab.simulator import (
    AssayResult,
    Envelope,
    InstrumentInfo,
    Measurement,
    MeasurementFlag,
    ProtocolSubmission,
    RunStatus,
    parse_concentration_um,
)

PLATE_ROWS, PLATE_COLS = 8, 12  # 96-well
TILE = 24                       # pixels per well micrograph
BONDS_PLACEHOLDER = None


def _seed(*parts: Any) -> int:
    return int(hashlib.sha256(":".join(str(p) for p in parts).encode()).hexdigest()[:8], 16)


def true_ic50_um(protocol_seed: int, sample_id: str) -> float:
    """Seeded true potency (0.5-50 uM), stable across runs."""
    return 0.5 + (_seed(protocol_seed, sample_id) % 1000) / 1000.0 * 49.5


def hill_response(conc_um: float, ic50_um: float, max_resp: float = 100.0) -> float:
    return max_resp / (1.0 + ic50_um / max(conc_um, 1e-6))


class ImagingPlateReader:
    """Synthetic 96-well fluorescence plate with image capture."""

    def __init__(self, seed: int = 7, tile: int = TILE, noise: float = 6.0,
                 artifact_rate: float = 0.04):
        self.seed = seed
        self.tile = tile
        self.noise = noise
        self.artifact_rate = artifact_rate

    def capture(self, run_id: str, well_spec: list[tuple[str, str, float]]) -> dict[str, dict]:
        """well_spec: (well_id, sample_id, conc_um). Returns {well_id: {image, ...}}.

        Pixel intensity = response-scaled cell blobs + background, with shot
        noise and vignetting; occasional well artifacts.
        """
        rng_art = random.Random(_seed("artifacts", run_id))
        yy, xx = np.mgrid[0:self.tile, 0:self.tile]
        vignette = 1.0 - 0.15 * (((yy - self.tile / 2) ** 2 + (xx - self.tile / 2) ** 2)
                                 / (self.tile / 2) ** 2)
        wells: dict[str, dict] = {}
        for well_id, sample_id, conc in well_spec:
            ic50 = true_ic50_um(self.seed, sample_id)
            response = hill_response(conc, ic50)
            # homogeneous whole-well fluorescence: uniform signal + cell texture
            rng = np.random.default_rng(_seed("img", run_id, well_id))
            img = rng.normal(0, self.noise, (self.tile, self.tile)) * vignette + 20.0
            img += response * 0.9                       # the measured signal
            n_cells = max(4, int(rng.normal(18, 5)))
            for _ in range(n_cells):                    # texture, response-independent
                cy = int(rng.integers(3, self.tile - 3))
                cx = int(rng.integers(3, self.tile - 3))
                img[cy - 2:cy + 3, cx - 2:cx + 3] += 3.0 * rng.uniform(0.6, 1.4)
            artifact = ""
            if rng_art.random() < self.artifact_rate:
                artifact = rng_art.choice(["edge_effect", "pipetting_spike", "bubble"])
                if artifact == "edge_effect":
                    img[:, :4] *= 0.4
                elif artifact == "pipetting_spike":
                    img[2:6, 2:6] += 400.0
                else:
                    img[10:18, 10:18] += 250.0
            wells[well_id] = {"image": img, "sample_id": sample_id,
                              "conc_um": conc, "artifact": artifact}
        return wells


def analyze_plate(plate: dict[str, dict]) -> dict[str, Any]:
    """Image analysis: background-corrected median intensity per well ->
    per-compound dose-response IC50 fit + assay QC."""
    raw: dict[str, list[tuple[str, float, float, str]]] = {}
    for well_id, v in plate.items():
        img = v["image"]
        raw.setdefault(v["sample_id"], []).append(
            (well_id, v["conc_um"], float(np.median(img)), v["artifact"]))
    # plate background = baseline of control wells (whole-well uniform signal
    # raises a well's own corners, so per-well subtraction would cancel it)
    ctrl_medians = [med for sample, vals in raw.items() if sample.startswith("ctrl")
                    for _, _, med, _ in vals]
    bg = float(np.median(ctrl_medians)) if ctrl_medians else 20.0
    intensities: dict[str, list[tuple[float, float, str]]] = {}
    for sample, vals in raw.items():
        intensities[sample] = [(conc, med - bg, artifact) for _, conc, med, artifact in vals]

    ctrl_vals = [s for sample, vals in intensities.items() if sample.startswith("ctrl")
                 for _, s, _ in vals]
    all_vals = [s for vals in intensities.values() for _, s, _ in vals]
    z_prime = 0.5
    if len(ctrl_vals) >= 2:
        sigma_all = float(np.std(all_vals)) or 1.0
        spread = abs(float(np.mean(all_vals)) - float(np.mean(ctrl_vals)))
        z_prime = max(-1.0, min(1.0, 1 - 3 * (float(np.std(ctrl_vals)) + 1.0)
                                / (spread + sigma_all)))

    compounds: dict[str, dict] = {}
    for sample, vals in intensities.items():
        if sample.startswith("ctrl"):
            continue
        pts = sorted((c, s / 0.9) for c, s, _ in vals)  # undo capture gain -> % response
        artifacts_used = sorted({a for _, _, a in vals if a})
        top = max((s for _, s in pts), default=0.0)
        ic50 = None
        if top > 10.0:
            target = 50.0  # half of the assay's known maximal response (100%)
            for (c0, s0), (c1, s1) in zip(pts, pts[1:]):
                if s0 <= target <= s1:
                    frac = 0.0 if s1 == s0 else (target - s0) / (s1 - s0)
                    ic50 = round(c0 + frac * (c1 - c0), 2)
                    break
            if ic50 is None and pts[-1][1] >= target:
                ic50 = round(pts[-1][0], 2)
        compounds[sample] = {"ic50_um": ic50, "max_signal": round(top, 1),
                             "curve": pts, "artifacts": artifacts_used}
    return {"z_prime": round(z_prime, 3), "compounds": compounds}


class ImagingSimulatorLab:
    """LabAdapter: raw plate images in, analyzed AssayResults out."""

    name = "imaging-simulator"

    def __init__(self, seed: int = 7, image_dir: str | Path = ".data/images",
                 artifact_rate: float = 0.04):
        self.device = ImagingPlateReader(seed=seed, artifact_rate=artifact_rate)
        self.image_dir = Path(image_dir)
        self.image_dir.mkdir(parents=True, exist_ok=True)
        self._runs: dict[str, ProtocolSubmission] = {}

    def list_capabilities(self) -> dict[str, Any]:
        return {"assays": ["binding", "enzymatic", "cytotoxicity", "counterscreen"],
                "readout": "fluorescence-imaging", "plate": "96-well",
                "tile_px": self.device.tile, "bsl_max": 2,
                "throughput": {"plates_per_day": 12}}

    def submit_protocol(self, protocol: ProtocolSubmission) -> str:
        run_id = f"img-{protocol.protocol_id[:8]}"
        self._runs[run_id] = protocol
        return run_id

    def get_status(self, run_id: str) -> str:
        return "done" if run_id in self._runs else "failed"

    def fetch_results(self, run_id: str) -> AssayResult:
        protocol = self._runs[run_id]
        well_spec: list[tuple[str, str, float]] = []
        for i, sample in enumerate(protocol.samples):
            conc = parse_concentration_um(sample.concentration)
            well_id = f"{chr(ord('A') + (i // PLATE_COLS))}{(i % PLATE_COLS) + 1}"
            is_control = sample.kind.value == "buffer" or sample.sample_id.startswith("ctrl")
            if is_control and protocol.assay_type.value != "plate_reader":
                conc = 1e-3  # negative-control wells: effectively no compound
            well_spec.append((well_id, "ctrl" if is_control else sample.sample_id, conc))
        plate = self.device.capture(run_id, well_spec)
        for well_id, v in plate.items():  # persist raw evidence (agents can open these)
            np.save(self.image_dir / f"{run_id}_{well_id}.npy", v["image"])
        analysis = analyze_plate(plate)
        measurements = []
        for sample_id, r in analysis["compounds"].items():
            if r["ic50_um"] is not None:
                measurements.append(Measurement(
                    sample_id=sample_id,
                    assay_type=protocol.assay_type.value,
                    value=r["ic50_um"], unit="uM",
                    derived_metrics={"ic50_um": r["ic50_um"],
                                     "max_signal": r["max_signal"],
                                     "z_prime": analysis["z_prime"]},
                    flags=[MeasurementFlag.suspect] if r["artifacts"] else [],
                ))
        sample_image = next(iter(plate))
        return AssayResult(
            envelope=Envelope(experiment_branch_id="imaging-simulator"),
            run_id=run_id, protocol_id=protocol.protocol_id,
            instrument=InstrumentInfo(
                adapter=self.name, instrument_id="img-reader-01",
                raw_output_uri=str(self.image_dir / f"{run_id}_{sample_image}.npy")),
            status=RunStatus.completed,
            measurements=measurements,
            qc={"controls_passed": analysis["z_prime"] >= 0.3,
                "z_prime": analysis["z_prime"]},
        )

    def cancel(self, run_id: str) -> None:
        self._runs.pop(run_id, None)


import random  # noqa: E402  (kept last to keep the device imports obvious)
