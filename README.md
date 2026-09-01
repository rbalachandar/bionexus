# BioNexus

[![ci](https://github.com/rbalachandar/bionexus/actions/workflows/ci.yml/badge.svg)](https://github.com/rbalachandar/bionexus/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/bionexuslab)](https://pypi.org/project/bionexuslab/)
[![Python](https://img.shields.io/pypi/pyversions/bionexuslab)](https://pypi.org/project/bionexuslab/)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)

BioNexus is an open-source framework in which AI agents run the scientific
method end to end: given a research problem and its constraints, agents propose
a portfolio of hypotheses, select the ones worth testing, design experiments,
execute them on simulated or real laboratory equipment, observe the results as
they arrive, and deliver verdicts against criteria that were registered before
the experiment ran.

Two properties make it suitable for real laboratory work rather than
demonstrations:

- **Safety is structural.** Agents never address instruments directly. Every
  physical action passes through a policy engine that sits outside the agent's
  trust boundary, and a resource budget caps what a campaign may consume.
- **Every step is auditable.** Problem, hypotheses, decisions, submissions,
  results, and verdicts are recorded in a hash-chained, tamper-evident
  provenance store that renders as a shareable report.

## How a campaign works

A campaign is started with a single command and a problem statement:

```json
{
  "problem": {
    "objective": "Find a confirmed sub-20uM KRAS_G12C binder",
    "constraints": [
      {"name": "potency", "description": "IC50 <= 20 uM", "kind": "hard",
       "limit": 20.0, "unit": "uM"}
    ],
    "success_metric": "orthogonal confirmation"
  },
  "hypotheses": [
    {"statement": "C-101 binds with IC50 <= 20 uM", "candidate": "C-101",
     "assay_type": "binding", "predicted": "IC50 <= 20",
     "predicted_value": 20.0, "rationale": "covalent warhead precedent"}
  ],
  "autonomy": "act"
}
```

```sh
bn auto campaign.json
```

The campaign then runs: the hypothesis portfolio is filtered to the top-k by
score with a diversity cap (one idea cannot crowd out others); each selected
hypothesis is designed and submitted through the safety gateway; the lab
performs it; the agent notices the device output, fits the results, and delivers
verdicts; confirmation assays are submitted to close the loop.

```
[campaign] problem prob-89fd555d: 3 hypotheses -> 2 selected
[campaign] [agent] noticed device output: sim-1403a26c.csv — reading it
[campaign] [agent] hypothesis hyp-22911313 (C-102): VALIDATED — IC50 1.833 uM vs threshold 20.0
[campaign] [agent] loop closed: confirmation assay for C-102 auto-submitted (safety-approved)
{
  "problem": "prob-89fd555d",
  "selected": ["C-101", "C-102"],
  "verdicts": {"C-101": "validated", "C-102": "validated"}
}
```

What the models contribute and what BioNexus contributes are kept explicit: the
LLM derives the SAR hypothesis, the QSAR model makes the calibrated prediction —
BioNexus is the layer that makes those results *executable, bounded, measurable,
and auditable*. Case studies 01 and 02 below were surfaced, scored, and recorded
by this harness.

### Autonomy is operator-set

| autonomy | agent behavior |
|---|---|
| `observe` | reads, fits, recommends — submits nothing |
| `gate` | proposes everything; each lab submission requires operator approval |
| `act` | autonomous within the SafetyEngine, including confirmation assays |

A `ResourceBudget` (max lab runs, hypotheses, confirmations, wall clock) is
enforced at submission and generation time; exhaustion is provenance-recorded.
Re-proposed duplicates of already-tried hypotheses are dropped automatically.

## Evidence: blind reproduction of published papers

The strongest test of the flow: hold out an entire published paper — values
excluded from training and hidden from the agent — and ask the system to
reproduce it.

| Study | Paper | Result |
|---|---|---|
| [Case study 01](case-studies/01-egfr-blind-reproduction/) | Gazit et al., *J. Med. Chem.* 1989 — the original tyrphostins paper | Q1 hypothesis identified, **qualified**: a probe confirmed the model has prior exposure to this literature (recognition, not derivation). Q2 ranking vs published IC50s passed. |
| [Case study 02](case-studies/02-az3246-hpk1/) | AZ3246 HPK1 inhibitor, *J. Med. Chem.* 2025 — post-training-cutoff | **Contamination-free.** Both checks passed: agent derived the pyrazine-carboxamide hypothesis from structures alone, and its blinded ranking (ρ = +0.42) outperformed a Random Forest trained on 25,600 other HPK1 measurements (ρ = +0.08) |

Case study 02's clean design trades the realism of case study 01 for freedom
from memorization; both READMEs document their limitations explicitly.

## For scientists

**Read your instrument exports automatically.** Point `bn read` at a
plate-reader export (CSV/TSV/XLSX, any column order, any vendor header block):

```sh
bn read synergy_export.csv
# plate: synergy_export.csv [long] | wells: 10 | controls: 2 | Z': 0.956
# compound        IC50 (uM)  points  note
# C-101                8.94       4  observed-max
# C-102                9.17       4  observed-max
```

Format, header synonyms, control wells, plate-grid layouts, and dose–response
IC50 fits are all automatic; right-censored and single-dose cases are reported
honestly.

**Don't point at files at all — the agent notices them.** `bn watch` monitors
an instrument outbox; when a reader exports a result, the agent reads it,
updates open hypotheses, and recommends the next step.

**Inspect the audit.** `bn prove <problem-id> --html report.html` renders the
hash-chained provenance of a campaign — hypotheses, criteria, decisions,
submissions — as a tamper-evident, shareable report.

## The virtual lab

BioNexus ships simulated devices so the entire loop runs offline, and so agent
behavior is testable before hardware is involved:

- **SimulatorLab** — seeded dose–response ground truth, replicates,
  counterscreen interference (PAINS-like artifacts), controls
- **ImagingSimulatorLab** — a 96-well imaging plate reader: raw fluorescence
  micrographs per well, an analysis pipeline that fits IC50s from the images,
  Z'-factor QC, and per-well artifacts (pipetting spikes, bubbles, edge effects)
- **Recording/playback** — real hardware sessions are recorded once and replay
  identically in CI

With a multimodal model, the agent can even read the plate visually:
`demo_vision_readout.py` shows a vision-LLM estimating fluorescence from pixels
alone and recovering the IC50 to the same order of magnitude as the analysis
pipeline. See [`docs/virtual-lab.md`](docs/virtual-lab.md).

## Installation

```sh
pip install bionexuslab                 # core (pydantic only) + CLI
pip install "bionexuslab[dev]"          # + development dependencies
```

Optional extras: `[models-openai]`, `[bio-rdkit]`, `[lab-imaging]`,
`[sandbox-agentenv]`, `[store-postgres]`.

## CLI

```sh
bn run examples/workflow.yml       # tournament + assay on the configured lab
bn sim                             # reference round on the virtual lab
bn read results.csv                # auto-analyze an instrument export
bn watch /path/to/outbox           # agent notices device outputs
bn auto campaign.json              # whole flow, one command
bn prove <branch> --html out.html  # tamper-evident provenance + shareable report
bn mcp                             # MCP server: drive BioNexus from Claude/Cursor
bn new-adapter lab my_robot        # scaffold a tested LabAdapter
```

## Agent Skills and MCP

BioNexus ships as an [Agent Skills](https://agentskills.io/) package
(`skills/`, `plugin.json`) and exposes its tools over MCP:

```json
{"bionexus": {"command": "bn", "args": ["mcp"]}}
```

It composes with [Scientific Agent Skills](https://github.com/K-Dense-AI/scientific-agent-skills):
those skills teach an agent *how* to author protocols and query databases;
BioNexus decides *whether they run*, and records what happened. Focused skills:
`bionexus` (overview) · `bionexus-labread` · `bionexus-labwatch` ·
`bionexus-campaign` · `bionexus-opentrons`.

Tutorials: [`notebooks/`](notebooks/) — run a campaign · write an adapter ·
bring your own model.

## Five core interfaces

Everything in BioNexus implements one of five interfaces; adapters are opt-in
and interchangeable.

| Interface | Adapters (now → roadmap) |
|---|---|
| `ModelProvider` | openai_compat (OpenAI/ollama/vLLM/stub), anthropic → gemini |
| `LabAdapter` (+ `SafetyEngine`, `LabGateway`) | simulator, imaging-simulator, Opentrons OT-2/Flex (HTTP), PlateReaderShare → cloud labs |
| `Sandbox` | local (copy-on-fork) → AgentENV (real fork/snapshot) |
| `ProvenanceStore` | sqlite → postgres, s3-worm |
| `BioTool` | rdkit descriptors → docking, ADMET, ESMFold |

## Documentation

| Doc | Contents |
|---|---|
| [`docs/QUICKSTART.md`](docs/QUICKSTART.md) | install, run, workflows |
| [`docs/ADAPTERS.md`](docs/ADAPTERS.md) | authoring adapters (labs, models, tools, stores) |
| [`docs/SAFETY.md`](docs/SAFETY.md) | safety rules, LabGateway, audit trail |
| [`docs/security.md`](docs/security.md) | threat model, trust boundaries, agent capability matrix |
| [`docs/virtual-lab.md`](docs/virtual-lab.md) | simulated devices, image-based readouts, QC and failure modes |
| [`docs/benchmarks.md`](docs/benchmarks.md) | public datasets and benchmark results |
| [`docs/domain-review.md`](docs/domain-review.md) | flow fidelity review vs. the real drug-discovery cycle |
| [`docs/stability.md`](docs/stability.md) | versioning, stability tiers, deprecation policy |
| [`docs/research-landscape.md`](docs/research-landscape.md) | review vs. Google, Anthropic, Isomorphic, Cradle, Lila, FutureHouse, OpenAI Rosalind |
| [`docs/critical-review.md`](docs/critical-review.md) | unsympathetic independent review: what works, what fails |
| [`docs/PLAN.md`](docs/PLAN.md) | build plan, principles, guardrails |
| [`case-studies/`](case-studies/) | blind reproduction studies on real published data |

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

**7 · Problem → Portfolio → Autonomous Loop** — state the problem, propose N hypotheses, filter to k, autonomous test-and-confirm with the provenance spine.

![Problem to Autonomous Loop](diagrams/svg/07-problem-loop.svg)

Styled HTML versions (dark blueprint pages with legends/captions) live in
[`diagrams/artifacts/`](diagrams/artifacts/) — open locally in a browser.

## Repository Layout

| Path | Contents |
|---|---|
| [`docs/architecture.md`](docs/architecture.md) | Architectural blocks A–F, components, responsibilities, interfaces |
| [`docs/flows.md`](docs/flows.md) | End-to-end flows: design iteration loop, fork/branch, review gates, wet-lab round trip |
| [`docs/blocks/`](docs/blocks/) | One deep-dive doc per block (A–F) |
| [`docs/research-landscape.md`](docs/research-landscape.md) | Review vs. Google AI co-scientist, Anthropic, Isomorphic, Cradle, Lila, FutureHouse, Coscientist, OpenAI Rosalind |
| [`contracts/`](contracts/README.md) | Normative contract: the pydantic models in `bionexus.core.contracts` (archived pre-implementation OpenAPI drafts kept for reference) |
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
- Scientific Agent Skills (K-Dense) — [163 validated scientific agent skills](https://github.com/K-Dense-AI/scientific-agent-skills) — complementary knowledge layer; BioNexus tools are exposed via MCP and the Agent Skills standard
- OpenAI — [GPT-Rosalind & Rosalind Workbench](https://openai.com/gpt-rosalind/) ([announcement](https://developers.openai.com/blog/rosalind-workbench)) — closed vertical competitor; see [positioning analysis](docs/research-landscape.md#rosalind-what-it-changes-and-where-bionexus-stands)
