"""Story page + figures — the narrative must stay computable and safe."""
import pytest


def test_figures_deterministic_and_labeled():
    pytest.importorskip("pandas")
    from bionexus import figures
    a = figures.get("recovery")
    assert a == figures.get("recovery")
    assert "<svg" in a and "adaptive (Bayesian)" in a
    assert "<svg" in figures.get("stability")
    assert "<svg" in figures.get("evidence")


def test_story_render_bare():
    pytest.importorskip("pandas")
    from bionexus import story
    story.render()          # bare mode: must not raise


def test_narrative_trust_summary_renders():
    pytest.importorskip("pandas")
    from pathlib import Path
    from bionexus import narrative
    from bionexus.adapters.store.sqlite import SqliteProvenanceStore
    from bionexus.core.contracts import Envelope, EventType
    from bionexus.core.interfaces import record_for, system_actor
    store = SqliteProvenanceStore()
    a = system_actor("t")
    env = Envelope(experiment_branch_id="problem/p1")
    store.append(record_for(env, EventType.hypothesis_proposed, a,
                            decision={"citation": "PMID:1",
                                      "citation_status": "verified"},
                            artifact=None))
    store.append(record_for(env, EventType.gate_decision, a,
                            decision={"kind": "advisory", "advisory": True,
                                      "flags": [{"sample": "X",
                                                 "alert": "acrylamide"}]}))
    narrative.render_trust(store.branch_records("problem/p1"),
                           ["submission for X rejected: [rules safety-rules-v1]"])
