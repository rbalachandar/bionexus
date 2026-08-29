# Security & Threat Model

What a malicious, buggy, or hallucinating agent can and cannot do in BioNexus.
Read with `docs/SAFETY.md` (SafetyEngine mechanics) and `docs/PLAN.md` (P6).

## Trust boundaries

```
┌─────────────────────────────────────────────────────────┐
│ Operator (human)                                        │
│   owns: safety rules, adapter config, credentials       │
├─────────────────────────────────────────────────────────┤
│ Core (trusted)                                          │
│   StageGraph · LabGateway · SafetyEngine · Provenance   │
├──────────────────────────────────┬──────────────────────┤
│ UNTRUSTED: agents (LLM-driven)   │ UNTRUSTED: models    │
│  can: propose, test, analyze,    │  can: return text/   │
│  revise, request lab actions     │  numbers via adapters│
└──────────────────────────────────┴──────────────────────┘
```

Agents run *inside* sandboxes and reach the lab only through `LabGateway`.
Adapters are operator-installed code — they are part of the trusted core, not
the agent.

## Capability matrix

| Action | Agent can | Enforced by |
|---|---|---|
| Generate/propose candidates | ✅ freely | — |
| Record hypotheses | ✅ (append-only, signed into chain) | ProvenanceStore |
| Submit a lab protocol | ✅, but **only via gateway** | `LabGateway.submit` |
| Mark a protocol safe | ❌ no code path exists | SafetyEngine outside agent trust boundary |
| Modify safety rules | ❌ rules are operator-registered; no agent API | core API surface |
| Skip/relax a gate | ❌ gate decisions are human/scripted events | StageGraph gates |
| Read lab capabilities | ✅ (declared catalog only) | IAL `list_capabilities` |
| Touch instruments directly | ❌ adapters are never handed to agents | design (P2/P6) |
| Erase or rewrite provenance | ❌ append-only, hash-chained | ProvenanceStore |
| Use more lab time/reagents than requested | ⚠️ within protocol limits | MaxStepsRule + inventory limits (D) |

## Threat scenarios

| Threat | Scenario | Mitigation | Status |
|---|---|---|---|
| Hallucinated protocol | Agent invents an unsafe reagent combination | SafetyEngine forbidden-combo rules reject with reason; agent must revise through the same gate | ✅ enforced |
| Scope creep | Agent orders 100 extra assay steps | MaxStepsRule; throughput caps in Lab State Manager | ✅ enforced |
| Provenance tampering | Agent rewrites history to hide a failure | Hash chain (sha256, prev-link); `bn prove` detects breaks; store is append-only | ✅ enforced |
| Gate bypass | Agent marks its own candidate approved | Gates are core-side events requiring an approver actor outside the agent | ✅ enforced |
| Prompt-injected exfiltration | Malicious dataset content steers agent to send data out | Sandboxes have no network unless granted; lab adapters are local/operator-configured | ⚠️ sandbox policy is adapter-dependent |
| Data poisoning | Adversarial "results" enter the flywheel | Flywheel examples only from gateway-approved runs; provenance links every label to a run id | ✅ structural |
| Ground-truth leakage | Agent reads simulator truth to fake performance | `true_ic50_um` excluded from agent-facing tools; evaluation-only API | ✅ convention — enforced by review |
| Malicious adapter | Third-party adapter exfiltrates data | Out of scope of core; adapters are operator-installed trusted code — vet like any dependency | ⚠️ operator responsibility |

## Non-goals

- Not a sandbox escape defense: run untrusted agent code inside a real
  sandbox (AgentENV/Docker), not on your workstation
- Not multi-tenant isolation: one deployment = one operator
- Not a compliance framework: the provenance chain *supports* GxP audits, but
  doesn't certify anything

## Reporting

Security issues: open a private security advisory on GitHub (do not open a
public issue with exploit details).
