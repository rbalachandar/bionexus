"""AgentToolkit — wires BioNexus capabilities as tools for the agentic loop.

Each tool is a named function with an Anthropic-compatible schema. The toolkit
connects to the real BioNexus layer: LabGateway (safety), ADMET panel,
retrosynthesis, provenance store, and TPP. Agents cannot bypass these — the
gateway is the only path to the lab.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from bionexus.core.contracts import Envelope, EventType, ProtocolOp, \
    ProtocolStep, ProtocolSubmission, ReagentSpec, SampleKind, SampleSpec
from bionexus.core.interfaces import record_for

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "rank_variants",
        "description": "Score and rank candidate genetic variants by "
                       "AlphaGenome Atlas Variant Impact (AVI) score with "
                       "feature attributions (splicing, chromatin, expression, "
                       "conservation, protein impact). Input: list of "
                       "{chromosome, position, ref, alt}.",
        "input_schema": {
            "type": "object",
            "properties": {
                "variants": {
                    "type": "array",
                    "items": {"type": "object",
                              "properties": {"chromosome": {"type": "string"},
                                             "position": {"type": "integer"},
                                             "ref": {"type": "string"},
                                             "alt": {"type": "string"}},
                              "required": ["chromosome", "position", "ref", "alt"]},
                },
            },
            "required": ["variants"],
        },
    },
    {
        "name": "predict_admet",
        "description": "Predict ADMET properties (MW, LogP, TPSA, HBD/HBA, "
                       "rotatable bonds, Lipinski/Veber/PAINS) for a SMILES string.",
        "input_schema": {
            "type": "object",
            "properties": {"smiles": {"type": "string"}},
            "required": ["smiles"],
        },
    },
    {
        "name": "check_synthesis",
        "description": "Makeability gate for a SMILES string: can we make "
                       "this, how many routes, lead-time (days) and cost "
                       "(USD)? Modeled from named-reaction rules; numbers "
                       "are simulated and stamped. Blocks campaigns at Make.",
        "input_schema": {
            "type": "object",
            "properties": {"smiles": {"type": "string"}},
            "required": ["smiles"],
        },
    },
    {
        "name": "propose_hypothesis",
        "description": "Record a falsifiable hypothesis into the provenance chain. "
                       "Must be called BEFORE the corresponding experiment.",
        "input_schema": {
            "type": "object",
            "properties": {
                "statement": {"type": "string"},
                "candidate": {"type": "string"},
                "assay_type": {"type": "string"},
                "predicted": {"type": "string"},
            },
            "required": ["statement", "candidate", "assay_type", "predicted"],
        },
    },
    {
        "name": "submit_assay",
        "description": "Submit compounds for potency testing through the safety "
                       "gate. Returns a run_id; call check_results later. "
                       "In gate autonomy, submission waits for operator approval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "compounds": {"type": "array", "items": {"type": "string"}},
                "assay_type": {"type": "string",
                               "enum": ["binding", "enzymatic", "cytotoxicity",
                                        "counterscreen"]},
                "concentrations": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["compounds", "assay_type"],
        },
    },
    {
        "name": "check_results",
        "description": "Check if results are ready for a previously submitted "
                       "run. Returns measurements if done, or status if pending.",
        "input_schema": {
            "type": "object",
            "properties": {"run_id": {"type": "string"}},
            "required": ["run_id"],
        },
    },
    {
        "name": "record_verdict",
        "description": "Record a validated/invalidated/inconclusive verdict for "
                       "a hypothesis based on evidence. The event type follows "
                       "the verdict, and an inconclusive verdict is recorded "
                       "as such — never silently as an invalidation.",
        "input_schema": {
            "type": "object",
            "properties": {
                "candidate": {"type": "string"},
                "verdict": {"type": "string",
                            "enum": ["validated", "confirmed", "invalidated",
                                     "refuted", "inconclusive"]},
                "evidence": {"type": "string"},
            },
            "required": ["candidate", "verdict", "evidence"],
        },
    },
    {
        "name": "query_tpp",
        "description": "Query the current TPP criteria for a phase. Returns the "
                       "criteria list so you know what thresholds to target.",
        "input_schema": {
            "type": "object",
            "properties": {"phase": {"type": "string",
                                     "enum": ["hit", "lead", "candidate"]}},
        },
    },
]


class AgentToolkit:
    """Builds tool executors bound to live BioNexus services.

    Usage:
        toolkit = AgentToolkit(lab=SimulatorLab(), store=store, actor=actor)
        loop = AgenticLoop(provider=..., tools_schema=AgentToolkit.schemas(),
                           tool_executor=toolkit.executors)
    """

    def __init__(self, lab_gateway, store, actor, tpp=None,
                 branch_id: str = "agentic-toolkit"):
        self.gateway = lab_gateway
        self.store = store
        self.actor = actor
        self.tpp = tpp
        self.branch = branch_id
        self._runs: dict[str, dict] = {}
        self._admet = None
        self._retro = None
        self._variant_scorer = None

    @property
    def admet(self):
        if self._admet is None:
            from bionexus.adapters.admet import get_admet_predictor
            self._admet = get_admet_predictor()
        return self._admet

    @property
    def variant_scorer(self):
        if self._variant_scorer is None:
            from bionexus.adapters.genomics.alphagenome import get_variant_scorer
            self._variant_scorer = get_variant_scorer()
        return self._variant_scorer

    @property
    def retro(self):
        if self._retro is None:
            from bionexus.adapters.retrosynthesis import \
                get_retrosynthesis_adapter
            self._retro = get_retrosynthesis_adapter("rule-based")
        return self._retro

    def executors(self) -> dict[str, Callable]:
        return {
            "predict_admet": self._tool_admet,
            "check_synthesis": self._tool_synthesis,
            "propose_hypothesis": self._tool_hypothesis,
            "submit_assay": self._tool_submit,
            "check_results": self._tool_results,
            "record_verdict": self._tool_verdict,
            "query_tpp": self._tool_tpp,
            "rank_variants": self._tool_rank_variants,
        }

    @staticmethod
    def schemas() -> list[dict]:
        return TOOL_SCHEMAS

    # ---- implementations ------------------------------------------------

    def _tool_rank_variants(self, variants: list[dict]) -> dict:
        """variants: [{chromosome, position, ref, alt}, ...] — ranked by
        AlphaGenome Atlas AVI score (real API when configured, else seeded
        simulation flagged as such)."""
        scored = self.variant_scorer.rank(variants)
        return {"source": scored[0].source if scored else "none",
                "ranked": [v.summary() for v in scored]}

    def _tool_admet(self, smiles: str) -> dict:
        out = self.admet.predict(smiles).summary()
        from bionexus.interpret import explain_admet
        out["why"] = explain_admet(out)   # attribution beside every prediction
        return out

    def _tool_synthesis(self, smiles: str) -> dict:
        plans = self.retro.plan_routes(smiles)
        viable = [p for p in plans if p.feasible]
        best = max(plans, key=lambda p: (p.feasible, p.yield_pct))
        return {"smiles": smiles, "makeable": bool(viable),
                "num_routes": len(plans), "viable_routes": len(viable),
                "best_route": best.summary(),
                "routes": [p.summary() for p in plans],
                "answer": (f"{'can make' if viable else 'CANNOT MAKE at acceptable yield/lead-time'}"
                           f" via {len(viable)}/{len(plans)} modeled route(s): "
                           f"{best.lead_time_days} d, ~${best.cost_usd:.0f}"),
                "data_origin": best.data_origin}

    def _tool_hypothesis(self, statement: str, candidate: str,
                         assay_type: str, predicted: str) -> dict:
        from bionexus.core.hypothesis import HypothesisTracker
        tracker = HypothesisTracker(self.store, self.actor)
        h = tracker.propose(statement=statement, candidate=candidate,
                            assay_type=assay_type, predicted=predicted)
        return {"hypothesis_id": h.hypothesis_id, "status": "recorded"}

    def _tool_submit(self, compounds: list[str], assay_type: str,
                     concentrations: list[str] | None = None) -> dict:
        concs = concentrations or ["0.5uM", "2uM", "10uM", "40uM"]
        protocol = ProtocolSubmission(
            envelope=Envelope(experiment_branch_id=self.branch),
            title=f"agent assay ({assay_type})",
            assay_type=assay_type,
            steps=[ProtocolStep(seq=1, op=ProtocolOp.dispense, params={"volume_ul": 50})],
            samples=[SampleSpec(sample_id=c, kind=SampleKind.compound, concentration=cc)
                     for c in compounds for cc in concs]
            + [SampleSpec(sample_id="ctrl-neg", kind=SampleKind.buffer, concentration="10uM")],
            reagents=[ReagentSpec(name="assay-buffer", amount="5 mL", bsl_level=1)],
        )
        run_id, rejection = self.gateway.submit(protocol)
        if rejection:
            return {"status": "rejected", "reason": rejection}
        self._runs[run_id] = protocol
        return {"run_id": run_id, "status": "submitted",
                "compounds": compounds, "next": "call check_results when ready"}

    def _tool_results(self, run_id: str) -> dict:
        if run_id not in self._runs:
            return {"status": "unknown_run", "run_id": run_id}
        protocol = self._runs[run_id]
        result = self.gateway.results(
            Envelope(experiment_branch_id=self.branch), run_id)
        measurements = [
            {"sample_id": m.sample_id, "value": m.value, "unit": m.unit}
            for m in result.measurements
        ]
        return {"run_id": run_id, "status": result.status.value,
                "z_prime": result.qc.z_prime, "measurements": measurements}

    def _tool_verdict(self, candidate: str, verdict: str, evidence: str) -> dict:
        from bionexus.core.contracts import EventType
        event = {
            "validated": EventType.hypothesis_validated,
            "confirmed": EventType.hypothesis_validated,
            "invalidated": EventType.hypothesis_invalidated,
            "refuted": EventType.hypothesis_invalidated,
            "inconclusive": EventType.hypothesis_inconclusive,
        }.get(verdict, EventType.hypothesis_tested)
        self.store.append(record_for(
            Envelope(experiment_branch_id=self.branch),
            event,
            self.actor,
            decision={"candidate": candidate, "verdict": verdict,
                      "evidence": evidence[:500],
                      "declared_by": "agent (free-text evidence; not a "
                                     "tool-verified fit)"},
        ))
        return {"recorded": True, "candidate": candidate, "verdict": verdict}

    def _tool_tpp(self, phase: str = "hit") -> dict:
        if not self.tpp:
            return {"error": "no TPP configured"}
        from bionexus.tpp import CriterionPhase
        criteria = self.tpp.criteria_for_phase(CriterionPhase(phase))
        return [{"name": c.name, "threshold": c.threshold,
                 "direction": c.direction, "unit": c.unit,
                 "required": c.required} for c in criteria]
