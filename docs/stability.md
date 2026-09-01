# API Stability Policy

How BioNexus versions, what you can depend on, and how things change.
Applies from v0.1.0.

## Versioning

Semantic versioning: `MAJOR.MINOR.PATCH`.

- **MAJOR** — breaking change to any *stable* surface (below)
- **MINOR** — new adapters, new optional features, additive interface methods
- **PATCH** — bug fixes, docs, performance

While `0.x`: MINOR bumps may break (treated as deprecation+removal in one
step, always announced in the changelog).

## Stability tiers

| Tier | Surfaces | Guarantees |
|---|---|---|
| **Stable** | The five core interfaces (`ModelProvider`, `BioTool`, `LabAdapter`, `Sandbox`, `ProvenanceStore`) and the contract models (`bionexus.core.contracts`) | Additive evolution only. No renames, removals, or semantic changes within a MAJOR. Old serialized contracts keep loading. |
| **Stable** | `SafetyEngine` rule API and `LabGateway` behavior | Safety semantics never silently change: any change to enforcement behavior is a MAJOR bump |
| **Experimental** | `bionexus.workflow` (StageGraph, tournament), `bionexus.benchmark`, `bionexus.report` | May change in MINOR releases; flagged in docstrings |
| **Unstable** | `bionexus.cli`, `bionexus.mcp_server` tool list | New tools/flags appear freely; existing tools keep working where possible |
| **Adapter-internal** | everything under `bionexus.adapters.*` except their public class constructors | Adapters may change at any MINOR; pin if you subclass them |

Rules of thumb:

1. **Depend on core, construct adapters.** If you only use
   `bionexus.core.interfaces` + the adapter constructors documented in
   `docs/ADAPTERS.md`, you are on the stable surface.
2. **Subclassing adapters is unsupported.** Compose or wrap instead.
3. Anything not exported from `bionexus` / `bionexus.core` is private.

## Deprecation policy

1. Deprecations are announced in the changelog and via `DeprecationWarning`
   for at least one MINOR release (six months for anything in the stable tier
   post-1.0).
2. Removals happen only in MAJOR releases.
3. Contract schemas (`contracts/v1/*`) evolve additively: new optional fields
   only. Consumers must ignore unknown fields. Breaking schema needs a `v2/`
   directory, never a mutation of `v1/`.

## Compatibility commitments

- Python: latest two minor versions supported (currently 3.12+)
- Core dependencies kept minimal (`pydantic`); its major version bumps are
  coordinated with ours, not surprise MAJOR jumps
- Contract files are usable without installing the package (they are the
  integration point between organizations)

## How changes are decided

Interface changes require an ADR (architecture decision record) in
`docs/adr/` describing motivation, alternatives, and migration path — see the
process in `CONTRIBUTING.md`.
