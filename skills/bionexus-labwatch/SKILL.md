---
name: bionexus-labwatch
description: "Watch an instrument outbox so the agent notices device outputs automatically: new export files trigger analysis, hypothesis verdicts against pre-registered criteria, and next-step recommendations. Use when instrument results should be picked up without a human shuttling files."
license: Apache-2.0
compatibility: "Python 3.10+. pip install bionexuslab (core deps: pydantic). Optional extras: lab-imaging (numpy), bio-rdkit (rdkit)."
allowed-tools: Read Write Edit Bash
metadata:
  version: "0.1.0"
  skill-author: "BioNexus contributors"
---

## Overview

`bionexus.watch` inverts the flow: the device finishing a run is the event, and
the agent reacts — reads the export, updates open hypotheses, queues decisions.
The event interface maps to real push sources (webhooks, queue callbacks);
directory watching is the lowest-common-denominator.

## Usage

```sh
bn watch /path/to/instrument_outbox
```

```python
from bionexus.watch import watch
watch(inbox="outbox/", tracker=tracker, gateway=gateway,
      notify=lambda m: print("[agent]", m))
```

## Behavior

1. New export file appears -> `plate_ready` event.
2. Agent reads it (`read_plate`), reports compounds + Z'.
3. Any open hypothesis whose candidate was measured gets a verdict against its
   pre-registered criteria (validated / invalidated / **inconclusive** if QC failed).
4. Recommendation is emitted in bench language ("best binder so far... confirm
   with orthogonal assay").
5. With a `gateway` provided, the confirmation assay is auto-submitted through
   the SafetyEngine — closing the loop autonomously.
