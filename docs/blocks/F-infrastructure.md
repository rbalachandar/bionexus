# Block F — Infrastructure (AgentENV, L3)

Exists today (see the AgentENV repo); this block is integration work only.

## What AgentENV provides

| Capability | Use in this platform |
|---|---|
| E2B-compatible HTTP API | create/pause/resume/delete agent sandboxes |
| Snapshot (diff) + fork | experiment branching, review-gate state freeze, audit replay |
| Template API | per-agent rootfs images pre-loaded with toolchains (RDKit, BioPython, FM clients) |
| Gateway + Scheduler (Go control plane) | multi-node scale-out, sandbox-to-node routing, HA query path |
| OverlayBD/ublk storage | fast rootfs/extra-drive materialization; memory snapshots |
| P2P artifact transport | large artifact distribution (structures, trajectories, mem layers) |
| Custom extension hooks | lab callbacks: stop-hook checkpoints agent state when a batch completes |
| Graceful restart persistence | paused sandboxes restored as Paused across server restarts |

## Integration points

1. **Orchestrator extension** — Stage Graph (A) drives sandboxes via the AgentENV
   API; gate pauses map 1:1 to sandbox pause.
2. **Agent images as templates** — build a rootfs template per agent role; publish
   via the snapshot/template pipeline.
3. **IAL as a sandbox sidecar** — the Instrument Abstraction Layer endpoint is
   injected into sandboxes (MMDS/custom-extension config) so agents get a stable
   tool endpoint without hardcoding.
4. **Scheduler strategies** — GPU-proximity hints for simulation-bound sandboxes;
   lab-fabric latency hints for wet-lab-heavy branches.

## Gaps to close

- [ ] Sandbox-level RBAC / per-tenant auth for multi-team use
- [ ] Cost accounting hooks (CPU/GPU-seconds per sandbox) feeding the Experiment Ledger
- [ ] Long-running sandbox watchdog policy (max runtime per stage)
