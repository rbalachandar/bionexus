# Research Landscape — Agentic Drug Discovery (2024–2026)

Conceptual review of published systems from companies working in this space, and how
our architecture compares. Last reviewed: 2026-08.

## Landscape summary

| System | Architecture | Lab integration | Published results |
|---|---|---|---|
| **Google AI co-scientist** (Feb 2025) | Multi-agent on Gemini 2.0: Supervisor + Generate, Reflect, Rank (Elo tournaments), Evolve, Proximity, Meta-review; test-time compute scaling | Hypotheses validated by partner labs | AML drug repurposing (KIRA6 killed AML cell lines at clinical concentrations); liver-fibrosis targets w/ Stanford; beat SOTA agentic models on 15 expert goals (Elo) |
| **Anthropic Claude for Life Sciences** (Oct 2025) | General agent + MCP connectors (Benchling, PubMed, 10x Genomics) + Agent Skills; partners build bio agents on Claude | **Model Hardware Standard** research preview for agents operating lab devices | Protocol QA 0.83 (human 0.79); Sanofi, Novo Nordisk, Broad |
| **Isomorphic Labs** | "Drug Design Engine": predictive+generative beyond AlphaFold 3, co-folding ligands/nucleic acids | In-house experimental teams; Novartis + Lilly deals (~$3B) | AF3 ~76% PoseBusters pose success; first candidates toward clinic 2025–26 |
| **Cradle Bio** | Design rounds: generate → multi-property optimize → analyze; ML pipelines | Own wet lab; per-customer fine-tuning each round | Up to 12× shorter protein R&D cycles; 6 of top-25 pharma |
| **Helical** | "Virtual AI lab" + Helix-mRNA FM (500M, post-trained on therapeutics evaluation) | Virtual-first | — |
| **Lila Sciences** | LLM agents on NVIDIA BioNeMo Agent Toolkit + autonomous "AI Science Factory" | Fully autonomous labs | CAR-T-adjacent RNA engine outperforming leading CAR-T in NHPs; $435M raised |
| **FutureHouse Robin** (May 2025) | Multi-agent: PaperQA2 literature agents → hypothesis → protocol | Partner labs | Dry-AMD candidate (RIPK1) validated in retinal organoids |
| **Coscientist** (CMU, Nature 2023) | GPT-4 planner + code exec + robot API docs (Opentrons, Chemify) | Real Suzuki/Sonogashira syntheses, chemist-approved | Canonical LLM+robot-lab demo |
| **OpenAI + Retro GPT-4b micro** (Dec 2024) | Fine-tuned GPT-4 variant for protein design | Retro wet lab | Designs beating human-made Yamanaka-factor variants >50× in some assays |
| **Chai Discovery** | chai-1/chai-2 structure + antibody design FMs; CAD-suite, not agentic | Partner validation | Novartis, Pfizer, Lilly deals |
| **OpenAI Rosalind Workbench** (Aug 2026) | GPT-Rosalind (dedicated life-sciences model) + Workbench: in-chat molecular/structure viewers, sequence alignment, plan-first NGS Analysis Workbench; Explore vs. gated Research modes; built into ChatGPT and Codex | Wet-lab *assistance* and tool orchestration; no owned lab fleet | Enterprise-first (verified orgs); "every scientist to be their own research team" |

## Rosalind: what it changes, and where BioNexus stands

OpenAI's Rosalind (model April 2026, Workbench Aug 28 2026) validates the
category this project works in: LLM agents + domain tools + reviewable plans
for life-science R&D. Reading the announcement carefully against our design:

**What Rosalind is:** a closed, vertical product — one frontier model + a
curated tool suite (structure viewers, NGS workbench) inside ChatGPT/Codex,
with access gated by organization and OpenAI deciding which workflows exist.

**What it is not:** open infrastructure. You cannot run Rosalind's brain on
your data on your terms, add your own lab adapters, extend the workflow
grammar, or audit its decision path — and it has no wet-lab execution layer,
no provenance chain, and no sandbox fork/snapshot semantics.

**BioNexus positioning against it:**

| Dimension | Rosalind Workbench | BioNexus |
|---|---|---|
| Model | Locked (GPT-Rosalind) | Any provider (P3) — including GPT-Rosalind itself via adapter |
| Workflows | Curated by OpenAI | User-defined stage graphs + tournaments |
| Wet lab | Assistance only | IAL + SafetyEngine + device sims, real adapters (P4/P6) |
| Provenance | Reviewable outputs (UI-level) | Hash-chained, tamper-evident, WORM (P5) |
| Experiment semantics | Plan-first UI | Pre-registered hypotheses w/ criteria, design, QC-aware verdicts |
| Access | Enterprise research preview | Open source, Apache-2.0 |
| Is it a competitor? | Competitor for *scientist attention*; **potential upstream**: GPT-Rosalind is a plausible `ModelProvider` inside BioNexus |

**Strategic take:** don't compete with Rosalind on model quality — impossible
and unnecessary. Compete on the layers OpenAI won't open: the lab-in-the-loop
abstraction, the safety/provenance substrate, and freedom of model/workflow
choice. The MCP server (`bn mcp`) is the bridge: any agent stack, including
OpenAI's, can drive BioNexus labs.

Sources: https://openai.com/gpt-rosalind/ ·
https://developers.openai.com/blog/rosalind-workbench ·
https://help.openai.com/en/articles/20001193-gpt-rosalind-for-life-sciences-research

## What our architecture already gets right

1. **Fork/snapshot experiment branching** (AgentENV) — unique in the field; no
   published system captures full agent state at review gates for replay/audit.
2. **Contract-first decoupling** (5 schemas) — matches the direction of MCP (Anthropic)
   and BioNeMo Agent Toolkit (NVIDIA); the agent layer is commoditizing, the moat is
   orchestration + lab + data flywheel.
3. **Safety outside the agent trust boundary** — aligned with Anthropic's Model
   Hardware Standard and Isomorphic's "bioresilience".

## Learnings folded back into the design

| Gap | Evidence | Change made |
|---|---|---|
| Single-shot hypothesis generation | Google's Generate/Reflect/Rank/Evolve tournament is SOTA | Block B: hypothesis tournament stage; Block C: `c.evals.rank_batch` |
| No data flywheel | Cradle's per-round fine-tuning loop is its entire model | Block C: fine-tuning flywheel consuming `AssayResult`s; `c.flywheel.*` tools |
| Thin literature layer | FutureHouse PaperQA2-grade agents are proven stage-one assets | Block B: literature agent upgraded to agent-grade (hypothesis support, citations) |
| Proprietary tool wire format | MCP + Model Hardware Standard are becoming standards | Block D: IAL aligns with MCP semantics + tracks Model Hardware Standard |
| Scored-only ranking | Tournament ranking outperforms scalar scoring | Block C: Evaluation Harness gains Elo-style tournament ranking |

## Sources

- Google AI co-scientist: https://research.google/blog/accelerating-scientific-breakthroughs-with-an-ai-co-scientist/ · https://arxiv.org/abs/2502.18864
- Claude for Life Sciences: https://www.anthropic.com/news/claude-for-life-sciences · Model Hardware Standard: https://www.anthropic.com/news/model-hardware-standard-research-preview
- Isomorphic Drug Design Engine: https://www.isomorphiclabs.com/articles/the-isomorphic-labs-drug-design-engine-unlocks-a-new-frontier
- Cradle: https://www.cradle.bio/platform
- Helical: https://www.helical.bio/
- Lila + BioNeMo: https://www.lilasciences.com/news/building-the-agent-driven-era-of-science-with-nvidia-bionemo-agent-toolkit
- FutureHouse Robin: https://www.futurehouse.org/research-announcements
- Coscientist: https://www.nature.com/articles/s41586-023-06792-0
- GPT-4b micro: https://www.technologyreview.com/2024/12/09/1108188/openai-model-for-protein-engineering-gpt-4b-micro-retro-biosciences/
