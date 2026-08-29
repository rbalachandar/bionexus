# Block B — Agent Workforce (L2)

Six specialized agents. Each is a process inside an AgentENV sandbox, consuming the
tool API contract only.

## Roster

| Agent | Modality | Key tools consumed |
|---|---|---|
| Target Research Agent | text/omics | knowledge base (RAG), omics DBs |
| Design Agent (Chemist) | small molecules | FM gateway (generative chemistry, structure), molecule registry, evaluation harness |
| Biology Agent | proteins/antibodies | FM gateway (protein structure/design), sequence registry |
| Assay Planning Agent | protocols | lab capability catalog (from IAL), protocol templates |
| Analysis Agent | results | provenance queries, statistics tools, feature store |
| Trial Design Agent | clinical | trial simulation (E), historical trial data |

## Sandbox lifecycle mapping (AgentENV)

- **create** — one sandbox per experiment branch, rootfs pre-loaded with the agent's
  toolchain
- **fork** — branch at hypothesis split points (e.g., N parallel assay-plan variants)
- **snapshot/pause** — freeze full agent state at review gates; resume with identical
  context
- **custom extension hooks** — start/stop/patch-params for checkpointing and lab
  callback wiring

## Loop behavior

Analysis Agent drives the active-learning loop: interprets `AssayResult`s, queries
provenance for the full branch history, and emits structured `next_round_proposals`
that the Stage Graph turns into new `StageTask`s.

## Constraints

- Agents never talk to hardware or registries directly — only via tool invocations
  routed through A
- Agents cannot mark protocols safe; only the Safety Engine (D) can
- All agent outputs are `ProvenanceRecord`-wrapped (inputs, prompts, model versions)
