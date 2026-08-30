---
name: bionexus-campaign
description: "Run the whole drug-discovery campaign flow with BioNexus: state the problem with constraints, propose a portfolio of hypotheses, filter to top-k, design and submit safety-gated experiments, collect verdicts and confirmations. Use for start-to-finish campaigns, with operator-chosen autonomy (observe/gate/act)."
license: Apache-2.0
compatibility: "Python 3.10+. pip install bionexuslab (core deps: pydantic). Optional extras: lab-imaging (numpy), bio-rdkit (rdkit)."
allowed-tools: Read Write Edit Bash
metadata:
  version: "0.1.0"
  skill-author: "BioNexus contributors"
---

## Overview

`bn auto campaign.json` (or `bionexus.autoloop.run_campaign()` in Python) runs:
problem + constraints -> portfolio of N hypotheses -> filter to top-k ->
design -> safety-gated submission -> device output -> agent analysis ->
pre-registered verdicts -> auto-submitted confirmation assays.

## Autonomy levels (operator-set, per campaign)

- **observe** — reads, fits, recommends; submits nothing
- **gate** — every lab submission requires operator approval (approver callback)
- **act** — autonomous inside the SafetyEngine, incl. confirmation assays

## Config format

```json
{
  "problem": {"objective": "...", "constraints": [
      {"name": "potency", "description": "IC50 <= 20 uM", "kind": "hard",
       "limit": 20.0, "unit": "uM"}],
   "success_metric": "orthogonal confirmation"},
  "hypotheses": [
    {"statement": "C-101 binds with IC50 <= 20 uM", "candidate": "C-101",
     "assay_type": "binding", "predicted": "IC50 <= 20",
     "predicted_value": 20.0, "rationale": "precedent"}],
  "scores": {"C-101": 0.9, "C-102": 0.8},
  "k": 2,
  "autonomy": "gate"
}
```

## Hard rules

- Pre-register success criteria before results exist.
- Never bypass the SafetyEngine; resubmissions go through the same gate.
- Rejected hypotheses stay on record — selection decisions are auditable.
- `bn prove <problem-id> --html out.html` renders the tamper-evident audit.
