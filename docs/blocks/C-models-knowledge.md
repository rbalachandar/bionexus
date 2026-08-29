# Block C — Model & Knowledge Services (L2)

Stateless/gateway services behind one versioned tool API. Buildable today with
open-source models on a GPU box.

## Components

### Bio Foundation Model Gateway
- Single versioned inference API (`/v1/predict`, `/v1/generate`)
- Model families: protein structure, property prediction, generative chemistry
  (diffusion/LM), ADMET
- Model registry with pinned versions; every response records model+version for
  provenance
- Batching/queueing for GPU efficiency

### Knowledge Base Service
- Literature RAG, patents, pathways, internal experiment history
- Citation-grounded responses (required for target dossiers)

### Molecule/Sequence Registry
- Canonical store of all designed candidates
- Computed properties cache, similarity/fingerprint indexes, dedup

### Evaluation Harness
- Standardized benchmark suites per candidate batch: docking scores,
  retrosynthesis feasibility, ADMET panels, novelty filters
- **Tournament ranking** (`c.evals.rank_batch`): Elo-style pairwise ranking of
  proposals (optionally with LLM meta-reviewer), not scalar scores — matches the
  tournament pattern validated by Google's AI co-scientist
- Emits ranked batches; the "unit tests" of the pipeline

### Fine-tuning Flywheel
- Consumes confirmed `AssayResult`s + provenance lineage as training examples
  (`c.flywheel.submit_example`): wet-lab outcomes are the ground-truth labels the
  foundation models currently lack
- Per-customer/per-program model variants, refit each design round (Cradle's model:
  wet-lab data → fine-tune → next round is the core compounding asset)
- Dataloops recorded in provenance so every model version is traceable to the exact
  experiments that trained it

## Interfaces
- Consumes: `ToolInvocation` from A/B
- Produces: `ToolResult` + `ProvenanceRecord` (model version pinned)

## Build order
1. Gateway skeleton + one small FM per family
2. Registry + evaluation harness
3. Knowledge base RAG
4. Scale-out/batching
