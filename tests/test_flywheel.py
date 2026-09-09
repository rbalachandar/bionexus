"""Flywheel tests — negatives recorded, priors applied, prompt context."""
from bionexus.flywheel import Flywheel


def test_submit_and_negative_summary():
    fw = Flywheel(":memory:")
    fw.submit("A-1", "fam-A", "binding", "invalidated", 45.0, (40.0, 50.0),
              problem_id="p1")
    fw.submit("A-2", "fam-A", "binding", "validated", 3.0, None, problem_id="p1")
    fw.submit("A-3", "fam-B", "binding", "tested")       # non-verdict ignored
    negs = fw.negative_summary()
    assert [n["candidate"] for n in negs] == ["A-1"]
    assert fw.negative_summary(problem_id="other") == []


def test_family_prior_direction():
    fw = Flywheel(":memory:")
    assert fw.family_prior("fresh") == 1.0
    for i in range(3):
        fw.submit(f"A-{i}", "fam-A", "binding", "invalidated")
        fw.submit(f"B-{i}", "fam-B", "binding", "validated")
    assert fw.family_prior("fam-A") == 0.5      # all fail -> floor
    assert fw.family_prior("fam-B") == 1.5      # all win -> ceiling
    assert fw.prior_bonus("fam-A") < 0 < fw.prior_bonus("fam-B")


def test_prompt_context_mentions_ruled_out():
    fw = Flywheel(":memory:")
    fw.submit("Z-9", "dead-scaffold", "binding", "refuted", 33.0)
    txt = fw.prompt_context()
    assert "Z-9" in txt and "dead-scaffold" in txt and "do NOT re-propose" in txt
    assert Flywheel(":memory:").prompt_context() == ""


def test_tracker_on_verdict_hook():
    from bionexus.adapters.store.sqlite import SqliteProvenanceStore
    from bionexus.core.hypothesis import (HypothesisTracker, ProblemStatement)
    from bionexus.core.interfaces import system_actor
    seen = []
    fw = Flywheel(":memory:")
    t = HypothesisTracker(SqliteProvenanceStore(), system_actor(),
                          on_verdict=lambda h: seen.append(h.status))
    p = ProblemStatement(objective="o")
    hs = t.propose_portfolio(p, [{"statement": "s", "candidate": "c",
                                  "predicted": "<=20", "predicted_value": 20.0,
                                  "family": "fam"}])
    h = hs[0]
    h.status = "invalidated"
    h.observed_value = 44.0
    t.record_outcome(h)
    assert seen == ["invalidated"]
    assert fw.negative_summary() == []          # hook only; submit is separate
