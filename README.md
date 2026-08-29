# BioNexus (agentic-drug-discovery)

A **lean open-source framework for agentic drug discovery** — pluggable models, bio
tools, labs, and sandboxes behind five core interfaces. Like early LangChain: small,
typed, domain-specific. Not bloated: core deps = `pydantic` only.

Also home to the platform **architecture definition**: diagrams, flows, stage
descriptions, and integration contracts that the framework implements.

## Quickstart (simulator-first, no network needed)

```sh
python -m venv .venv && .venv/bin/pip install -e . dev-dependencies...  # see pyproject
.venv/bin/pip install -e ".[dev]"
.venv/bin/python examples/iteration_loop.py   # full design round on the virtual lab
.venv/bin/python -m pytest                    # 11 tests, <1s, offline
```

The example runs: candidate generation → hypothesis tournament → human-approvable
protocol → **safety engine** → virtual wet lab → fork branch → safety rejection demo →
hash-chained provenance. See [`docs/PLAN.md`](docs/PLAN.md) for the full build plan.

### Five core interfaces (everything is one of these)

| Interface | Adapters (now → roadmap) |
|---|---|
| `ModelProvider` | openai_compat (OpenAI/ollama/vLLM/stub) → anthropic, gemini |
| `LabAdapter` (+ `SafetyEngine`, `LabGateway`) | simulator → opentrons, cloud labs |
| `Sandbox` | local (copy-on-fork) → AgentENV (real fork/snapshot) |
| `ProvenanceStore` | sqlite → postgres, s3-worm |
| `BioTool` | rdkit descriptors → docking, ADMET, ESMFold |

## Architecture Diagrams

Hand-drawn blueprint-style diagrams (SVG — rendered directly on GitHub):

**1 · Layered View** — L0 governance → L3 infrastructure, with the five architectural blocks between.

![Layered View](diagrams/svg/01-layered-view.svg)

**2 · Design Iteration Loop** — one active-learning round, from dossier to next-round proposals.

![Design Iteration Loop](diagrams/svg/02-iteration-loop.svg)

**3 · Hypothesis Tournament** — Generate → Reflect → Rank → Evolve, plus the fine-tuning flywheel.

![Hypothesis Tournament](diagrams/svg/03-tournament.svg)

**4 · Wet-Lab Round Trip** — protocol through the safety boundary, instruments, and back as provenance.

![Wet-Lab Round Trip](diagrams/svg/04-wetlab-roundtrip.svg)

**5 · Fork / Snapshot Branching** — sandbox lifecycle as experiment tree.

![Fork / Snapshot Branching](diagrams/svg/05-branching.svg)

**6 · Campaign Pipeline** — target ID through trial design with human gates and failure loops.

![Campaign Pipeline](diagrams/svg/06-campaign.svg)

Styled HTML versions (dark blueprint pages with legends/captions) live in
[`diagrams/artifacts/`](diagrams/artifacts/) — open locally in a browser.

## Repository Layout

| Path | Contents |
|---|---|
| [`docs/architecture.md`](docs/architecture.md) | Architectural blocks A–F, components, responsibilities, interfaces |
| [`docs/flows.md`](docs/flows.md) | End-to-end flows: design iteration loop, fork/branch, review gates, wet-lab round trip |
| [`docs/blocks/`](docs/blocks/) | One deep-dive doc per block (A–F) |
| [`docs/research-landscape.md`](docs/research-landscape.md) | Review vs. Google AI co-scientist, Anthropic, Isomorphic, Cradle, Lila, FutureHouse, Coscientist |
| [`contracts/`](contracts/README.md) | The five shared integration contracts (StageTask, ToolInvocation, ProtocolSubmission, AssayResult, ProvenanceRecord) |
| [`diagrams/`](diagrams/) | SVG diagrams + styled HTML artifact pages |

## Architectural Blocks at a Glance

| Block | Name | Layer | Can start with |
|---|---|---|---|
| [A](docs/blocks/A-orchestration.md) | Workflow & Orchestration | L1 | stub tool endpoints |
| [B](docs/blocks/B-agents.md) | Agent Workforce | L2 | virtual lab + mocked models |
| [C](docs/blocks/C-models-knowledge.md) | Model & Knowledge Services | L2 | open-source FMs on a GPU box |
| [D](docs/blocks/D-lab-execution.md) | Lab Execution | L2/L3 | full virtual lab simulator |
| [E](docs/blocks/E-simulation-data.md) | Simulation & Data Services | L2 | existing MD/docking tools |
| [F](docs/blocks/F-infrastructure.md) | Infrastructure (AgentENV) | L3 | exists — integrate |

## Design Principles

1. **Contract-first integration** — blocks communicate only through five versioned
   schemas; nothing else couples them.
2. **Hardware behind an abstraction** — agents see the Instrument Abstraction Layer
   (IAL) only; a Virtual Lab Simulator is a drop-in stand-in for real robots.
3. **State is snapshot-able** — every experiment branch runs in a sandbox that can be
   forked, paused at review gates, and replayed for audits.
4. **Provenance is immutable** — every artifact carries full lineage (inputs, model
   versions, prompts, instrument run IDs) in WORM storage.
5. **Safety is non-bypassable** — a policy engine sits in the physical-action path,
   outside any agent's trust boundary.

## References & Sources

The architecture draws on published work from teams operating in this space. The
full review — what each system does, how it compares, and which learnings were
folded into this design — is in [`docs/research-landscape.md`](docs/research-landscape.md).

**Key sources:**

- Google — [AI co-scientist](https://research.google/blog/accelerating-scientific-breakthroughs-with-an-ai-co-scientist/) ([paper](https://arxiv.org/abs/2502.18864)) · [AlphaFold 3](https://www.nature.com/articles/s41586-024-07487-w) · [Isomorphic Labs Drug Design Engine](https://www.isomorphiclabs.com/articles/the-isomorphic-labs-drug-design-engine-unlocks-a-new-frontier) · [Bioresilience approach](https://www.isomorphiclabs.com/articles/our-approach-to-bioresilience)
- Anthropic — [Claude for Life Sciences](https://www.anthropic.com/news/claude-for-life-sciences) · [Model Hardware Standard](https://www.anthropic.com/news/model-hardware-standard-research-preview)
- Cradle Bio — [Platform](https://www.cradle.bio/platform) · [Series B / wet-lab expansion](https://techcrunch.com/2024/11/26/cradle-builds-out-its-protein-design-ai-platform-and-wet-lab-with-73m-in-new-funding/)
- FutureHouse — [Robin multi-agent system](https://www.futurehouse.org/research-announcements)
- Lila Sciences — [Agent-driven science on NVIDIA BioNeMo](https://www.lilasciences.com/news/building-the-agent-driven-era-of-science-with-nvidia-bionemo-agent-toolkit)
- Helical — [Virtual AI lab / Helix-mRNA FM](https://www.helical.bio/)
- Coscientist (CMU) — [Autonomous chemical research with LLMs + robotics, Nature 2023](https://www.nature.com/articles/s41586-023-06792-0)
- OpenAI + Retro Biosciences — [GPT-4b micro protein engineering, MIT Tech Review](https://www.technologyreview.com/2024/12/09/1108188/openai-model-for-protein-engineering-gpt-4b-micro-retro-biosciences/)
- Chai Discovery — [chai-1/chai-2 structure & antibody models](https://www.chaidiscovery.com/)
