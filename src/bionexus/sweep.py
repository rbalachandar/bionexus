"""Parallel campaign harness — fan one problem across candidate shards.

The ART campaign ran ~950 coordinated agent sessions; BioNexus's unit of
fan-out is the campaign. `run_sweep` partitions a candidate pool across
`fan` shards, runs one full gated campaign per shard (each with its own
problem branch, budget and verdict chain), then folds the shards into a
single roll-up record on the parent branch — the same tree-rollup pattern
problem trees use, so the workbench and reviewer read it unchanged.

Shards run sequentially today (deterministic, sqlite-safe); the
workbench's subprocess fan-out (api/launch.py) is the live parallel
counterpart and streams per-shard via branch announcements.
"""
from __future__ import annotations

from typing import Any, Callable

from bionexus.core.contracts import Envelope, EventType
from bionexus.core.hypothesis import Constraint, ProblemStatement
from bionexus.core.interfaces import ProvenanceStore, record_for, system_actor


def run_sweep(problem: ProblemStatement, candidates: list[str],
              lab_factory: Callable[[], Any], store: ProvenanceStore,
              *, fan: int = 3, k_per_shard: int = 2, threshold: float,
              unit: str = "uM", metric: str = "potency", seed: int = 0,
              rounds: int = 1, notify: Callable[[str], None] | None = None,
              ) -> dict:
    """Partition `candidates` across `fan` shard campaigns and roll the
    verdicts up. Returns {shards, verdicts, tally, best} — verdicts keyed
    by candidate, tally by status, best = confirmed/validated candidates."""
    from bionexus.autoloop import CampaignConfig, run_campaign

    say = notify or (lambda m: None)
    base = problem.problem_id or "sweep"
    constraint = Constraint(name=metric, kind="hard", limit=threshold,
                            unit=unit,
                            description=f"{metric} <= {threshold:g} {unit}")
    shards: list[list[str]] = [[] for _ in range(max(1, fan))]
    for i, c in enumerate(candidates):
        shards[i % len(shards)].append(c)

    verdicts: dict[str, str] = {}
    shard_summaries = []
    for i, shard in enumerate(shards):
        if not shard:
            continue
        shard_problem = ProblemStatement(
            objective=problem.objective,
            problem_id=f"{base}-sw{i}",
            constraints=[constraint],
            success_metric=problem.success_metric)
        specs = [{"statement": f"{c} {metric} <= {threshold:g} {unit}",
                  "candidate": c, "assay_type": "binding",
                  "predicted": f"<= {threshold:g}", "rationale": "sweep"}
                 for c in shard]
        say(f"shard {i}: {len(shard)} candidates, k={k_per_shard}")
        report = run_campaign(
            CampaignConfig(problem=shard_problem, hypotheses=specs,
                           k=k_per_shard, rounds=rounds, autonomy="act",
                           inbox=f".data/inbox-sweep-{base}-sw{i}",
                           poll_secs=0.05),
            lab_factory(), store, notify=say)
        verdicts.update(report.verdicts)
        shard_summaries.append({"shard": i, "problem_id": shard_problem.problem_id,
                                "candidates": shard,
                                "verdicts": dict(report.verdicts)})

    tally: dict[str, int] = {}
    for v in verdicts.values():
        tally[v] = tally.get(v, 0) + 1
    best = sorted(c for c, v in verdicts.items()
                  if v in ("confirmed", "validated"))
    store.append(record_for(
        Envelope(experiment_branch_id=f"problem/{base}"),
        EventType.gate_decision,
        system_actor("sweep"),
        decision={"kind": "sweep-rollup", "fan": fan,
                  "shards": shard_summaries, "tally": tally,
                  "best": best}))
    say(f"SWEEP ROLL-UP: {tally} · best: {best or '—'}")
    return {"shards": shard_summaries, "verdicts": verdicts,
            "tally": tally, "best": best}
