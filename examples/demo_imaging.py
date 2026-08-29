"""Demo: simulated lab devices with image-based readouts.

A plate run produces raw well images (.npy), an analysis pipeline fits IC50s,
and QC (Z' factor) is computed from controls — the same evidence chain as a
real imaging plate reader.

    .venv/bin/python examples/demo_imaging.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, "src")

from bionexus.adapters.lab.imaging import ImagingSimulatorLab, true_ic50_um
from bionexus.core.contracts import (
    Envelope, ProtocolOp, ProtocolStep, ProtocolSubmission,
    ReagentSpec, SampleKind, SampleSpec,
)


def main() -> None:
    lab = ImagingSimulatorLab(seed=42, image_dir=".data/images")
    print(f"capabilities: {lab.list_capabilities()['readout']}, "
          f"{lab.list_capabilities()['plate']}")

    protocol = ProtocolSubmission(
        envelope=Envelope(experiment_branch_id="imaging-demo"),
        title="dose-response panel",
        assay_type="binding",
        steps=[ProtocolStep(seq=1, op=ProtocolOp.dispense, params={"volume_ul": 50})],
        samples=[SampleSpec(sample_id=c, kind=SampleKind.compound, concentration=k)
                 for c in ["C1", "C2", "C3"] for k in ["0.5uM", "2uM", "10uM", "40uM"]]
        + [SampleSpec(sample_id=f"ctrl-neg{i}", kind=SampleKind.buffer, concentration="10uM")
           for i in (1, 2)],
        reagents=[ReagentSpec(name="buffer-A", amount="5 mL", bsl_level=1)],
    )
    run_id = lab.submit_protocol(protocol)
    result = lab.fetch_results(run_id)

    print(f"\nrun {run_id}: Z'={result.qc.z_prime} "
          f"(controls {'PASS' if result.qc.controls_passed else 'FAIL'})")
    print(f"{'compound':<10} {'measured IC50':>14} {'ground truth':>13}")
    for m in sorted(result.measurements, key=lambda m: m.sample_id):
        truth = true_ic50_um(42, m.sample_id)
        flagged = " (artifact flagged)" if m.flags else ""
        print(f"{m.sample_id:<10} {m.value:>10} uM {truth:>10} uM{flagged}")

    images = sorted(Path(".data/images").glob(f"{run_id}_*.npy"))
    print(f"\nraw evidence: {len(images)} well images in .data/images/"
          f" (e.g. {images[0].name if images else '-'})")
    print("each file is a 24x24 fluorescence micrograph — open one and look.")


if __name__ == "__main__":
    main()
