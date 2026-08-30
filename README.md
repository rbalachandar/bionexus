# BioNexus

[![ci](https://github.com/rbalachandar/bionexus/actions/workflows/ci.yml/badge.svg)](https://github.com/rbalachandar/bionexus/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/bionexuslab)](https://pypi.org/project/bionexuslab/)
[![Python](https://img.shields.io/pypi/pyversions/bionexuslab)](https://pypi.org/project/bionexuslab/)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)

**Agents that run the scientific method:** state the problem, propose a
portfolio of hypotheses, filter to the ones worth testing, design and run the
experiments (simulated or real), notice the results, deliver verdicts against
pre-registered criteria — all inside a safety boundary, all recorded in
tamper-evident provenance.

An **open-source framework for agentic drug discovery** — pluggable models, bio
tools, labs, and sandboxes behind five core interfaces.

Core dependencies: `pydantic` only. Everything else (models, labs, sandboxes,
stores) is an adapter you opt into.

## For scientists: read your instrument exports automatically

The point of the library: **devices and labs produce files; BioNexus reads
them.** Point it at a plate-reader export (CSV/TSV/XLSX, any column order, any
vendor header block) — it auto-detects the format, finds your controls, fits
dose–response IC50s, and computes assay QC:

```sh
.venv/bin/bn read synergy_export.csv
# plate: synergy_export.csv [long] | wells: 10 | controls: 2 | Z': 0.956
# compound        IC50 (uM)  points  note
# C-101                8.94       4  observed-max
# C-102                9.17       4  observed-max
```

Or in Python:

```python
from bionexus.labread import read_plate
r = read_plate("my_results.csv")   # auto-detect: long/grid/xlsx/imaging evidence
print(r)                           # IC50 table + Z' — no configuration
```

Recognized automatically: header synonyms (`Well/Position`, `Compound/Sample`,
`Conc/Dose`, `RFU/OD/Value/...`), vendor metadata header lines (skipped),
control wells (`ctrl/control/blank/vehicle/DMSO/...`), plate-grid layouts
(rows A–P × numbered columns), and BioNexus imaging evidence (`.npy` well
images). Right-censored and single-dose cases are reported honestly.

### You don't even point at the file — the agent notices it

Watch an instrument outbox and the agent reacts on its own: reads the export,
updates open hypotheses, and tells you what to do next:

```sh
.venv/bin/bn watch /path/to/instrument_outbox
```

```
[instrument] run 0042 complete -> synergy_run0042.csv exported
[agent] noticed device output: synergy_run0042.csv — reading it
[agent] analyzed: 1 compound(s), Z'=0.96
[agent] hypothesis hyp-45357756 (C-101): VALIDATED — IC50 8.944 uM vs threshold 20.0
[agent] recommendation: best binder so far is C-101 (IC50 8.944 uM) — next: confirm with orthogonal assay
```

The same event interface maps to real push sources (instrument webhooks, lab
queue callbacks) — inbox watching is the lowest-common-denominator that works
with every instrument that exports a file.

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

### Simulated lab devices with image readouts

The virtual lab goes one level deeper: a simulated **imaging plate reader**. A
protocol run captures raw fluorescence micrographs per well (96-well plate), an
analysis pipeline fits dose–response IC50s **from the images**, and assay QC is a
Z' factor computed from controls. Measured IC50s recover the seeded ground truth
within realistic noise, and the raw well images are kept as evidence that agents
(or vision-capable LLMs) can inspect:

```sh
.venv/bin/pip install numpy                       # [lab-imaging] extra
.venv/bin/python examples/demo_imaging.py
# run img-c2f0183b: Z'=0.938 (controls PASS)
#   compound    measured IC50   ground truth
#   C2              11.98 uM      10.85 uM
# raw evidence: 14 well images in .data/images/
```

Failure modes are simulated too: well artifacts (pipetting spikes, bubbles, edge
effects) are flagged, weak compounds are right-censored (no IC50 — test higher
concentrations), and runs failing Z' QC are marked unusable. See
[`docs/virtual-lab.md`](docs/virtual-lab.md).

## The whole flow, one command

Everything composes into a single campaign: **problem + constraints → hypothesis
portfolio → filter to top-k → design → safety-gated wet-lab → agent notices →
analysis → verdict → confirmation loop.**

```sh
.venv/bin/bn auto campaign.json
```

<details><summary>campaign.json — the problem, stated like a scientist would</summary>

```json
{
  "problem": {
    "objective": "Find a confirmed sub-20uM KRAS_G12C binder for lead development",
    "constraints": [
      {"name": "potency", "description": "IC50 <= 20 uM", "kind": "hard", "limit": 20.0, "unit": "uM"},
      {"name": "budget",  "description": "max 2 hypotheses to wet-lab", "kind": "hard"}
    ],
    "success_metric": "orthogonal confirmation"
  },
  "hypotheses": [
    {"statement": "C-101 binds with IC50 <= 20 uM", "candidate": "C-101",
     "assay_type": "binding", "predicted": "IC50 <= 20", "predicted_value": 20.0,
     "rationale": "covalent warhead precedent"},
    {"statement": "C-102 binds with IC50 <= 20 uM", "candidate": "C-102",
     "assay_type": "binding", "predicted": "IC50 <= 20", "predicted_value": 20.0,
     "rationale": "scaffold hop"}
  ],
  "scores": {"C-101": 0.9, "C-102": 0.8},
  "k": 2,
  "autonomy": "act"
}
```
</details>

Actual output:

```
[campaign] problem prob-89fd555d: 3 hypotheses -> 2 selected
[campaign] [agent] noticed device output: sim-1403a26c.csv — reading it
[campaign] [agent] analyzed: 1 compound(s), Z'=0.946
[campaign] [agent] hypothesis hyp-22911313 (C-102): VALIDATED — IC50 1.833 uM vs threshold 20.0
[campaign] [agent] recommendation: best binder so far is C-102 (IC50 1.833 uM) — next: confirm with orthogonal assay
[campaign] [agent] loop closed: confirmation assay for C-102 auto-submitted (safety-approved) -> run sim-e67698bc
{
  "problem": "prob-89fd555d",
  "selected": ["C-101", "C-102"],
  "verdicts": {"C-101": "validated", "C-102": "validated"}
}
```

Every step is provenance-recorded: the problem and its constraints, why each
hypothesis made or missed the cut, which criteria each verdict used, and every
safety-gated submission — `bn prove <problem-id> --html report.html` renders it
as a tamper-evident audit.

### You choose how much the agent does

| autonomy | agent behavior |
|---|---|
| `observe` | reads, fits, recommends — **submits nothing** |
| `gate` | proposes everything; **each lab submission needs operator approval** |
| `act` | fully autonomous within the SafetyEngine (incl. confirmation assays) |

The same flow also runs step-by-step by hand (see the notebooks) — the manual
and agent paths share the same five interfaces, so you can start manual and
hand stages to the agent as trust grows.

**CLI:**

```sh
bn run examples/workflow.yml       # tournament + assay on the configured lab
bn sim                             # reference round on the virtual lab
bn read results.csv                # auto-analyze an instrument export
bn watch /path/to/outbox           # agent notices device outputs
bn auto campaign.json              # whole flow, one command
bn prove <branch> --html out.html  # tamper-evident provenance + shareable report
bn mcp                             # MCP server: drive BioNexus from Claude/Cursor
```

**Works with Claude / Cursor / any MCP client** — add to your MCP config:

```json
{"bionexus": {"command": "bn", "args": ["mcp"]}}
```

Exposes `generate_candidates`, `run_assay` (dose-response + IC50),
`propose_hypothesis`, and `list_lab_capabilities` as agent tools.

**Tutorials:** [`notebooks/`](notebooks/) — run a campaign · write an adapter · bring your own model.

**Extend it:**

```sh
bn new-adapter lab my_robot      # scaffold a tested LabAdapter in seconds
bn new-adapter tool my_docking --cap e.sim.docking
```

See [`docs/ADAPTERS.md`](docs/ADAPTERS.md) and the
[stability policy](docs/stability.md) — the five core interfaces are stable
surfaces with additive-evolution guarantees.

| Doc | Contents |
|---|---|
| [`docs/QUICKSTART.md`](docs/QUICKSTART.md) | install, run, workflows |
| [`docs/ADAPTERS.md`](docs/ADAPTERS.md) | authoring adapters (labs, models, tools, stores) |
| [`docs/SAFETY.md`](docs/SAFETY.md) | safety rules, LabGateway, audit trail |
| [`docs/domain-review.md`](docs/domain-review.md) | flow fidelity review vs. the real drug-discovery cycle |
| [`docs/benchmarks.md`](docs/benchmarks.md) | public datasets (MoleculeNet, TDC, DOCKSTRING, ProteinGym) + first benchmark results |
| [`docs/virtual-lab.md`](docs/virtual-lab.md) | simulated devices, image-based readouts, QC and failure modes |
| [`docs/security.md`](docs/security.md) | threat model, trust boundaries, agent capability matrix |
| [`docs/stability.md`](docs/stability.md) | versioning, stability tiers, deprecation policy |
| [`docs/PLAN.md`](docs/PLAN.md) | build plan, principles, guardrails |

### Five core interfaces (everything is one of these)

| Interface | Adapters (now → roadmap) |
|---|---|
| `ModelProvider` | openai_compat (OpenAI/ollama/vLLM/stub) → anthropic, gemini |
| `LabAdapter` (+ `SafetyEngine`, `LabGateway`) | simulator, imaging-simulator (synthetic plate images + analysis + Z' QC) → opentrons, cloud labs |
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
- OpenAI — [GPT-Rosalind & Rosalind Workbench](https://openai.com/gpt-rosalind/) ([announcement](https://developers.openai.com/blog/rosalind-workbench)) — closed vertical competitor; see [positioning analysis](docs/research-landscape.md#rosalind-what-it-changes-and-where-bionexus-stands)
