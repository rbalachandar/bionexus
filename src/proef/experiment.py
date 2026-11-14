"""ExperimentDefinition — the experiment as a scientific object, not a protocol.

A protocol describes how to execute a run. An experiment definition describes
what claim the run can support: the intervention, the biological system it is
applied to, delivery conditions, controls, readouts, and the denominators
required to interpret negative results.

Inspired by the "the cassette is the experiment" critique: a protocol can
complete successfully while producing an uninterpretable result, because the
interpretability of a result is decided by the experiment definition, not by
the pipetting.
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ClaimType(str, Enum):
    """What kind of causal claim the experiment is designed to support."""

    gain_of_function = "gain_of_function"
    loss_of_function = "loss_of_function"
    causal_modification = "causal_modification"
    interaction_capture = "interaction_capture"
    occupancy_vs_catalysis = "occupancy_vs_catalysis"
    turnover_or_pulse_cohort = "turnover_or_pulse_cohort"
    detection_or_pulldown = "detection_or_pulldown"
    correlation_only = "correlation_only"


class ReadoutCapability(str, Enum):
    """What the readout can actually distinguish."""

    edited_vs_unedited = "edited_vs_unedited"
    distinguishes_modified_from_mimetic = "distinguishes_modified_from_mimetic"
    size_only = "size_only"
    signal_present = "signal_present"
    quantified_fraction = "quantified_fraction"
    interaction_dependent = "interaction_dependent"
    orthogonal_to_modification = "orthogonal_to_modification"


class Reagent(BaseModel):
    name: str
    role: str = "reagent"                 # donor / acceptor / inhibitor / label ...
    sequence_or_structure: str | None = None
    concentration: str | None = None
    units: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Intervention(BaseModel):
    """The causal manipulation being applied to the biological system."""

    kind: str                             # e.g. protein_edit, degron_mutation, label_install
    target: str                           # protein / pathway / site under study
    site: str | None = None               # residue or region edited or targeted
    modification: str | None = None       # e.g. phosphotyrosine, crosslinker, label
    cassette: str | None = None           # donor / cassette description
    construct_size_kda: float | None = None
    requires_prior_genome_edit: bool = False
    mutations_introduced: list[str] = Field(default_factory=list)
    notes: str = ""


class BiologicalSystem(BaseModel):
    organism: str | None = None
    cell_line: str | None = None
    target_copy_number: float | None = None       # copies per cell, if known
    target_half_life_min: float | None = None     # protein turnover, if known
    preparation: str | None = None                # knock-in campaign, stable line, etc.
    notes: str = ""


class DeliveryConditions(BaseModel):
    method: str | None = None                     # electroporation, transfection...
    donor_concentration: str | None = None
    expected_intracellular_exposure: str | None = None
    timing: str | None = None                     # when the edit is applied
    per_cell_loading_measured: bool = False       # is delivery variance a covariate?
    notes: str = ""


class ReadoutSpec(BaseModel):
    assay: str
    capabilities: list[ReadoutCapability] = Field(default_factory=list)
    measures_edited_fraction: bool = False        # the missing denominator
    distinguishes_modified_from_mimetic: bool = False
    notes: str = ""


class ExperimentDefinition(BaseModel):
    """The complete scientific definition of an experiment.

    Execution details (protocol steps, device instructions) live in the
    ProtocolSubmission; this object carries everything needed to decide
    whether a successful run would support the intended claim.
    """

    experiment_id: str | None = None
    hypothesis_id: str | None = None
    scientific_question: str
    claim_type: ClaimType
    intervention: Intervention
    system: BiologicalSystem
    delivery: DeliveryConditions = Field(default_factory=DeliveryConditions)
    readout: ReadoutSpec
    controls: list[str] = Field(default_factory=list)
    denominators: list[str] = Field(default_factory=list)
    expected_intermediates: list[str] = Field(default_factory=list)
    kinetic_constraints: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def interpretability_warnings(self) -> list[str]:
        """Structural warnings about what this definition can and cannot show.

        These mirror the failure modes documented in the protein-editing
        literature: bulk readouts over partially edited populations, mimetics
        mistaken for authentic modifications, and turnover faster than the
        measurement window.
        """
        warnings: list[str] = []
        r = self.readout
        if self.claim_type in (ClaimType.loss_of_function,
                               ClaimType.causal_modification) and \
                not r.measures_edited_fraction:
            warnings.append(
                "loss-of-function or causal-modification claims on a bulk readout "
                "are uninterpretable without an edited-vs-unedited denominator"
            )
        if not r.distinguishes_modified_from_mimetic and \
                self.claim_type == ClaimType.causal_modification:
            warnings.append(
                "readout cannot distinguish an authentic modification from a "
                "mimetic; the causal claim is weakened to correlation"
            )
        if self.delivery.method and not self.delivery.per_cell_loading_measured:
            warnings.append(
                "delivery variance is unmeasured; per-cell editing extent may "
                "vary with loading, biasing time-resolved claims"
            )
        half_life = self.system.target_half_life_min
        if half_life is not None and half_life < 30:
            warnings.append(
                f"target half-life ({half_life} min) is close to the typical "
                "editing window; survivorship bias is expected in edited cohorts"
            )
        if self.intervention.requires_prior_genome_edit:
            warnings.append(
                "intervention requires a prior genome edit; any phenotype may "
                "reflect the acceptor-bearing state rather than the edit"
            )
        if self.intervention.construct_size_kda is not None and \
                self.intervention.construct_size_kda > 15:
            warnings.append(
                f"construct size {self.intervention.construct_size_kda} kDa is a "
                "significant fraction of typical target proteins; the acceptor-"
                "bearing state may perturb biology before the experiment starts"
            )
        if not self.controls:
            warnings.append("no controls declared")
        if self.claim_type == ClaimType.correlation_only:
            warnings.append("claim type is explicitly correlational")
        return warnings

    def interpretable_negative_result(self) -> bool:
        """Whether a null result would distinguish 'no effect' from 'not enough
        edited material to detect an effect'."""
        return self.readout.measures_edited_fraction and bool(self.denominators)
