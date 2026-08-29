# Safety

Physical actions are the one thing BioNexus treats as non-negotiable (P6).

## The rule

**Agents cannot touch a `LabAdapter`.** The only path to the lab is:

```
agent → ProtocolSubmission → SafetyEngine.check() ──approved──▶ LabAdapter
                                    │
                                    └─rejected (with reason) → agent revises
```

`LabGateway.submit()` is the choke point. The SafetyEngine lives in core
(P6: safety is not a plugin), its rules are declared by the *operator*, and no
agent API can modify them or mark a protocol approved.

## Default rules

| Rule | What it does |
|---|---|
| `MaxBslRule(max_bsl=2)` | rejects reagents above the configured biosafety level |
| `ForbiddenComboRule(pairs)` | rejects forbidden reagent combinations (glob patterns, e.g. `("acid*", "*hypochlorite*")`) |
| `MaxStepsRule(100)` | rejects runaway agent-generated protocols |

## Operator configuration

```python
from bionexus.core.safety import SafetyEngine, MaxBslRule, ForbiddenComboRule

safety = SafetyEngine(rules=[
    MaxBslRule(max_bsl=1),                                    # strict lab
    ForbiddenComboRule([("acid*", "*hypochlorite*"), ("cyan*", "acid*")]),
])
gateway = LabGateway(lab_adapter, safety, provenance_store, actor)
run_id, rejection = gateway.submit(protocol)   # (None, reason) when rejected
```

Rejections always carry a machine-readable reason so agents can revise —
but revision goes through the same gate again. There is no bypass flag by
design.

## Provenance

Every approved run writes a `lab_run` ProvenanceRecord (P5); every gate decision
writes a `gate_decision` record. Combined with the hash chain, `bn prove
<branch>` gives a tamper-evident history of who submitted what and what was
approved — the audit trail regulators ask for.

## Principles honored

- **P6** Safety is core and non-bypassable
- **P4** The gateway works identically for the simulator and real hardware —
  safety behavior is tested in CI (P8) *before* a robot is ever involved
- **P5** Approval decisions are provenance records, not log lines
