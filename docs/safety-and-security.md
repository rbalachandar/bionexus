# Safety & Security — the full mechanism reference

Consolidated from SAFETY.md + security.md + the README trust table (Oct 11
consolidation). Two distinct concerns, deliberately kept separate:

- **Safety** — protecting the WORLD from the agent's actions:
  toxicophores, BSL limits, DURC screening, the halt switch.
- **Security** — protecting the SYSTEM from tampering and untrusted
  inputs: hash chains, trust boundaries, injection defense.

## The full mechanism table

| Mechanism | What it guarantees |
|---|---|
| Uncertainty vetoes certainty | a 95% CI straddling the gate abstains on any metric — IC50, %-inhibition, ipTM alike; near-gate point estimates do not earn a decisive verdict (CS05: 14 abstentions; CS08: 6) |
| Pre-registered claims | every hypothesis records its predicted and **refuted-if** clauses before data arrives; verdicts are read against the pre-registered condition — CS08's control clauses ("if this validates, the score's ranking value is refuted") evaluated true, in the chain |
| Proxy-evidence ladder | every metric declares what it stands for; verdicts carry their evidence distance (`bn why`), and chains that do not reach the target claim (`ipTM → binding affinity`) are labeled unresolved |
| Provenance physics | the hash chain is engine-enforced and recomputed on read (`verify_chain`); verdict reading is payload-driven, recency-wins — the read path is verified like the write path |
| Molecular safety gate | 18+ curated toxicophore SMARTS (versioned data file — refusals cite the rule version); hard classes always refuse; electrophilic warheads pass **only** with declared covalent intent in the hypothesis |
| Execution governance | enforced in gateway code, outside the agent's tool surface: an operator halt switch it cannot lift (`bn halt`), a three-column authorization matrix (autonomous / human-approved / never — DURC and BSL-3+ default to never), and SOP sign-off before anything recurring runs unattended; every decision is a provenance record |
| Physical-fault honesty | saturated plates, dark reads, negative values, and device errors are classified as **physical** failures before any retry — flagged for operator inspection, not re-queried blindly and not turned into verdicts |
| DURC screening | campaigns naming select agents / regulated toxins are refused before any work, and the refusal is recorded |
| Citation enforcement | PMIDs/DOIs resolved against PubMed; a fabricated reference ranks below no citation at all; offline checks never falsely accuse |
| Makeability is a gate | before Make allocates a batch, a named-reaction rule corpus plans routes (how many, how long, at what cost, modeled yield); a compound whose routes all fail the yield/lead-time floors is refused with a `no_viable_route` provenance record — batch numbers are drawn from the chosen route and every plan is stamped simulated |
| Series discipline | proposed→tested→judged grouped by family or Murcko chemotype (grouping backend stamped); matched-pair SAR deltas carry propagated CIs and abstain when straddling the retention band; a series claim's verdict is derived only from its members and cannot aggregate past what its data supports |
| Institutional memory | `bn ingest` folds pre-BioNexus ELN outcomes into ALREADY RULED OUT and family priors — stamped `imported`, sha256-sealed against the export sidecar; a CSV edited after export imports as unsealed, with a warning |
| `bn reproduce` | the execution environment (lab, version, seed, concentrations) is in the provenance root — replay a branch, diff verdicts |
| Fault tolerance | junk/adversarial instrument files degrade to "unreadable, no verdicts changed" — no crashes, no verdicts from noise |
| Input trust boundary | instrument labels are sanitized data; injection-shaped sample names cannot reach the gate as instructions (tested) |
| Verdict stability | same ground truth, N noise draws — verdicts that flip are flagged borderline, not averaged away |
| Attribution | per-prediction "why": exact n-gram contributions, importance-weighted RF bits (with hashed-bit caveats stated), triggered ADMET rules, AVI feature attributions |
| Retrieval traces | every generation records prompt hash, model, injected flywheel negatives — "what shaped this hypothesis" is answerable from the chain |
| Anchoring | Merkle root over the whole store; publish it anywhere you don't control for external tamper-evidence |
| Evidence is the data | the Evidence section re-renders each branch's **recorded run files** — plate exports or model-prediction artifacts, the same numbers the verdicts were read from; a missing file renders as an explicit gap, not a stock figure |
| Retirement, not deletion | archived experiments leave the working set but their hash-chained records stay intact and auditable — consistent with the append-only provenance store |
| Regime-gated assertions | deposited percent tables are fingerprinted for their normalization frame; absolute IC50 verdicts issue only in externally validated frames (CS05), while self-normalized dialects (where CS06 showed numbers do not port) are admitted at the *shape* level only — affine-invariant concentration-dependence classes, labeled responders-never-verdicts (97.4% concordance with NCATS' own actives on their deposit). Trust is a declared envelope |
| Applicability domain | every learned predictor carries a nearest-neighbour Tanimoto domain (Morgan bits, char-gram fallback, declared conservative floor): values from beyond a model's training chemistry are stamped `extrapolation`, earn no claim-grade verdict in either direction, and are surfaced on the card — the model-side counterpart of the regime gate, graded by its own eval task |

## Safety — rules that protect the world

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

## Security — trust boundaries and threat model

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

Agents reach the lab only through `LabGateway`. Sandbox execution is
opt-in and currently covers lab ops + routed tool calls per experiment
(ROADMAP S-T3); blanket agent-in-sandbox enforcement is NOT yet true —
agent/reviewer/MCP lanes run in-process (S-T3 1e).
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
| Prompt-injected exfiltration | Malicious dataset content steers agent to send data out | Sandboxes have no network unless granted; lab adapters are local/operator-configured. The **OpenSandbox adapter** supports per-sandbox egress controls and a credential vault (secrets never enter the workload) — the recommended isolation tier for untrusted agent code | ✅ with OpenSandbox/AgentENV; ⚠️ Local/Docker are operator-trust |
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
