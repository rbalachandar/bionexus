"""Demo: the agent decides the hypothesis structure itself.

Given ONLY the problem statement + a candidate library, the LLM proposes:
how many mechanistic families, what each claims, how many variants per family,
and which variables to tune. The flow then runs autonomously (simulated lab).

    BIONEXUS_LLM_* (or ANTHROPIC_*) env for a real model.
    .venv/bin/python examples/demo_agent_hypotheses.py
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, "src")

from bionexus.adapters.lab.simulator import SimulatorLab
from bionexus.adapters.models.openai_compat import OpenAICompatProvider
from bionexus.adapters.store.sqlite import SqliteProvenanceStore
from bionexus.autoloop import CampaignConfig, run_campaign
from bionexus.core.hypothesis import Constraint, ProblemStatement
from bionexus.core.interfaces import system_actor


class _ScriptedHypothesisModel:
    """Offline stand-in that emits a realistic families JSON (CI-friendly)."""
    name = "scripted"
    model_version = "scripted-1"

    def generate(self, invocation, prompt, **kw):
        from bionexus.core.contracts import ToolResult
        text = json.dumps({"families": [
            {"family": "covalent-warhead",
             "parent_statement": "A covalent warhead targeting Cys12 inhibits KRAS_G12C",
             "kind": "mechanistic", "rationale": "switch-II pocket precedent",
             "confidence": 0.85,
             "variables": ["warhead electronics", "linker length"],
             "variants": [
                 {"statement": "C-101 binds with IC50 <= 20 uM", "candidate": "C-101",
                  "assay_type": "binding", "predicted": "IC50 <= 20",
                  "predicted_value": 20.0,
                  "rationale": "acrylamide warhead",
                  "variables": {"warhead": "acrylamide"}},
                 {"statement": "C-103 binds with IC50 <= 15 uM", "candidate": "C-103",
                  "assay_type": "binding", "predicted": "IC50 <= 15",
                  "predicted_value": 15.0,
                  "rationale": "extra hydrophobe tunes occupancy",
                  "variables": {"warhead": "acrylamide", "linker": "+1C"}}]},
            {"family": "noncovalent-scaffold",
             "parent_statement": "A non-covalent scaffold reaches sub-20uM",
             "kind": "mechanistic", "rationale": "developability",
             "confidence": 0.7,
             "variables": ["scaffold polarity"],
             "variants": [
                 {"statement": "C-102 binds with IC50 <= 20 uM", "candidate": "C-102",
                  "assay_type": "binding", "predicted": "IC50 <= 20",
                  "predicted_value": 20.0, "rationale": "scaffold hop",
                  "variables": {"polarity": "high"}}]},
            {"family": "artifact-explanation",
             "parent_statement": "C-104 signal is assay interference",
             "kind": "artifact-explanation", "rationale": "fluorescent aggregator",
             "confidence": 0.6, "variables": [],
             "variants": [
                 {"statement": "C-104 shows counterscreen interference",
                  "candidate": "C-104", "assay_type": "counterscreen",
                  "predicted": "interference", "rationale": "aggregator-like",
                  "variables": {}}]},
        ]})
        return ToolResult(envelope=invocation.envelope.model_copy(),
                          invocation_id=invocation.invocation_id,
                          status="succeeded", output={"text": text},
                          model_version=self.model_version)

    def predict(self, invocation, kind, payload):
        raise NotImplementedError


def main() -> None:
    if os.environ.get("BIONEXUS_LLM_TOKEN") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        from bionexus.adapters.models.anthropic_provider import AnthropicProvider
        model = AnthropicProvider()
        print("[demo] using real LLM:", model.model_version)
    else:
        model = _ScriptedHypothesisModel()
        print("[demo] no LLM env — using scripted offline hypothesis model")

    problem = ProblemStatement(
        objective="Find a confirmed sub-20uM KRAS_G12C binder for lead development",
        context="Post-screen hit list C-101..C-104; binding assay validated at "
                "4 concentrations; counterscreen available. C-104 is fluorescent "
                "and aggregator-like.",
        constraints=[
            Constraint(name="potency", description="IC50 <= 20 uM", kind="hard",
                       limit=20.0, unit="uM"),
            Constraint(name="budget", description="max 2 hypotheses to wet-lab",
                       kind="hard"),
        ],
        success_metric="orthogonal confirmation",
    )
    candidates = [
        {"id": "C-101", "note": "covalent warhead, acrylamide"},
        {"id": "C-102", "note": "non-covalent scaffold hop"},
        {"id": "C-103", "note": "C-101 analog, extra hydrophobe"},
        {"id": "C-104", "note": "fluorescent, aggregator-like"},
    ]

    cfg = CampaignConfig(
        problem=problem,
        hypothesis_source="agent",   # the model decides families + variants
        model=model,
        candidates=candidates,
        max_families=3,
        max_variants_per_family=2,
        k=2,
        autonomy="act",
        inbox=".data/inbox-agent",
        actor_name="agent-hypotheses-demo",
    )
    report = run_campaign(cfg, SimulatorLab(seed=42), SqliteProvenanceStore())

    print(f"\n[campaign] problem {report.problem_id}")
    print(f"[campaign] selected: {report.selected}")
    print(f"[campaign] verdicts: {report.verdicts}")
    print("[campaign] the agent chose the families, the variants, "
          "and the tuned variables — from the problem alone.")


if __name__ == "__main__":
    main()
