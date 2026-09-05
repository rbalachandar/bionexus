"""Demo: ExperimentDefinition + ExperimentReadinessReview.

Two experiments targeting the same hypothesis:

  A. A well-defined causal experiment: authentic modification installed on
     endogenous protein, edited-fraction denominator measured, controls
     declared, turnover compatible.

  B. A weakly-defined variant: bulk Western readout (cannot separate edited
     from unedited protein), phosphomimetic surrogate, no denominator,
     no controls, short-lived target.

Experiment A is READY. Experiment B is BLOCKED — not because the protocol is
invalid, but because its result would be uninterpretable even if it succeeded.

    .venv/bin/python examples/demo_experiment_definition.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bionexus.adapters.store.sqlite import SqliteProvenanceStore
from bionexus.core.hypothesis import (
    Constraint, HypothesisTracker, ProblemStatement,
)
from bionexus.core.interfaces import system_actor
from bionexus.experiment import (
    BiologicalSystem, ClaimType, DeliveryConditions, ExperimentDefinition,
    Intervention, ReadoutCapability, ReadoutSpec,
)
from bionexus.readiness import review_and_record


def main() -> None:
    store = SqliteProvenanceStore()
    actor = system_actor("experiment-definition-demo")
    tracker = HypothesisTracker(store, actor)
    problem = tracker.define_problem(ProblemStatement(
        objective="Determine whether phosphorylation at S62 is causal for "
                  "c-Myc degradation",
        constraints=[Constraint(name="denominator",
                                description="edited fraction must be measured",
                                kind="hard")],
        success_metric="causal attribution of S62 phosphorylation to turnover",
    ))

    # --------------------------------------------------- Experiment A: strong
    exp_a = ExperimentDefinition(
        experiment_id="exp-A",
        hypothesis_id=None,
        scientific_question=(
            "Does authentic phosphoserine at S62, installed on endogenous "
            "c-Myc, change protein half-life?"
        ),
        claim_type=ClaimType.causal_modification,
        intervention=Intervention(
            kind="protein_edit",
            target="c-Myc",
            site="S62",
            modification="phosphoserine",
            cassette="split-intein acceptor + synthetic donor",
            cassette_size_kda=12.0,
            requires_prior_genome_edit=True,
            mutations_introduced=[],
        ),
        system=BiologicalSystem(
            organism="Homo sapiens",
            cell_line="HEK293T",
            target_copy_number=50000,
            target_half_life_min=120,
            preparation="CRISPR knock-in of acceptor cassette",
        ),
        delivery=DeliveryConditions(
            method="electroporation",
            donor_concentration="50 uM",
            expected_intracellular_exposure=">= 5 uM (2% capture efficiency)",
            timing="edited within 10 min of electroporation",
            per_cell_loading_measured=True,
        ),
        readout=ReadoutSpec(
            assay="ratiometric LC-MS/MS on splice-junction peptides",
            capabilities=[
                ReadoutCapability.edited_vs_unedited,
                ReadoutCapability.quantified_fraction,
                ReadoutCapability.distinguishes_modified_from_mimetic,
                ReadoutCapability.orthogonal_to_modification,
            ],
            measures_edited_fraction=True,
            distinguishes_modified_from_mimetic=True,
        ),
        controls=[
            "catalytically dead donor (C1A/N37A/S+A)",
            "no-donor electroporation control",
            "wild-type unedited c-Myc half-life baseline",
        ],
        denominators=[
            "edited / total c-Myc by ratiometric proteomics",
            "per-cell donor loading by fluorescence",
        ],
        expected_intermediates=[
            "hemi-spliced intermediate if intein kinetics are mismatched",
        ],
    )

    # --------------------------------------------------- Experiment B: weak
    exp_b = exp_a.model_copy(deep=True)
    exp_b.experiment_id = "exp-B"
    exp_b.scientific_question = (
        "Does c-Myc carrying a phosphomimetic S62E substitution and an "
        "internal tag degrade differently?"
    )
    exp_b.claim_type = ClaimType.causal_modification
    exp_b.intervention.mutations_introduced = [
        "A44G", "P45Y", "S62E (mimetic)", "P72N",
    ]
    exp_b.readout = exp_b.readout.model_copy(deep=True)
    exp_b.readout.assay = "anti-tag Western blot of bulk lysate"
    exp_b.readout.capabilities = []          # size-only, no fraction, no mimetic discrimination
    exp_b.readout.measures_edited_fraction = False
    exp_b.readout.distinguishes_modified_from_mimetic = False
    exp_b.controls = []                       # forgot controls
    exp_b.denominators = []                   # no denominator
    exp_b.system.target_half_life_min = 20    # turnover close to editing window

    for label, exp in [("A (well-defined)", exp_a), ("B (weakly-defined)", exp_b)]:
        review = review_and_record(store, __import__(
            "bionexus.core.contracts", fromlist=["Envelope"]
        ).Envelope(experiment_branch_id="experiment-definition-demo"), actor, exp)
        tracker.define_experiment(problem, exp, review)
        print(f"\nExperiment {label}: {exp.scientific_question[:60]}...")
        print(f"  claim: {exp.claim_type.value}, readout: {exp.readout.assay[:50]}")
        print(f"  verdict: {review.verdict.value.upper()}")
        for f in review.findings:
            print(f"    [{f.severity:7}] {f.check}: {f.message[:80]}")
        print(f"  interpretable negative result: "
              f"{exp.interpretable_negative_result()}")

    print(f"\nprovenance records: "
          f"{len(store.branch_records('experiment-definition-demo'))}")


if __name__ == "__main__":
    main()
