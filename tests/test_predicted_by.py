"""provenance: every predicted number states WHO/WHAT produced it."""
from bionexus import proxy  # noqa: F401  (ensures module importable)
from bionexus.adapters.store.sqlite import SqliteProvenanceStore
from bionexus.core.hypothesis import (Constraint, HypothesisTracker,
                                      ProblemStatement)
from bionexus.core.interfaces import system_actor
from bionexus.views import pipeline_cards

PB = {"source": "model", "policy": "char3gram-ridge-v1",
      "ad": {"extrapolation": True, "nn_tanimoto": 0.21}}


def _chain(with_ad: bool):
    store = SqliteProvenanceStore(":memory:")
    actor = system_actor("t")
    tr = HypothesisTracker(store, actor)
    prob = ProblemStatement(objective="pb", constraints=[Constraint(
        name="potency", description="d", kind="hard", limit=10.0, unit="uM")])
    tr.define_problem(prob)
    pb = dict(PB)
    if not with_ad:
        pb.pop("ad")
    tr.propose_portfolio(prob, [{
        "statement": "P binds", "candidate": "P-1", "assay_type": "binding",
        "predicted": "<= 10", "predicted_value": 5.0, "predicted_by": pb,
        "smiles": "CCO"}])
    return store, f"problem/{prob.problem_id}"


def test_provenance_records_predicted_by():
    store, br = _chain(False)
    recs = store.branch_records(br)
    prop = [r for r in recs if r.event_type.value == "hypothesis_proposed"][0]
    assert (prop.decision or {}).get("predicted_by") == {
        "source": "model", "policy": "char3gram-ridge-v1"}


def test_card_shows_source_and_domain_note():
    store, br = _chain(True)
    card = pipeline_cards(store.branch_records(br))[0]
    assert card["predicted_by"]["policy"] == "char3gram-ridge-v1"
    assert "applicability domain" in card["predicted_by"]["note"]
    # a human/LLM-stated prediction (absent key) rides cleanly as None
    store2, br2 = _chain(False)
    for r in store2.branch_records(br2):
        if r.event_type.value == "hypothesis_proposed":
            assert r.decision["predicted_by"] is not None
