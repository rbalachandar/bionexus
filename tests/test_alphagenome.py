"""AlphaGenome Atlas adapter tests — offline (simulated AVI backend)."""
from bionexus.adapters.genomics.alphagenome import (SimulatedAVI,
                                                    get_variant_scorer)
from bionexus.core.contracts import Envelope, ToolInvocation
from bionexus.core.interfaces import system_actor
from bionexus.toolkit import AgentToolkit


def test_simulated_avi_deterministic_and_shaped():
    scorer = SimulatedAVI()
    a = scorer.score("chr22", 36201698, "A", "C")
    b = scorer.score("chr22", 36201698, "A", "C")
    assert a == b                                  # same variant, same score
    assert 0.0 <= a.avi_score <= 1.0
    assert a.classification in ("high", "moderate", "low")
    assert abs(sum(a.attributions.values()) - a.avi_score) < 1e-3
    assert a.source == "simulated"


def test_ranking_orders_by_avi():
    scorer = SimulatedAVI()
    variants = [{"chromosome": f"chr{i}", "position": 1000 * i, "ref": "A", "alt": "G"}
                for i in range(1, 6)]
    ranked = scorer.rank(variants)
    assert len(ranked) == 5
    scores = [v.avi_score for v in ranked]
    assert scores == sorted(scores, reverse=True)
    assert ranked[0].variant != ranked[1].variant


def test_factory_falls_back_to_simulated(monkeypatch):
    monkeypatch.delenv("ALPHAGENOME_API_KEY", raising=False)
    scorer = get_variant_scorer()
    assert isinstance(scorer, SimulatedAVI)        # no package/key in CI


def test_toolkit_rank_variants_tool():
    from bionexus.adapters.lab.simulator import SimulatorLab
    from bionexus.adapters.store.sqlite import SqliteProvenanceStore
    from bionexus.core.safety import LabGateway, SafetyEngine
    toolkit = AgentToolkit(
        lab_gateway=LabGateway(SimulatorLab(), SafetyEngine(),
                               SqliteProvenanceStore(), system_actor()),
        store=SqliteProvenanceStore(), actor=system_actor())
    assert "rank_variants" in toolkit.executors()
    out = toolkit._tool_rank_variants([
        {"chromosome": "chr7", "position": 140453136, "ref": "T", "alt": "A"},
        {"chromosome": "chr1", "position": 100, "ref": "C", "alt": "T"},
    ])
    assert out["source"] == "simulated"
    assert len(out["ranked"]) == 2
    assert out["ranked"][0]["avi_score"] >= out["ranked"][1]["avi_score"]
    assert set(out["ranked"][0]["top_drivers"]) <= {
        "splicing", "chromatin_accessibility", "gene_expression",
        "conservation", "protein_impact"}


def test_tool_schema_declared():
    names = {s["name"] for s in AgentToolkit.schemas()}
    assert "rank_variants" in names
