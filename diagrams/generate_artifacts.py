#!/usr/bin/env python3
"""Generate Claude-artifact-style HTML pages for each architecture diagram.

Each page is self-contained (Mermaid from CDN) with a warm, artifact-like
presentation. Outputs to diagrams/artifacts/.
"""
import pathlib

OUT = pathlib.Path(__file__).parent / "artifacts"

TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} · Agentic Drug Discovery</title>
<script type="module">
  import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs';
  mermaid.initialize({{
    startOnLoad: true,
    theme: 'base',
    themeVariables: {{
      primaryColor: '#f5f0e8',
      primaryTextColor: '#3d3929',
      primaryBorderColor: '#d9c9a8',
      lineColor: '#8a7f6a',
      secondaryColor: '#eef3ee',
      tertiaryColor: '#f7f4ef',
      fontFamily: 'ui-sans-serif, system-ui, -apple-system, sans-serif',
      fontSize: '15px'
    }},
    flowchart: {{ curve: 'basis', padding: 16 }},
    sequence: {{ actorMargin: 42, noteMargin: 12 }}
  }});
</script>
<style>
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 0;
    background: #faf9f5;
    color: #3d3929;
    font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
    min-height: 100vh;
    display: flex; flex-direction: column; align-items: center;
  }}
  .artifact {{
    width: min(1200px, 96vw);
    margin: 32px 0 48px;
    background: #ffffff;
    border: 1px solid #e8e2d6;
    border-radius: 16px;
    box-shadow: 0 4px 24px rgba(60, 50, 30, 0.07);
    padding: 40px 44px 32px;
  }}
  h1 {{
    font-size: 22px; font-weight: 600; margin: 0 0 4px;
    letter-spacing: -0.01em;
  }}
  .subtitle {{
    font-size: 14px; color: #8a7f6a; margin: 0 0 28px;
  }}
  .badge {{
    display: inline-block; font-size: 11px; font-weight: 600;
    letter-spacing: 0.06em; text-transform: uppercase;
    background: #f0ebe0; color: #6b604a;
    border-radius: 999px; padding: 3px 10px; margin-bottom: 14px;
  }}
  .diagram {{ overflow-x: auto; }}
  .footer {{
    font-size: 12px; color: #a89e8a; margin-top: 24px;
    border-top: 1px solid #f0ece2; padding-top: 14px;
  }}
  .footer a {{ color: #a1662f; text-decoration: none; }}
</style>
</head>
<body>
  <main class="artifact">
    <span class="badge">Agentic Drug Discovery · Architecture</span>
    <h1>{title}</h1>
    <p class="subtitle">{subtitle}</p>
    <div class="diagram">
<pre class="mermaid">
{mermaid}
</pre>
    </div>
    <div class="footer">Interactive diagram — pan/zoom with the trackpad or open in a full
    browser tab. Source: <a href="../../{source}">{source}</a></div>
  </main>
</body>
</html>
"""

D = {}

D["00-top-level"] = dict(
    title="Platform — Layered View",
    subtitle="L0 Human & Governance → L3 Infrastructure (AgentENV), with the five architectural blocks between.",
    source="docs/architecture.md",
    mermaid="""flowchart TB
    subgraph L0["L0 · Human & Governance"]
        UI["Scientist Reviewer UI"]
        Gates["Approval Gates"]
        Audit["Audit & Compliance"]
    end
    subgraph L1["L1 · Orchestration"]
        WF["Stage Graph Engine"]
        Router["Agent Router"]
        Prov["Provenance Store"]
        Ledger["Experiment Ledger"]
    end
    subgraph L2["L2 · Agent & Service Workforce"]
        Agents["Agent Workforce<br/>Target · Design · Biology<br/>Assay · Analysis · Trial"]
        Models["Bio FM Gateway &<br/>Knowledge Services"]
        Lab["Lab Execution<br/>IAL · Safety · Simulator"]
        Sim["Simulation &<br/>Data Services"]
    end
    subgraph L3["L3 · Infrastructure (AgentENV)"]
        SBX["Agent Sandboxes<br/>snapshot · fork · resume"]
        CP["Gateway & Scheduler<br/>multi-node control plane"]
        ART["Artifact & P2P Storage"]
    end
    L0 -->|approvals, context| L1
    L1 -->|StageTask| Agents
    L1 -->|ToolInvocation| Models
    L1 -->|ToolInvocation| Lab
    L1 -->|ToolInvocation| Sim
    Agents --- SBX
    CP --- SBX
    ART --- SBX
    style L0 fill:#f7f4ef,stroke:#d9c9a8
    style L1 fill:#f0ebe0,stroke:#d9c9a8
    style L2 fill:#eef3ee,stroke:#b9cbb9
    style L3 fill:#e9eef5,stroke:#a8bdd4
""")

D["01-iteration-loop"] = dict(
    title="Core Flow — Design Iteration Loop",
    subtitle="One active-learning round: target dossier → candidate design → evaluation → human gate → wet lab → analysis.",
    source="docs/flows.md",
    mermaid="""sequenceDiagram
    autonumber
    participant ORCH as Stage Graph (A)
    participant TRG as Target Agent
    participant DSG as Design Agent
    participant EVH as Evaluation Harness (C)
    participant SIM as In-silico (E)
    participant HUM as Scientist (L0)
    participant ASN as Assay Planning Agent
    participant LAB as Lab Execution (D)
    participant ANA as Analysis Agent
    ORCH->>TRG: StageTask(target-id)
    TRG-->>ORCH: Target dossier
    ORCH->>DSG: StageTask(hit-generation, dossier)
    DSG-->>ORCH: N candidates
    ORCH->>EVH: ToolInvocation(benchmark-batch)
    EVH-->>ORCH: top-K ranking
    ORCH->>SIM: ToolInvocation(in-silico-assay, top-K)
    SIM-->>ORCH: survivors
    ORCH->>HUM: review gate — pause branch
    HUM-->>ORCH: approve / reject / redirect
    ORCH->>ASN: StageTask(assay-planning, survivors)
    ASN-->>LAB: ProtocolSubmission
    LAB-->>ORCH: AssayResult(s)
    ORCH->>ANA: StageTask(analysis, results)
    ANA-->>ORCH: findings + next-round proposals
    Note over ORCH,DSG: proposals feed the next iteration (active learning loop)
""")

D["02-branching"] = dict(
    title="Experiment Branching — Fork / Snapshot",
    subtitle="AgentENV sandbox lifecycle mapped onto experiment trees: fork per hypothesis, snapshot at review gates, replay for audits.",
    source="docs/flows.md",
    mermaid="""stateDiagram-v2
    [*] --> DesignIteration: create sandbox
    DesignIteration --> ReviewGate: snapshot (pause-able state)
    ReviewGate --> Approved: scientist approves
    ReviewGate --> Rejected: scientist rejects
    Approved --> WetLabBranches: fork per hypothesis
    WetLabBranches --> BranchA: fork → assay plan variant 1
    WetLabBranches --> BranchB: fork → assay plan variant 2
    BranchA --> Results: assay results
    BranchB --> Results: assay results
    Results --> DesignIteration: analysis feeds next round
    Rejected --> DesignIteration: restore snapshot, redirect
""")

D["03-wetlab"] = dict(
    title="Wet-Lab Round Trip — Hardware in the Loop",
    subtitle="Protocol submission through safety review, instrument scheduling, execution, and telemetry → provenance.",
    source="docs/flows.md",
    mermaid="""sequenceDiagram
    autonumber
    participant ASN as Assay Planning Agent (sandbox)
    participant PC as Protocol Compiler
    participant SE as Safety Engine
    participant LSM as Lab State Manager
    participant IAL as IAL
    participant INST as Instrument
    participant TI as Telemetry Ingestor
    participant PS as Provenance Store
    ASN->>PC: ProtocolSubmission (abstract protocol)
    PC->>PC: compile → instrument scripts
    PC->>SE: validate
    alt policy violation
        SE-->>ASN: rejection (with reason) — agent revises
    else approved
        SE->>LSM: reserve reagents / instrument slot
        LSM->>IAL: enqueue run
        IAL->>INST: submit_protocol
        INST-->>IAL: telemetry + raw output
        IAL-->>TI: stream
        TI->>PS: normalized AssayResult + lineage
    end
""")

D["04-campaign"] = dict(
    title="Stage Pipeline — Campaign View",
    subtitle="Discovery campaign stages, with failure loops feeding earlier stages.",
    source="docs/flows.md",
    mermaid="""flowchart LR
    T["Target ID<br/>(triage)"] --> HG["Hit Generation<br/>(FM-driven design)"]
    HG --> LO["Lead Optimization<br/>(iterate loop)"]
    LO --> PC2["Preclinical<br/>(assays · ADMET · tox)"]
    PC2 --> TD["Trial Design<br/>(simulation)"]
    TD --> IND["IND package"]
    LO -.->|fails criteria| HG
    PC2 -.->|fails criteria| LO
    style IND fill:#eef3ee,stroke:#7fa87f
""")

D["05-tournament"] = dict(
    title="Hypothesis Tournament — Inside One Design Round",
    subtitle="Generate → Reflect → Rank → Evolve loop (pattern validated by Google's AI co-scientist), with fine-tuning flywheel.",
    source="docs/flows.md",
    mermaid="""flowchart TB
    G["Generate: N proposals<br/>(diverse seeds/prompts)"] --> R["Reflect: self + cross critique"]
    R --> RK["Rank: Elo tournament<br/>(Evaluation Harness + meta-reviewer)"]
    RK -->|"top-k survive"| E["Evolve: mutate/combine top-k"]
    E --> G
    RK -->|"round budget spent"| OUT["Ranked batch → next stage<br/>(assay / human gate)"]
    OUT -.->|confirmed AssayResults| FT["Fine-tuning Flywheel<br/>(Block C model variants)"]
    FT -.->|better models next round| G
    style FT fill:#f0ebe0,stroke:#c9a86a
    style OUT fill:#eef3ee,stroke:#7fa87f
""")

D["06-deployment"] = dict(
    title="Deployment View",
    subtitle="AgentENV nodes hosting agent sandboxes, wired to FM gateway, lab fabric, and shared storage.",
    source="docs/flows.md",
    mermaid="""flowchart TB
    subgraph Client["Client / Control"]
        GW["Gateway"]
        SCH["Scheduler"]
    end
    subgraph Node1["AgentENV Node 1"]
        S1["Server + Orchestrator"]
        SBX1["Agent sandboxes"]
        IAL1["IAL gateway"]
    end
    subgraph Node2["AgentENV Node 2"]
        S2["Server + Orchestrator"]
        SBX2["Agent sandboxes"]
    end
    subgraph Services["Shared Services"]
        FM["Bio FM Gateway (GPU)"]
        LAB["Lab fabric (robots/cloud labs)"]
        OSS["Object storage / registries"]
    end
    GW --> SCH
    SCH --> S1 & S2
    S1 --- SBX1
    S2 --- SBX2
    SBX1 --> FM
    SBX2 --> FM
    IAL1 --> LAB
    S1 & S2 --> OSS
""")

D["07-lab-pipeline"] = dict(
    title="Block D — Lab Execution Pipeline",
    subtitle="Agents only ever see the IAL contract; a safety engine sits outside any agent's trust boundary.",
    source="docs/architecture.md",
    mermaid="""flowchart LR
    A["Assay Planning Agent"] -->|ProtocolSubmission| PC["Protocol Compiler"]
    PC --> SE["Safety & Constraint Engine"]
    SE -->|reject| A
    SE -->|approved| Q["Lab State Manager<br/>(inventory · queue · custody)"]
    Q --> IAL["Instrument Abstraction Layer"]
    IAL --> V["Virtual Lab Simulator"]
    IAL --> H["Physical Instruments"]
    V --> T["Telemetry Ingestor"]
    H --> T
    T -->|AssayResult| Prov["Provenance Store"]
    style SE fill:#f7e8e4,stroke:#c98a7a
    style V fill:#eef3ee,stroke:#7fa87f
""")

def main():
    OUT.mkdir(exist_ok=True)
    for name, art in D.items():
        (OUT / f"{name}.html").write_text(TEMPLATE.format(**art))
    # index page
    cards = "\n".join(
        f'<a class="card" href="{n}.html"><span class="num">{i+1:02d}</span>'
        f'<span class="t">{a["title"]}</span>'
        f'<span class="s">{a["subtitle"]}</span></a>'
        for i, (n, a) in enumerate(D.items())
    )
    index = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Agentic Drug Discovery — Diagram Artifacts</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ margin:0; background:#faf9f5; color:#3d3929;
    font-family: ui-sans-serif, system-ui, -apple-system, sans-serif;
    display:flex; justify-content:center; }}
  main {{ width:min(980px, 96vw); padding:48px 0; }}
  h1 {{ font-size:26px; letter-spacing:-0.01em; margin:0 0 6px; }}
  p.sub {{ color:#8a7f6a; margin:0 0 36px; }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(280px,1fr)); gap:16px; }}
  .card {{ display:flex; flex-direction:column; gap:8px; background:#fff;
    border:1px solid #e8e2d6; border-radius:14px; padding:22px;
    text-decoration:none; color:inherit; transition:box-shadow .15s, transform .15s; }}
  .card:hover {{ box-shadow:0 6px 20px rgba(60,50,30,.1); transform:translateY(-2px); }}
  .num {{ font-size:11px; font-weight:700; color:#a1662f; letter-spacing:.08em; }}
  .t {{ font-weight:600; font-size:16px; }}
  .s {{ font-size:13px; color:#8a7f6a; line-height:1.5; }}
</style></head>
<body><main>
  <h1>Agentic Drug Discovery</h1>
  <p class="sub">Architecture diagram artifacts — {len(D)} diagrams</p>
  <nav class="grid">
{cards}
  </nav>
</main></body></html>
"""
    (OUT / "index.html").write_text(index)
    print(f"wrote {len(D) + 1} files to {OUT}")

if __name__ == "__main__":
    main()
