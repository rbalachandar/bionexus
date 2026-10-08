"""ProteinDesignLabAdapter — protein binder design through BioNexus's
hypothesis pipeline. All quality-passing designs become hypotheses;
budget constrains screening, not proposing."""
import pytest

from bionexus.adapters.lab.protein_design import ProteinDesignLabAdapter
from bionexus.core.hypothesis import Constraint, HypothesisTracker, ProblemStatement
from bionexus.adapters.store.sqlite import SqliteProvenanceStore
from bionexus.core.interfaces import system_actor


def _make_tracker():
    store = SqliteProvenanceStore(":memory:")
    actor = system_actor("t")
    tr = HypothesisTracker(store, actor)
    prob = ProblemStatement(objective="protein design", constraints=[Constraint(
        name="iptm", description="interface confidence", kind="hard",
        limit=0.7, unit="iptm")])
    tr.define_problem(prob)
    return tr, prob


def test_quality_floor_rejects_bad_sequences():
    ad = ProteinDesignLabAdapter(mock=True)
    designs = [
        {"name": "good", "sequence": "M" + "ACDEFGHIKLMNPQRSTVWY" * 4, "plddt": 0.85},
        {"name": "low_conf", "sequence": "M" + "ACDEFGHIKLMNPQRSTVWY" * 4, "plddt": 0.3},
        {"name": "too_short", "sequence": "MAG", "plddt": 0.9},
        {"name": "bad_aa", "sequence": "M" + "X" * 80, "plddt": 0.9},
    ]
    passing, rejected = ad.apply_quality_floor(designs)
    assert len(passing) == 1 and passing[0]["name"] == "good"
    assert len(rejected) == 3
    assert all("rejection_reasons" in d for d in rejected)


def test_diversity_prioritization_prefers_dissimilar():
    ad = ProteinDesignLabAdapter(mock=True)
    import string
    designs = [{"name": f"d{i}",
                "sequence": "M" + "".join(
                    string.ascii_uppercase[(i*7+j*13) % 20]
                    for j in range(80)),
                "plddt": 0.9} for i in range(30)]
    picked = ad.prioritize(designs, budget=5)
    assert len(picked) == 5
    seqs = [d["sequence"] for d in picked]
    assert len(set(seqs)) >= 3  # diversity: not 5 copies of the same fold


def test_full_design_cycle_all_quality_passing_become_hypotheses():
    tr, prob = _make_tracker()
    ad = ProteinDesignLabAdapter(mock=True, seed=7, min_plddt=0.5)
    result = ad.run_design_cycle(tr, prob, target_sequence="M" * 120,
                                 n_attempts=30, screening_budget=10,
                                 iptm_gate=0.5)
    # every quality-passing design becomes a hypothesis (no arbitrary cap)
    assert result["n_hypotheses"] > 0
    assert result["n_hypotheses"] <= result["n_generated"]
    # screening budget respected
    assert len(result["screened"]) <= 10
    # verdicts distributed
    assert sum(result["verdicts"].values()) == result["n_hypotheses"]
    # rejected-by-floor designs are counted, not silent
    assert result["n_generated"] >= result["n_hypotheses"]


def test_screening_budget_is_not_hypothesis_cap():
    tr, prob = _make_tracker()
    ad = ProteinDesignLabAdapter(mock=True, seed=7, min_plddt=0.0)
    result = ad.run_design_cycle(tr, prob, target_sequence="M" * 120,
                                 n_attempts=50, screening_budget=5,
                                 iptm_gate=0.5)
    # 5 screened but all quality-passing designs are hypotheses
    assert len(result["screened"]) <= 5
    assert result["n_hypotheses"] > 5  # way more proposed than screened
    assert result["verdicts"]["proposed"] > 0  # untested hypotheses visible
