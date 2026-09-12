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
