# Block E — Simulation & Data Services (L2)

Computational assays that substitute for or complement wet-lab work.

## Components

### MD / Docking Farm
- GPU batch execution: molecular dynamics, docking, free-energy estimates
- Job queue with priority by pipeline stage; large artifacts (trajectories) go to
  object storage with P2P distribution

### In-silico Assay Simulation
- Predicted assay outcomes with calibrated uncertainty — backs the Virtual Lab
  Simulator (Block D) and pre-filters candidates before wet-lab
- Active-learning aware: reports which predictions are worth validating physically

### Clinical Trial Simulation
- Population models, enrollment/dropout, adverse-event modeling, endpoint power
  analysis
- Feeds Trial Design Agent

### Data Platform
- ELN/LIMS integration, assay QC pipelines
- Feature stores feeding the active-learning loop
- Historical trial data marts

## Interfaces
- Consumes `ToolInvocation` (simulation jobs), emits results + artifacts
- Provides outcome priors to the Virtual Lab Simulator
