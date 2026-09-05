"""Demo: the full autonomous agentic loop with async lab monitoring.

The agent proposes hypotheses, checks ADMET and synthesis, submits assays
through the safety gateway, does other work while waiting for results, checks
back, delivers verdicts, and iterates — all through the constrained tool-calling
loop.

The lab uses the simulator (instant results), but the async pattern is real:
submit_assay returns a run_id, and check_results polls for completion. With
real hardware, check_results would return "pending" until the instrument
finishes.

    .venv/bin/python examples/demo_agentic_full.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bionexus.adapters.lab.simulator import SimulatorLab
from bionexus.adapters.models.openai_compat import OpenAICompatProvider
from bionexus.adapters.store.sqlite import SqliteProvenanceStore
from bionexus.agentic import AgenticLoop, LoopConfig
from bionexus.core.hypothesis import Constraint, HypothesisTracker, ProblemStatement
from bionexus.core.interfaces import system_actor
from bionexus.core.safety import LabGateway, SafetyEngine
from bionexus.toolkit import AgentToolkit


def main() -> None:
    store = SqliteProvenanceStore()
    actor = system_actor("agentic-demo")
    lab = SimulatorLab(seed=42)
    safety = SafetyEngine()

    tracker = HypothesisTracker(store, actor)
    problem = tracker.define_problem(ProblemStatement(
        objective="Identify active HPK1 inhibitors from a compound series",
        constraints=[Constraint(name="potency", description="IC50 <= 20 uM",
                                kind="hard", limit=20.0, unit="uM")],
        success_metric="orthogonal confirmation of at least one active compound",
    ))

    gateway = LabGateway(lab, safety, store, actor)
    toolkit = AgentToolkit(
        lab_gateway=gateway, store=store, actor=actor,
        branch_id="agentic-full", tpp=None,
    )

    # ------------------------------------------------- tool schemas + executors
    schemas = AgentToolkit.schemas()
    executors = toolkit.executors()

    # ------------------------------------------------- system prompt
    system = """You are a medicinal chemistry research agent running a DMTA cycle.

Available workflow:
1. propose_hypothesis — record your hypothesis BEFORE testing
2. submit_assay — submit compounds for testing (safety gate will check)
3. check_results — poll for results (may need multiple calls)
4. record_verdict — record validated/invalidated based on evidence

Rules:
- Pre-register hypotheses BEFORE running experiments.
- Check synthesis feasibility before proposing expensive experiments.
- If a safety rejection occurs, revise and resubmit.
- Stop with 'DONE: <summary>' when you have enough evidence.

Be concise. Test 2-3 compounds maximum."""

    # ------------------------------------------------- initial task
    task = """Find active HPK1 inhibitors among: C-101, C-102, C-103.
Test them in a binding assay and report which ones are active (IC50 <= 20 uM).
Check synthesis feasibility first."""

    # ------------------------------------------------- the loop
    config = LoopConfig(
        max_turns=12,
        max_consecutive_errors=3,
        max_tool_result_chars=3000,
        system_prompt=system,
        tools=schemas,
    )
    provider = OpenAICompatProvider()  # offline stub — set base_url for real LLM
    loop = AgenticLoop(
        provider=provider,
        tools_schema=schemas,
        tool_executor=executors,
        config=config,
        envelope=__import__("bionexus.core.contracts", fromlist=["Envelope"]).Envelope(
            experiment_branch_id="agentic-full"),
    )

    print("=== Agentic loop starting ===")
    result = loop.run(task)
    print(f"\n=== Loop finished ===")
    print(f"  completed: {result.completed}")
    print(f"  reason: {result.reason}")
    print(f"  turns: {result.turns}")
    print(f"  tool_calls: {result.tool_calls}")
    if result.output:
        print(f"  output: {result.output[:200]}")

    # provenance
    recs = store.branch_records("agentic-full")
    print(f"  provenance records: {len(recs)}")
    for r in recs[-5:]:
        print(f"    {r.event_type.value}: {str(r.decision)[:60]}")


if __name__ == "__main__":
    main()
