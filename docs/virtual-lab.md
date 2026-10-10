# The Virtual Lab

BioNexus's simulated lab is a stand-in for real instruments — same `LabAdapter`
contract, layered realism. Agents never know (or need to know) which is which.

## Layers of simulation

| Adapter | What it simulates | Readout |
|---|---|---|
| `SimulatorLab` | Assays as abstract seeded measurements: Hill dose–response ground truth per compound, replicate noise, counterscreen interference (PAINS-like artifacts), controls | Normalized `Measurement`s with `ic50_um` |
| `ImagingSimulatorLab` (extra `[lab-imaging]`) | An **imaging plate reader**: 96-well plate, each well a synthetic fluorescence micrograph (24×24 px) encoding the same seeded ground truth, plus shot noise, vignetting, cell-texture blobs, and per-well artifacts (edge effect, pipetting spike, bubble) | **Raw well images on disk** → analysis pipeline → IC50s + Z' factor QC |

## Why images matter

With `ImagingSimulatorLab`, the result chain is physical:

```
protocol → device captures well images (.npy on disk)
        → analysis pipeline: background (from control wells)
          → median intensity → dose–response fit → IC50
        → QC: Z' factor from controls (≥0.3 required)
        → AssayResult (raw_output_uri points at the actual images)
```

Measured IC50s recover ground truth within noise with a small positive bias —
exactly the behavior of a real assay. Compounds whose curve never crosses 50%
are right-censored (no IC50 reported), as in real screens.

## Failure modes agents must learn to handle

- **Artifacts**: pipetting spikes and bubbles flag wells `suspect`; edge effects
  corrupt whole well regions
- **Right-censoring**: weak compounds produce no IC50 — agents must re-test at
  higher concentrations or deprioritize
- **QC failure**: Z' below threshold marks the whole run `controls_passed=False`
  — the honest response is a re-run, not using the data

## Ground truth access (for evaluation only)

`true_ic50_um(seed, sample_id)` exposes the seeded truth so benchmarks can score
how well agents *measure* — never wire it into agent-facing tools.

## Vision-LLM readout (evaluation harness)

`bionexus/vision.py`: well micrographs are
encoded as PNGs (jointly normalized to preserve relative brightness across the
dose series) and shown to a multimodal model, which estimates fluorescence; its
estimates are fit with the same curve model as the pipeline. Comparing
ground truth / pipeline / vision-LLM IC50s yields a standing benchmark for
multimodal assay analysis. Ground truth stays out of the model's context —
it is used only to score.
