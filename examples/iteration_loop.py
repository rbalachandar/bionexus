"""End-to-end design round on the simulator (P8: simulator-first CI).

Runs the iteration loop with the stub model: generate -> tournament -> gate ->
protocol (through the safety gateway) -> virtual lab -> analysis proposal.
Needs no network and no model server:

    python examples/iteration_loop.py
"""
from __future__ import annotations

import json

from bionexus.adapters.lab.simulator import SimulatorLab
from bionexus.adapters.models.openai_compat import OpenAICompatProvider
from bionexus.adapters.sandbox.local import LocalSandbox
from bionexus.adapters.store.sqlite import SqliteProvenanceStore
from bionexus.core.contracts import (
    Actor,
    Envelope,
    ProtocolOp,
    ProtocolStep,
    ProtocolSubmission,
    ReagentSpec,
    SampleKind,
    SampleSpec,
    StageName,
    StageTask,
    ToolInvocation,
)
from bionexus.core.interfaces import system_actor
from bionexus.core.registry import Registry
from bionexus.core.safety import ForbiddenComboRule, LabGateway, SafetyEngine
from bionexus.core.workflow import HypothesisTournament, Stage, StageGraph, TournamentConfig


def main() -> None:
    branch = "branch-root"
    store = SqliteProvenanceStore("bionexus.db")
    actor = system_actor("example")
    model = OpenAICompatProvider()  # stub mode: deterministic, offline
    registry = Registry()
    registry.register_model(model, default=True)

    # safety: allow BSL-1/2 but forbid mixing acid + bleach analogues
    safety = SafetyEngine(rules=[ForbiddenComboRule([("acid*", "*hypochlorite*")])])
    lab = LabGateway(SimulatorLab(seed=42), safety, store, actor)

    # 1) sandbox branch + tournament over candidate molecules
    sandbox = LocalSandbox(branch, store=store, actor=actor)
    tourn = HypothesisTournament(
        registry.model,
        TournamentConfig(population=6, survivors=3, waves=2),
    )
    envelope = Envelope(experiment_branch_id=branch)
    invocation = ToolInvocation(
        envelope=envelope,
        tool="c.fm.generate_molecules",
        args={"target": "KRAS_G12C"},
    )
    gen = registry.model.generate(invocation, "generate candidates for KRAS_G12C", n=6)
    candidates = json.loads(gen.output["text"])
    ranked = tourn.run(
        branch,
        seed_context={"target": "KRAS_G12C"},
        generate_fn=lambda ctx: candidates,
        score_fn=lambda p: int(p["smiles"].count("C")) * 0.1,  # stand-in for eval harness
    )
    print(f"tournament survivors: {[c['smiles'] for c in ranked]}")
    top = ranked[0]["smiles"]

    # 2) assay the top candidate through the safety gateway + virtual lab
    protocol = ProtocolSubmission(
        envelope=envelope,
        title=f"binding assay for {top}",
        assay_type="binding",
        steps=[ProtocolStep(seq=1, op=ProtocolOp.dispense, params={"volume_ul": 50})],
        samples=[SampleSpec(sample_id=top, kind=SampleKind.compound)],
        reagents=[ReagentSpec(name="buffer-A", amount="10 mL", bsl_level=1)],
        controls=["positive", "negative"],
    )
    run_id, rejection = lab.submit(protocol)
    assert run_id, f"safety rejected: {rejection}"
    result = lab.results(envelope, run_id)
    print(f"run {run_id}: {len(result.measurements)} measurement(s), qc={result.qc}")

    # 3) fork a branch to try a riskier protocol (safety should block it)
    child = sandbox.fork()
    risky = protocol.model_copy(deep=True)
    risky.envelope = Envelope(experiment_branch_id=child.branch_id)
    risky.reagents.append(ReagentSpec(name="acid chloride", amount="1 mL", bsl_level=1))
    risky.reagents.append(ReagentSpec(name="sodium hypochlorite", amount="1 mL", bsl_level=1))
    run_id2, rejection2 = lab.submit(risky)
    assert run_id2 is None and rejection2, "expected safety rejection"
    print(f"fork {child.branch_id}: safety blocked risky protocol -> {rejection2}")

    # 4) provenance: the whole round is replayable
    records = store.branch_records(branch)
    print(f"provenance records in {branch}: {len(records)} (hash-chained)")
    for rec in records[-2:]:
        print(f"  {rec.event_type.value}: {rec.decision}")


if __name__ == "__main__":
    main()
