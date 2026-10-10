# BioNexus — Build Plan

Open-source framework for agentic drug discovery: minimal core, adapter/plugins for
models, bio libraries, labs, sandboxes, and storage. Like early LangChain: small,
typed, domain-specific — not bloated.

## Design principles (every task must satisfy these)

| # | Principle | Rule of thumb |
|---|---|---|
| P1 | Minimal core | `core/` deps = `pydantic` only. CI must install+test core in <5s, no network |
| P2 | Interfaces not implementations | `core/` contains zero concrete integrations; everything real lives in `adapters/` |
| P3 | Model-agnostic | Any OpenAI-compatible endpoint works by default; others are plugins |
| P4 | Wet lab is an adapter | Simulator and hardware implement one `LabAdapter` protocol; CI runs simulator only |
| P5 | Provenance mandatory, storage pluggable | Every interface result is provenance-wrapped; store is an adapter |
| P6 | Safety is core, non-bypassable | Policy engine sits in core; physical actions cannot be dispatched without passing it |
| P7 | Fork/snapshot first-class | `Sandbox` protocol has fork/snapshot/resume; engine use is PARTIAL — the
opt-in S-T3 session wraps lab ops + routed tools; blanket enforcement open, adapters may degrade gracefully |
| P8 | Simulator-first CI | Full example workflows run against the virtual lab on every commit; hardware tested vs recordings only |

## Architecture (framework view)

```
User code / reference agents
        │ uses
┌───────▼──────────────────────────────────────────────┐
│ core/   contracts (pydantic) · interfaces (Protocol) │
│         workflow engine · tournament · safety        │
│         registry (plugin discovery)                  │
└───────┬──────────────┬───────────────┬───────────────┘
        │              │               │
   adapters/       adapters/       adapters/
   models*         lab*            store*      (+ sandbox, bio)
   openai_compat   simulator       sqlite
   anthropic       opentrons       postgres
   gemini          cloud-lab       s3-worm
   vllm/ollama
```

`*` = phase-1 adapters. Everything else is roadmap.

## Phases & tasks

### Phase 1 — Core skeleton (this is the framework's IP)
- [x] T1.1 Write this plan; map each task to principles
- [x] T1.2 Scaffold package: `pyproject.toml`, layout, dev venv *(P1)*
- [x] T1.3 `core/contracts/` — the 5 schemas as pydantic v2 models, shared Envelope,
      previously drafted in OpenAPI, now normative in code *(P1, P5)*
- [x] T1.4 `core/interfaces.py` — Protocols: `ModelProvider`, `BioTool`,
      `LabAdapter`, `Sandbox`, `ProvenanceStore`, plus `ToolInvocation` result
      types *(P2)*
- [x] T1.5 `core/safety.py` — `SafetyEngine` with declarative rules
      (BSL caps, forbidden reagent combos, inventory limits); `LabAdapter`
      dispatch goes *through* it, not around it *(P6)*
- [x] T1.6 `core/registry.py` — entry-point plugin discovery + typed tool registry
      with capability matching *(P2)*
- [x] T1.7 `core/workflow.py` — stage graph (sequential/parallel/loop/gate) +
      hypothesis tournament engine (generate→reflect→rank→evolve) using only
      core interfaces *(P2, P7)*
- [x] T1.8 Unit tests for all of the above; no network, no heavy deps *(P1, P8)*

### Phase 2 — Reference adapters (prove the interfaces)
- [x] T2.1 `adapters/store/sqlite.py` — hash-chained provenance store *(P5)*
- [x] T2.2 `adapters/lab/simulator.py` — virtual lab: seeded, deterministic-ish
      assay outcomes w/ noise; implements `LabAdapter`; capability catalog *(P4, P8)*
- [x] T2.3 `adapters/models/openai_compat.py` — works with OpenAI/ollama/vLLM/
      any compatible base_url; model+version pinned *(P3)*
- [x] T2.4 `adapters/sandbox/local.py` — in-process sandbox w/ copy-on-fork state
      (degraded snapshot: deep-copy); documents AgentENV adapter as the real one *(P7)*
- [x] T2.5 `adapters/bio/rdkit_ops.py` (optional extra) — descriptors / filters
      as `BioTool`s *(P2)*
- [x] T2.6 Example: `examples/iteration_loop.py` (since retired; superseded by
  `examples/demo_full_flow.py`) — full design round with stub
      model: generate → evaluate → gate → protocol → simulator → analysis *(P8)*

### Phase 3 — Trust & polish
- [x] T3.1 Docs: quickstart, adapter authoring guide, safety guide
- [x] T3.2 `bn` CLI: `bn run workflow.yml` · `bn sim` · `bn prove <id>`
- [x] T3.3 Recording/playback harness for hardware adapters (test vs recordings) *(P8)*
- [x] T3.4 CI: core-only fast job + full example job; adapter test matrix
- [x] T3.5 Packaging: extras (`[models-openai]`, `[bio-rdkit]`, `[sandbox-agentenv]`, `[store-postgres]`),
      README rewrite for framework positioning

### Phase 4 — Ecosystem (post-1.0)
- [x] T4.1 Anthropic adapter + MCP tool exposure; Gemini via the OpenAI-compatible
  endpoint (no dedicated adapter — claim corrected by the Oct-10 audit)
- [x] T4.2 AgentENV sandbox adapter (fork/snapshot for real)
- [ ] T4.3 Opentrons adapter; cloud-lab HTTP adapter
- [x] T4.4 Fine-tune flywheel hooks (export confirmed results as training pairs)
- [ ] T4.5 Template gallery: target-ID / small-molecule / antibody workflows

## Anti-bloat guardrails (enforced in review + CI)

1. `core/` import scan: forbidden imports (`requests`, `numpy`, `pandas`, `torch`,
   `langchain`, SDK packages) fail CI — *(P1)*
2. Every adapter module must import core only through `bionexus.core` — no
   adapter-to-adapter imports
3. New dependency = new issue justifying it against P1/P2
4. Deprecation policy: remove before adding; interfaces evolve additively

## Non-goals (explicitly)

- Not a model runtime, not a lab OS, not an ELN/LIMS
- No hosted service in the framework repo
- No workflow DSL beyond YAML stage lists (keep it boring)
