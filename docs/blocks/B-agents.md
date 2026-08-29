# Block B — Agent Workforce (L2)

Six specialized agents. Each is a process inside an AgentENV sandbox, consuming the
tool API contract only.

## Roster

| Agent | Modality | Key tools consumed |
|---|---|---|
| Literature Agent | text | knowledge base (RAG), citations-grounded QA (PaperQA2-grade) |
| Target Research Agent | text/omics | knowledge base, omics DBs, literature agent |
| Design Agent (Chemist) | small molecules | FM gateway (generative chemistry, structure), molecule registry, evaluation harness |
| Biology Agent | proteins/antibodies | FM gateway (protein structure/design), sequence registry |
| Assay Planning Agent | protocols | lab capability catalog (from IAL), protocol templates |
| Analysis Agent | results | provenance queries, statistics tools, feature store |
| Trial Design Agent | clinical | trial simulation (E), historical trial data |

## Hypothesis tournament (per design round)

Design rounds are not single-shot. Modeled on Google's AI co-scientist
(Generate/Reflect/Rank/Evolve), each round runs:

```text
Generate   — N candidate proposals per iteration (diverse prompts/seeds)
Reflect    — agents self-critique + cross-critique (structured review rubric)
Rank       — Elo-style tournament via Evaluation Harness (c.evals.rank_batch);
             pairwise debates with a meta-reviewer agent resolving disputes
Evolve     — top proposals seed the next generation; losers feed ablation/provenance
```

The tournament runs *inside* the sandbox branch (forked per generation wave), so
every proposal's full lineage is snapshot-replayable. Tournament state is recorded
as `evaluation` ProvenanceRecords.

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
