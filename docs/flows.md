# Flows

## 1. Design Iteration Loop (primary flow)

```mermaid
sequenceDiagram
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
```

Every hop appends a `ProvenanceRecord`.

## 2. Sandbox Branching with Fork / Snapshot

AgentENV's fork/snapshot maps experiment tree structure onto sandbox lifecycle:

```mermaid
stateDiagram-v2
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
```

- **Fork** at the wet-lab step runs parallel assay hypotheses in isolated sandboxes.
- **Snapshot** at review gates means any branch can be resumed or replayed for audits
  (the full agent state — prompts, tools, context — is captured, not just outputs).

## 3. Wet-Lab Round Trip (hardware in the loop)

```mermaid
sequenceDiagram
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
```

Against the **Virtual Lab Simulator**, this identical flow runs with simulated
instruments — agents never know the difference.

## 4. Stage Pipeline (campaign view)

```mermaid
flowchart LR
    T["Target ID<br/>(triage)"] --> HG["Hit Generation<br/>(FM-driven design)"]
    HG --> LO["Lead Optimization<br/>(iterate 1–3 loop)"]
    LO --> PC2["Preclinical<br/>(assays · ADMET · tox)"]
    PC2 --> TD["Trial Design<br/>(simulation)"]
    TD --> IND["IND package"]
    LO -.->|fails criteria| HG
    PC2 -.->|fails criteria| LO
```

Each pipeline stage maps to a Stage Graph sub-DAG that runs the iteration loop
(flow 1) until stage-exit criteria are met or a human intervenes. Within each design
round, candidate generation runs as a **hypothesis tournament** (Generate → Reflect →
Rank → Evolve; see `docs/blocks/B-agents.md`) rather than a single pass — the pattern
validated by Google's AI co-scientist. Confirmed wet-lab results also feed the
**fine-tuning flywheel** in Block C, so each round's models are better than the last.

## 5. Hypothesis Tournament (inside one design round)

```mermaid
flowchart TB
    G["Generate: N proposals<br/>(diverse seeds/prompts)"] --> R["Reflect: self + cross critique"]
    R --> RK["Rank: Elo tournament<br/>(Evaluation Harness + meta-reviewer)"]
    RK -->|"top-k survive"| E["Evolve: mutate/combine top-k"]
    E --> G
    RK -->|"round budget spent"| OUT["Ranked batch → next stage<br/>(assay / human gate)"]
```

## 6. Deployment View

```mermaid
flowchart TB
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
```


## 7. Problem → Portfolio → Autonomous Loop (the full flow, as implemented)

```mermaid
flowchart TB
    P["ProblemStatement: objective + constraints + success_metric"] --> HP["Portfolio: N hypotheses proposed (rationale + prediction each)"]
    HP --> F["select_portfolio(score_fn, k): every accept/reject recorded with reason"]
    F --> H["Per selected hypothesis: proposed -> designed -> safety-gated test"]
    H --> LAB["lab/device performs (images on disk)"]
    LAB --> EV["device event -> agent notices -> analyzes"]
    EV --> V["verdict vs pre-registered criteria"]
    V -->|validated| C["confirmation assay auto-submitted (SafetyEngine-approved)"]
    C -->|next round| P
    V -.->|invalidated / inconclusive| P
```
