---
name: bionexus-opentrons
description: "Execute liquid-handling protocols on Opentrons OT-2/Flex robots through BioNexus: compile an abstract protocol to an Opentrons Python protocol, submit it through the safety gateway, and collect execution evidence. Pair with the opentrons-integration skill for protocol authoring; BioNexus decides whether it may run."
license: Apache-2.0
compatibility: "Python 3.10+. pip install bionexuslab (core deps: pydantic). Optional extras: lab-imaging (numpy), bio-rdkit (rdkit)."
allowed-tools: Read Write Edit Bash
metadata:
  version: "0.1.0"
  skill-author: "BioNexus contributors"
---

## Overview

`bionexus.adapters.lab.opentrons.OpentronsLab` is the Make-step adapter for
Opentrons robots (HTTP API, port 31950). Authoring guidance lives in the
`opentrons-integration` skill; BioNexus adds the trust layer: SafetyEngine
gate, execution evidence, hash-chained provenance.

## Usage

```python
from bionexus.adapters.lab.opentrons import OpentronsLab, compile_protocol
from bionexus.core.safety import LabGateway, SafetyEngine

lab = OpentronsLab(base_url="http://169.254.8.32:31950")
gateway = LabGateway(lab, SafetyEngine(), store, actor)
run_id, rejection = gateway.submit(protocol)   # rejection = policy reason
status = gateway.lab.get_status(run_id)
result = gateway.results(protocol.envelope, run_id)  # execution evidence
```

## Division of labor

- `opentrons-integration` skill: how to write a correct API-v2 protocol.
- BioNexus: whether it runs (SafetyEngine first), what actually happened
  (executed-command evidence), and the audit trail.

## Honesty rules

- Execution results are NOT assay values. The plate still needs a reader
  (`PlateReaderShare` adapter or `bn read` on the reader's export).
- Failed robots runs are recorded as failed — never re-label as inconclusive
  science; the hypothesis stays open.
