# Research Landscape — Agentic Drug Discovery (2024–2026)

Conceptual review of published systems from companies working in this space, and how
our architecture compares. Last reviewed: 2026-10.

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
| **Google DDE — Drug Design Engine** (open plan, Oct 2026; ⚠ distinct from Isomorphic's same-named platform) | Packaged scion-based agent templates: Science Program Lead + Research Operations Controller + ~12 lean specialist roles; 4 invariant pre-clinical stages × modality tables; 5 artifact layers; skills = judgment, `dde` CLI = computation | **None** — artifacts/compute only; wet lab lives outside the system | None yet — it is a normative plan doc, not a graded system |
| **The Virtual Biotech** (2026) | Multi-agent org chart: virtual CSO + chief-of-staff + four scientist divisions (Target ID/Prioritization, Target Safety, Modality Selection, Clinical Officers) + scientific reviewer; 100+ domain MCP servers over biomedical DBs (78k targets, 14.5M PPIs, Tahoe-100M perturbation, FAERS, ClinicalTrials.gov) | **None** — analysis/evidence only; no wet lab, no physical loop | Evidence-based target/modality assessments; organizational auditability ("each agent audited by the corresponding human expert") |

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

## The Virtual Biotech: complementary, not competitive

The Virtual Biotech (VB) is the clearest statement yet of the
**pre-lab half** of the pipeline: translational evidence synthesis from
target identification through modality selection. BioNexus is the
clearest open statement of the **lab half**: the gated, audited
Design-Make-Test-Analyze loop that turns a *selected* modality and
target into verdicts with CIs. The two compose at a clean seam —
VB's Modality Selection output (modality + target + evidence) is
exactly BioNexus's program definition.

**What VB has that we do not** (adopted into the roadmap):
1. **Division-shaped decomposition** — target ID, target safety,
   modality selection, clinical officers as distinct analyst roles with
   curated tool subsets. Our problem trees decompose by scientific
   objective but not by *translational function*.
2. **Scientific reviewer agent** — a critic pass over methodology and
   claims before synthesis, with the CSO coordinating revisions. Maps
   1:1 onto our tiered-trust rule (AI may tighten, never clear).
3. **Clarify-before-compute orchestration** — the CSO asks follow-up
   questions and the chief-of-staff preps a data-availability briefing
   before expensive analyses run.
4. **Biomedical knowledge breadth** — 100+ MCP servers over genetics,
   PPIs, single-cell, perturbation, FAERS, trials.

**What we have that VB does not** (from their own framing, analysis/
evidence only): a physical loop. No gateway on physical actions, no
synthesis/production gates, no instrument adapters, no budgets, no
hash-chained execution provenance, no verdict discipline against
pre-registered CIs, no eval suite against seeded ground truth. VB
*recommends*; BioNexus *executes and verifies*.

**Folded back into the design** (see ROADMAP, "Virtual Biotech
learnings"): reviewer pass on verdicts, division-shaped tree
decomposition, pre-campaign briefing/clarification step, MCP-client
consumption of external knowledge during Design.

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


## Tools & standards: Scientific Agent Skills (K-Dense)

[scientific-agent-skills](https://github.com/K-Dense-AI/scientific-agent-skills)
(38k+ stars, MIT, Agent Skills standard) — 163 CI-validated skills giving agents
domain knowledge: RDKit/Datamol cheminformatics, PyTDC benchmarks, DiffDock
screening, PK/PD modeling, an Opentrons protocol-authoring skill, 78+ scientific
database lookups (ChEMBL, PubChem, UniProt, COSMIC...), and evidence-bounded
hypothesis generation.

**Relationship to BioNexus — complementary layers:**

| Layer | Provider |
|---|---|
| Domain knowledge & procedures (how to use RDKit, query ChEMBL, author protocols) | Scientific Agent Skills |
| Execution, safety, provenance, autonomy, lab devices | BioNexus |
| Bridge between them | Agent Skills standard + BioNexus MCP server |

Their Opentrons skill teaches an agent *how to author protocols*; our
`LabGateway` decides *whether they may run* (SafetyEngine first, always).
Benchmarks note: their skills include PyTDC access — the natural bridge to our
planned TDC benchmark adapter.

Sources: https://github.com/K-Dense-AI/scientific-agent-skills ·
https://agentskills.io/


## Genentech — AssayLoop / AssayFormer (arXiv 2609.11877, Sep 2026)

"Biology-in-the-loop": sequential hit discovery in CRISPR screens. An LLM runs
the first rounds from priors; AssayFormer, a transformer trained on 1,349
historical screens, takes over with those observations as context, choosing
the next 100 genes per round. Recovers 27.7% of hits after 5% of the library.
`assaybench` (PyPI, MIT) ships the Task/Model/Acquisition/Metric abstractions.

Relation to BioNexus: complementary layers, not competitors. AssayLoop is a
decision policy (which candidate next, retrospective eval on historical
screens). BioNexus is the execution and trust layer (safety-gated submissions
to real or simulated instruments, pre-registered criteria, hash-chained
provenance, human approval, evals in CI). The bridge is
`adapters/models/assayloop_ranker.py`: any assaybench-style policy can rank
candidates inside a BioNexus campaign; their loop ends at metrics, ours
continues to the lab and the record. We adopted their metric vocabulary
(adjusted nAUC, fraction-of-hits, shortfall, %essential) into the
`hit-recovery` eval task.

## Google DDE (Cloud LifeSciences, Oct 2026): convergence as validation

`GoogleCloudPlatform/LifeSciences/applications/drug-design-engine` — a
55 KB normative plan for an agentic pre-clinical R&D system (templates +
skills + a `dde` CLI on the scion orchestrator). It is a plan, not a
graded system, and it names **Isomorphic's** flagship as its own name —
but it is the strongest third-party convergence on our thesis we have
seen, so it goes in full.

**Where DDE independently reinvents BioNexus principles:**
- **Anti-fabrication as structure, not exhortation** (their §2.5): "a
  model asked for a pocket volume with no pocket-detection tool will
  produce a plausible one" — mitigation: every claimed capability maps to
  a real tool; "tools fail loudly and never synthesize"; every output is
  a durable checksummed artifact a claim must cite. That is our
  evidence-bound verdicts, input trust boundary, and regime gate in
  prose.
- **Computed vs judged artifact split** (their Layers 0/1): review is
  *mechanical* — re-run `analyze`, diff, then ask whether the prose is
  supported. That is our reviewer holding the analysis honest + chain
  recompute-on-read.
- **Thresholds outside model reach** (`.dde/thresholds.yaml`,
  "computation in tools, judgment in skills, a threshold belongs in
  configuration") — our pre-registered `SuccessCriteria` + safety floor
  the agent cannot clear, with one difference: config files mutate
  silently; ours are registered in the hash chain *before* the run.
- **Ephemeral specialists with immutable work-order context slices** —
  our retrieval traces (prompt hash + injected negatives per generation).
- **Batch-over-event reasoning for pattern recognition** + interrupt on
  safety alerts — our S-T1 series views / diary cohorts + gate alerts,
  landed a month ago.
- Independent scientific reviewer, stage-gate decision questions,
  modality-invariant loop — our tracker/watch split, program gates,
  modality packs.

**Where they are not, and we should say so precisely:**
1. **No lab.** DDE's boundary is documents and compute; no instrument
   ingestion, no adapters, no robot path. We read real Tecan/BioTek/Gen5
   dirt, gate synthesis routes, and run replayable lab abstractions.
2. **Honesty without math.** DDE's safeguards are procedural (layering,
   review, contracts). There is no uncertainty physics in the plan: no
   CIs on estimates, no abstain-when-straddling rule, no bootstrap, no
   graded eval of overclaiming, no regime-invariance argument (our
   affine-invariant shape admits / CS06-style refusals have no DDE
   analogue). "Caveats & Confidence" is a *reporting section*, not a
   verdict veto.
3. **Nothing is scored.** No leaderboard, no reproduction studies, no
   published failures. Our differentiator is precisely that our
   honesty-claims are graded (0.979 eval mean; CS05 98.9%/0-FP; CS06
   published negative).
4. Cloud/Gemini-shaped (scion, Vertex tooling); ours is provider-agnostic
   and hermetic-offline by CI.

**Position taken:** DDE validates the category at platform scale and
maps the *program* surface (genetics→IND dossier) far wider than our
DMTA loop — useful reading for where investors will push us. It does not
touch the ground our moat is on: quantified, graded, lab-connected
epistemics. No design changes folded back (the convergent parts were
already shipped); the sharpened pitch line is borrowed, though: *"tools
fail loudly and never synthesize"* — now echoed in the README trust row.

Sources: plan https://github.com/GoogleCloudPlatform/LifeSciences/blob/main/applications/drug-design-engine/docs/dde-plan.md (plus orchestration/skills/tool guidance siblings in that docs/).
