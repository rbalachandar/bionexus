---
name: bionexus
description: "Run agentic drug-discovery campaigns with BioNexus: state a problem with constraints, propose and filter hypotheses, design dose-response experiments, submit them through a safety-gated lab gateway (simulated devices, Opentrons, auto-export plate readers), notice device outputs, deliver pre-registered verdicts, and read the hash-chained provenance. Use for experiment orchestration, assay analysis, lab safety gating, and audit trails."
license: Apache-2.0
compatibility: "Python 3.10+. Requires pip install bionexuslab (core deps: pydantic). Optional extras: lab-imaging (numpy), bio-rdkit (rdkit). Hardware adapters need network access to the robot (port 31950)."
allowed-tools: Read Write Edit Bash
metadata:
  version: "0.1.0"
  skill-author: "BioNexus contributors"
---

# BioNexus — agentic drug discovery campaigns

## Overview

BioNexus executes the scientific method as a loop: **problem → hypothesis
portfolio → filter → design → safety-gated experiment → device output →
analysis → verdict → confirmation**. It pairs well with the
`opentrons-integration` skill: that skill teaches you how to *author* an
Opentrons protocol; BioNexus decides *whether it may run* (SafetyEngine) and
records *what happened* (provenance).

## Focused skills

This is the overview skill. Focused companions (install what you need):
`bionexus-labread` (analyze instrument exports) · `bionexus-labwatch` (notice
device outputs autonomously) · `bionexus-campaign` (whole flow, autonomy
levels) · `bionexus-opentrons` (robot execution via safety gateway).

## Setup

```sh
pip install bionexuslab          # core (pydantic only)
bn sim                           # reference round on the virtual lab — no hardware
```

## HARD RULES — read before any lab action

1. **Never call a lab adapter directly.** All lab access goes through the
   safety gateway (`LabGateway.submit` / `bn` workflows). If a submission is
   rejected with a reason, revise the protocol and resubmit through the same
   gate — there is no bypass, and attempting one is a safety violation.
2. **Pre-register before testing.** Every experiment needs a hypothesis with
   explicit success criteria (`SuccessCriteria`: metric, direction, threshold)
   and a declared `ExperimentDesign` (concentrations, replicates, controls)
   recorded *before* results exist.
3. **A QC-failed run is `inconclusive`, not a failure of the hypothesis.**
   Never mark a hypothesis invalidated on a run whose controls failed.
4. **Provenance is append-only.** Never rewrite history; it is hash-chained and
   `bn prove` detects tampering.
5. **Unknown concentrations**: if a compound yields no IC50, it is
   right-censored — re-test at higher concentrations or deprioritize; do not
   invent a value.

## Core workflow

### 1. State the problem and propose a portfolio

```python
from bionexus.core.hypothesis import (Constraint, HypothesisTracker,
                                      ProblemStatement)
from bionexus.adapters.store.sqlite import SqliteProvenanceStore
from bionexus.core.interfaces import system_actor

tracker = HypothesisTracker(SqliteProvenanceStore(), system_actor("agent"))
problem = tracker.define_problem(ProblemStatement(
    objective="Find a confirmed sub-20uM KRAS_G12C binder",
    constraints=[Constraint(name="potency", description="IC50 <= 20 uM",
                            kind="hard", limit=20.0, unit="uM")]))
portfolio = tracker.propose_portfolio(problem, [
    {"statement": "C-101 binds with IC50 <= 20 uM", "candidate": "C-101",
     "assay_type": "binding", "predicted": "IC50 <= 20", "predicted_value": 20.0,
     "rationale": "covalent warhead precedent"},
    # ... more hypotheses; rejected ones stay on record
])
selected = tracker.select_portfolio(problem, portfolio,
                                    score_fn=my_scoring, k=2)
```

### 2. Design + run experiments (safety-gated)

```python
from bionexus.core.safety import LabGateway, SafetyEngine
from bionexus.adapters.lab.simulator import SimulatorLab

gateway = LabGateway(SimulatorLab(seed=42), SafetyEngine(), store, actor)
run_id, rejection = gateway.submit(protocol)   # rejection carries a reason
result = gateway.results(protocol.envelope, run_id)
```

For real devices: `OpentronsLab` (robot HTTP API) and `PlateReaderShare`
(readers that auto-export to a network share) implement the same interface.

### 3. Verdicts against pre-registered criteria

```python
tracker.verdict(hyp, result)   # validated | invalidated | inconclusive (QC failed)
```

### 4. Let the agent notice device output autonomously

```python
from bionexus.watch import watch
watch(inbox="/path/to/instrument_outbox", tracker=tracker, gateway=gateway)
# or: bn watch /path/to/instrument_outbox
```

### 5. One-call autonomous campaign

```sh
bn auto campaign.json     # autonomy: "observe" | "gate" | "act"
```

## Reading instrument results

`bn read results.csv` auto-detects vendor exports (Biotek/Gen5-style headers,
plate grids, long formats), finds controls, fits IC50s, computes Z'. Use
`read_plate()` in Python.

## Audit

```sh
bn prove <branch> --html report.html   # hash-chained, tamper-evident history
```

## Troubleshooting

- Safety rejection reasons are machine-readable — fix the stated issue and
  resubmit; never retry unchanged.
- `inconclusive` verdicts mean evidence was insufficient — redesign the
  experiment (more concentrations/replicates), don't relabel it.
- Full docs: https://github.com/rbalachandar/bionexus
