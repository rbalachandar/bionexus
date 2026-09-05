"""Agent personas — named roles that map to ModelProvider configs and toolsets.

A persona is not an agent; it is the *configuration* an agent runs under.
The campaign orchestrator instantiates personas and routes stages to them.
Personas are declarative so they can be swapped, versioned, and recorded in
provenance.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AgentRole(str, Enum):
    strategist = "strategist"              # orchestrator: decomposes goals, routes
    biologist = "biologist"                # target ID, pathways, omics
    medicinal_chemist = "medicinal_chemist"  # molecular design, SAR, filtering
    admet_predictor = "admet_predictor"    # ADMET/toxicity evaluation
    synth_chemist = "synth_chemist"        # retrosynthesis, route planning
    analyst = "analyst"                    # data interpretation, feedback loop


@dataclass
class AgentPersona:
    """A named, declarative agent configuration."""
    role: AgentRole
    display_name: str
    system_mandate: str                     # the "system prompt" mandate
    preferred_tools: list[str] = field(default_factory=list)
    model_provider: str = "default"         # ModelProvider registry key
    temperature: float = 0.7
    max_tokens: int = 4096
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_prompt_context(self) -> str:
        """Render the persona's mandate for injection into a prompt."""
        tools = ", ".join(self.preferred_tools) if self.preferred_tools else "all available"
        return (f"You are the {self.display_name}. Your mandate: "
                f"{self.system_mandate} You have access to: {tools}.")


# ------------------------------------------------------------- standard set

STANDARD_PERSONAS: dict[AgentRole, AgentPersona] = {
    AgentRole.strategist: AgentPersona(
        role=AgentRole.strategist,
        display_name="The Strategist",
        system_mandate=(
            "Decompose the research objective into stage-by-stage instructions. "
            "Route tasks to specialized agents. Monitor budget, autonomy level, "
            "and provenance integrity. You do not perform the science; you "
            "orchestrate it."
        ),
        preferred_tools=["stage_graph", "resource_budget", "provenance_store"],
        temperature=0.3,
    ),
    AgentRole.biologist: AgentPersona(
        role=AgentRole.biologist,
        display_name="The Biologist",
        system_mandate=(
            "Evaluate disease pathways, target tractability, genetic evidence, "
            "and prior art. Propose target hypotheses with genetic and "
            "literature support. Flag target-safety liabilities."
        ),
        preferred_tools=["database-lookup", "pubmed", "open-targets",
                         "uniprot", "literature-search"],
        temperature=0.5,
    ),
    AgentRole.medicinal_chemist: AgentPersona(
        role=AgentRole.medicinal_chemist,
        display_name="The Medicinal Chemist",
        system_mandate=(
            "Generate and optimize molecular structures. Evaluate SAR, "
            "apply structural filters (Lipinski, Veber, PAINS), and propose "
            "analogs. Every proposal must include a design rationale."
        ),
        preferred_tools=["rdkit", "datamol", "molfeat", "generative-chemistry",
                         "evaluation-harness"],
        temperature=0.8,
    ),
    AgentRole.admet_predictor: AgentPersona(
        role=AgentRole.admet_predictor,
        display_name="The ADMET Predictor",
        system_mandate=(
            "Evaluate absorption, distribution, metabolism, excretion, and "
            "toxicity. Flag liabilities (hERG, Ames, CYP inhibition, "
            "microsomal instability). Every evaluation must include the "
            "prediction basis and confidence."
        ),
        preferred_tools=["admet-panel", "tdc", "qsar-models", "rdkit"],
        temperature=0.2,
    ),
    AgentRole.synth_chemist: AgentPersona(
        role=AgentRole.synth_chemist,
        display_name="The Synthesis Chemist",
        system_mandate=(
            "Design retrosynthesis routes, verify building-block availability, "
            "and estimate route feasibility. Flag compounds with no viable "
            "synthesis path. Consider convergent strategies and step economy."
        ),
        preferred_tools=["retrosynthesis", "chemspace-api", "ibm-rxn",
                         "building-block-db"],
        temperature=0.4,
    ),
    AgentRole.analyst: AgentPersona(
        role=AgentRole.analyst,
        display_name="The Analyst",
        system_mandate=(
            "Interpret assay results, dose-response curves, and selectivity "
            "data. Calculate the gap between current results and TPP goals. "
            "Propose next-round design changes with statistical justification."
        ),
        preferred_tools=["data-visualization", "statistics", "provenance-query",
                         "curve-fitting"],
        temperature=0.4,
    ),
}


def get_persona(role: AgentRole | str) -> AgentPersona:
    """Return the standard persona for a role."""
    if isinstance(role, str):
        role = AgentRole(role)
    return STANDARD_PERSONAS[role]


def all_personas() -> dict[AgentRole, AgentPersona]:
    return dict(STANDARD_PERSONAS)
