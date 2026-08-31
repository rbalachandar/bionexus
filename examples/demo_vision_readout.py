"""Flagship demo: a vision-LLM reads simulated plate images.

The imaging lab captures well micrographs (raw evidence, no numbers exposed).
The analysis pipeline fits IC50s from pixels. INDEPENDENTLY, a multimodal LLM
is shown the same images and asked to quantify fluorescence — its estimates
are fit with the same curve model. Three-way comparison:

    ground truth (device seed)  vs  pipeline IC50  vs  vision-LLM IC50

    BIONEXUS_LLM_* (or ANTHROPIC_*) env required.
    .venv/bin/python examples/demo_vision_readout.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, "src")

from bionexus.adapters.lab.imaging import (
    ImagingSimulatorLab, analyze_plate, true_ic50_um,
)
from bionexus.core.contracts import (
    Envelope, ProtocolOp, ProtocolStep, ProtocolSubmission,
    ReagentSpec, SampleKind, SampleSpec,
)
from bionexus.vision import VisionWellReader

CONCS = ["0.5uM", "2uM", "10uM", "40uM"]


def fit(points: list[tuple[float, float]], top: float) -> float | None:
    target = top / 2.0
    pts = sorted(points)
    for (c0, v0), (c1, v1) in zip(pts, pts[1:]):
        if min(v0, v1) <= target <= max(v0, v1):
            frac = 0.0 if v1 == v0 else (target - v0) / (v1 - v0)
            return round(c0 + frac * (c1 - c0), 2)
    return None


def main() -> None:
    from bionexus.vision import VisionWellReader
    reader = VisionWellReader()  # raises with a clear message if env missing

    lab = ImagingSimulatorLab(seed=42, image_dir=".data/images-vision")
    compound = "C-101"
    protocol = ProtocolSubmission(
        envelope=Envelope(experiment_branch_id="vision-demo"),
        title=f"vision readout {compound}", assay_type="binding",
        steps=[ProtocolStep(seq=1, op=ProtocolOp.dispense, params={"volume_ul": 50})],
        samples=[SampleSpec(sample_id=compound, kind=SampleKind.compound, concentration=c)
                 for c in CONCS]
        + [SampleSpec(sample_id="ctrl-neg", kind=SampleKind.buffer, concentration="10uM"),
           SampleSpec(sample_id="ctrl-neg2", kind=SampleKind.buffer, concentration="10uM")],
        reagents=[ReagentSpec(name="assay-buffer", amount="5 mL", bsl_level=1)],
    )
    run_id = lab.submit_protocol(protocol)
    result = lab.fetch_results(run_id)

    # pipeline IC50 (from the analysis pipeline)
    pipeline = {m.sample_id: m.value for m in result.measurements}

    # vision-LLM: read each well image independently
    well_images: dict[str, tuple[str, float, object]] = {}
    import numpy as np
    for i, conc in enumerate(CONCS):
        well = f"{chr(ord('A') + (i // 12))}{(i % 12) + 1}"
        img_path = Path(f".data/images-vision/{run_id}_{well}.npy")
        well_images[well] = (compound, float(conc.replace("uM", "")), np.load(img_path))
    # series mode: one composite strip -> relative comparison (better calibrated)
    series_imgs = [well_images[w][2] for w in sorted(well_images)][: len(CONCS)]
    estimates = {compound: reader.estimate_series(series_imgs, CONCS)}

    truth = true_ic50_um(42, compound)
    pts = [(c, v) for c, v in estimates.get(compound, {}).items()]
    vision_ic50 = fit(pts, top=max(v for _, v in pts)) if pts else None

    print(f"run {run_id}  compound {compound}")
    print(f"{'conc':>8} {'vision estimate':>16}")
    for c, v in sorted(estimates.get(compound, {}).items()):
        print(f"{c:>7}uM {v:>16.1f}")
    print(f"\nground truth IC50 : {truth:.2f} uM")
    print(f"pipeline IC50     : {pipeline.get(compound, '-')} uM")
    print(f"vision-LLM IC50   : {vision_ic50} uM  (model: {reader.model})")
    print("\nnote: the vision model saw only pixels — no numbers, no ground truth.")


if __name__ == "__main__":
    main()
