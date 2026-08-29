"""Stage graph + hypothesis tournament engine (P2: consumes only core interfaces).

The stage graph is deliberately boring: a list of Stages run in order, each a
callable StageTask -> StageResult, with optional human gates between stages and
round-based looping for the active-learning cycle. The tournament runs
generate->reflect->rank->evolve waves inside a stage.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from bionexus.core.contracts import (
    Actor,
    Envelope,
    EventType,
    GateType,
    StageName,
    StageResult,
    StageStatus,
    StageTask,
)
from bionexus.core.interfaces import ProvenanceStore, record_for


@dataclass
class Gate:
    """A human review point. `approver` returns True/False/redirect-dict."""
    gate_type: GateType
    approver: Callable[[StageResult], bool]


@dataclass
class Stage:
    name: StageName
    run: Callable[[StageTask], StageResult]
    gate: Gate | None = None
    max_rounds: int = 1  # >1 enables the active-learning loop


@dataclass
class StageGraph:
    """Ordered stages; each stage may loop rounds. Provenance on every transition."""
    stages: list[Stage]
    store: ProvenanceStore
    actor: Actor
    branch_id: str
    results: dict[str, list[StageResult]] = field(default_factory=dict)

    def execute(self, context: dict[str, Any] | None = None) -> dict[str, Any]:
        context = context or {}
        carry: dict[str, Any] = {}
        for stage in self.stages:
            carry = self._run_stage(stage, context, carry)
        return carry

    def _run_stage(self, stage: Stage, context: dict[str, Any], carry: dict[str, Any]) -> dict[str, Any]:
        out: list[StageResult] = []
        for round_no in range(1, stage.max_rounds + 1):
            task = StageTask(
                envelope=Envelope(experiment_branch_id=self.branch_id),
                stage=stage.name,
                attempt=round_no,
                context={**context, **carry, "round": round_no},
            )
            result = stage.run(task)
            out.append(result)
            self.store.append(
                record_for(
                    task.envelope,
                    EventType.stage_transition,
                    self.actor,
                    decision={
                        "stage": stage.name.value,
                        "round": round_no,
                        "status": result.status.value,
                    },
                )
            )
            if result.status in (StageStatus.failed_terminal, StageStatus.needs_human):
                break
            carry = {
                "artifacts": [a.model_dump() for a in result.output_artifacts],
                "proposals": [p.model_dump() for p in result.next_round_proposals],
            }
            if round_no < stage.max_rounds:
                # feed proposals back as next-round context (active learning)
                context = {**context, "prev_proposals": carry["proposals"]}
        self.results[stage.name.value] = out

        if stage.gate is not None:
            last = out[-1]
            approved = stage.gate.approver(last)
            self.store.append(
                record_for(
                    Envelope(experiment_branch_id=self.branch_id),
                    EventType.gate_decision,
                    self.actor,
                    decision={
                        "gate": stage.gate.gate_type.value,
                        "approved": approved,
                    },
                )
            )
            if not approved:
                carry["gate_rejected"] = stage.gate.gate_type.value
        return carry


# ------------------------------------------------------------- tournament

@dataclass
class TournamentConfig:
    population: int = 8          # proposals per wave
    survivors: int = 3           # top-k carried into the next wave
    waves: int = 2               # generation rounds
    score_fn: Callable[[dict[str, Any]], float] = lambda p: p.get("score", 0.0)


class HypothesisTournament:
    """Generate -> Reflect -> Rank -> Evolve (P2: only needs a ModelProvider +
    optional reflection/ranking callables). Deterministic given deterministic
    inputs; scores come from the Evaluation side (user-supplied or BioTools)."""

    def __init__(
        self,
        model: Any,
        config: TournamentConfig | None = None,
        reflect_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        evolve_fn: Callable[[list[dict[str, Any]]], list[dict[str, Any]]] | None = None,
    ):
        self.model = model
        self.cfg = config or TournamentConfig()
        self.reflect_fn = reflect_fn
        self.evolve_fn = evolve_fn

    def run(
        self,
        branch_id: str,
        seed_context: dict[str, Any],
        generate_fn: Callable[[dict[str, Any]], list[dict[str, Any]]],
        score_fn: Callable[[dict[str, Any]], float],
    ) -> list[dict[str, Any]]:
        """Returns ranked survivors (best first), scored by `score_fn`."""
        population = generate_fn(seed_context)[: self.cfg.population]
        for wave in range(self.cfg.waves):
            if self.reflect_fn:
                population = [self.reflect_fn(p) for p in population]
            population.sort(key=score_fn, reverse=True)
            survivors = population[: self.cfg.survivors]
            if wave < self.cfg.waves - 1:
                if self.evolve_fn:
                    population = self.evolve_fn(survivors)
                else:
                    population = survivors  # simple truncation evolve
            else:
                population = survivors
        return sorted(population, key=score_fn, reverse=True)
