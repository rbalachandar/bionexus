import json
import math

import pytest

from bionexus.adapters.lab.simulator import SimulatorLab
from bionexus.adapters.models.openai_compat import OpenAICompatProvider
from bionexus.adapters.sandbox.local import LocalSandbox
from bionexus.adapters.store.sqlite import SqliteProvenanceStore
from bionexus.core.contracts import (
    Actor,
    Envelope,
    EventType,
    ProtocolOp,
    ProtocolStep,
    ProtocolSubmission,
    ReagentSpec,
    SampleKind,
    SampleSpec,
    ToolInvocation,
)
from bionexus.core.interfaces import system_actor
from bionexus.core.registry import Registry
from bionexus.core.safety import (
    ForbiddenComboRule,
    LabGateway,
    MaxBslRule,
    MaxStepsRule,
    SafetyEngine,
)
from bionexus.core.workflow import HypothesisTournament, StageGraph, TournamentConfig

BRANCH = "b-test"


def env() -> Envelope:
    return Envelope(experiment_branch_id=BRANCH)


def make_protocol(reagents=None, steps=1):
    return ProtocolSubmission(
        envelope=env(),
        title="t",
        assay_type="binding",
        steps=[ProtocolStep(seq=i + 1, op=ProtocolOp.dispense) for i in range(steps)],
        samples=[SampleSpec(sample_id="C1", kind=SampleKind.compound)],
        reagents=reagents or [ReagentSpec(name="buffer", amount="1 mL", bsl_level=1)],
    )


# ---- contracts ---------------------------------------------------------------

def test_envelope_and_ids_unique():
    a, b = env(), env()
    assert a.contract_id != b.contract_id
    assert a.schema_version == "v1"


def test_tool_name_registry_covers_all_blocks():
    from bionexus.core.contracts import ToolName
    vals = {t.value for t in ToolName}
    assert {v for v in vals if v.startswith("c.")}, "block C tools present"
    assert {v for v in vals if v.startswith("d.")}, "block D tools present"
    assert {v for v in vals if v.startswith("e.")}, "block E tools present"


# ---- provenance (P5) -----------------------------------------------------------

def test_provenance_hash_chain():
    from bionexus.core.contracts import Artifact, ArtifactKind
    from bionexus.core.interfaces import record_for

    store = SqliteProvenanceStore()
    actor = system_actor()
    r1 = store.append(record_for(env(), EventType.artifact_created, actor,
                                 artifact=Artifact(artifact_id="a1", kind=ArtifactKind.molecule, uri="mem://a1")))
    r2 = store.append(record_for(env(), EventType.artifact_created, actor,
                                 artifact=Artifact(artifact_id="a2", kind=ArtifactKind.report, uri="mem://a2")))
    assert r1.record_hash and r2.record_hash
    assert r2.prev_record_hash == r1.record_hash
    assert len(store.branch_records(BRANCH)) == 2


# ---- safety (P6) ----------------------------------------------------------------

def test_safety_blocks_bsl_and_combos():
    engine = SafetyEngine(rules=[MaxBslRule(1), ForbiddenComboRule([("acid*", "*hypochlorite*")])])
    ok, reason = engine.check(make_protocol())
    assert ok and reason is None
    ok, reason = engine.check(make_protocol([ReagentSpec(name="toxin", amount="1", bsl_level=3)]))
    assert not ok and "BSL" in reason
    ok, reason = engine.check(make_protocol([
        ReagentSpec(name="acid chloride", amount="1", bsl_level=1),
        ReagentSpec(name="sodium hypochlorite", amount="1", bsl_level=1),
    ]))
    assert not ok and "forbidden" in reason


def test_max_steps_rule():
    ok, reason = SafetyEngine(rules=[MaxStepsRule(2)]).check(make_protocol(steps=5))
    assert not ok


def test_lab_gateway_blocks_unsafe_and_records_runs():
    store = SqliteProvenanceStore()
    actor = system_actor()
    gw = LabGateway(SimulatorLab(), SafetyEngine(rules=[ForbiddenComboRule([("a", "b")])]), store, actor)
    run_id, reason = gw.submit(make_protocol([ReagentSpec(name="a", amount="1", bsl_level=1),
                                              ReagentSpec(name="b", amount="1", bsl_level=1)]))
    assert run_id is None and "forbidden" in reason
    run_id, reason = gw.submit(make_protocol())
    assert run_id and reason is None
    events = {r.event_type for r in store.branch_records(BRANCH)}
    assert EventType.lab_run in events


# ---- simulator (P4/P8) ----------------------------------------------------------

def test_simulator_deterministic_per_sample():
    lab_a, lab_b = SimulatorLab(seed=7), SimulatorLab(seed=7)
    p = make_protocol()
    ra, rb = lab_a.fetch_results(lab_a.submit_protocol(p)), lab_b.fetch_results(lab_b.submit_protocol(p))
    assert [m.value for m in ra.measurements] == [m.value for m in rb.measurements]
    assert ra.qc.controls_passed


# ---- sandbox fork/snapshot (P7) ---------------------------------------------------

def test_local_sandbox_fork_isolation():
    store = SqliteProvenanceStore()
    parent = LocalSandbox("root", state={"hits": ["A"]}, store=store, actor=system_actor())
    snap = parent.snapshot()
    child = parent.fork(snap)
    child.state["hits"].append("B")
    assert parent.state["hits"] == ["A"]
    assert child.parent_branch_id == "root"
    events = {r.event_type for r in store.branch_records(child.branch_id)}
    assert EventType.sandbox_fork in events


# ---- tournament (workflow) ---------------------------------------------------------

def test_tournament_ranks_and_prunes():
    cfg = TournamentConfig(population=6, survivors=2, waves=2)
    t = HypothesisTournament(model=None, config=cfg)
    pool = [{"id": i, "score": float(i)} for i in range(6)]
    survivors = t.run("b", {}, generate_fn=lambda ctx: pool, score_fn=lambda p: p["score"])
    assert [s["id"] for s in survivors] == [5, 4]


# ---- model adapter (P3) --------------------------------------------------------------

def test_stub_provider_deterministic_offline():
    provider = OpenAICompatProvider()  # no base_url -> stub mode
    inv = ToolInvocation(envelope=env(), tool="c.fm.generate_molecules")
    r1 = provider.generate(inv, "prompt-x", n=3)
    r2 = provider.generate(inv, "prompt-x", n=3)
    assert r1.output["text"] == r2.output["text"]
    assert r1.model_version == provider.model_version
    json.loads(r1.output["text"])  # valid JSON proposals


# ---- anti-bloat guardrail (P1): core imports only pydantic ---------------------------

def test_core_has_no_heavy_imports():
    import pathlib
    forbidden = ("requests", "numpy", "pandas", "torch", "langchain", "httpx", "sqlalchemy")
    core = pathlib.Path(__file__).parent.parent / "src" / "bionexus" / "core"
    for py in core.rglob("*.py"):
        src = py.read_text()
        for bad in forbidden:
            assert f"import {bad}" not in src, f"{py.name} imports forbidden '{bad}'"


def test_success_criteria_ci_straddle_is_inconclusive():
    from bionexus.core.hypothesis import SuccessCriteria
    c = SuccessCriteria(metric="ic50_um", threshold=20.0, direction="min")
    assert c.classify(15.0, (9.0, 18.0)) == "validated"      # CI fully under
    assert c.classify(25.0, (21.0, 40.0)) == "invalidated"   # CI fully over
    assert c.classify(19.0, (12.0, 27.0)) == "inconclusive"  # straddles
    assert c.classify(15.0, None) == "validated"             # no CI: point est.
    hi = SuccessCriteria(metric="value", threshold=90.0, direction="max")
    assert hi.classify(95.0, (91.0, 99.0)) == "validated"
    assert hi.classify(95.0, (85.0, 99.0)) == "inconclusive"


def test_fit_ic50_ci_covers_true_value():
    import random
    from bionexus.labread import fit_ic50_ci
    rng = random.Random(3)
    true_ic50, maxr = 5.0, 500.0
    pts = [(c, maxr / (1 + true_ic50 / c) + rng.gauss(0, 12))
           for c in (0.5, 2, 10, 40)]
    out = fit_ic50_ci(pts, maxr)
    assert out and out["ci_low"] <= true_ic50 <= out["ci_high"]
    assert abs(out["ic50"] - true_ic50) / true_ic50 < 0.6


def test_bootstrap_ci_brackets_mean():
    from bionexus.benchmark import bootstrap_ci
    lo, hi = bootstrap_ci([1.0, 1.2, 0.9, 1.1, 1.3, 0.8, 1.05, 1.15])
    assert lo <= 1.087 <= hi
    assert hi > lo


def test_spearman_ci_width_reflects_n():
    from bionexus.benchmark import spearman_ci
    perfect = list(range(30)), [i * 2.0 for i in range(30)]
    rho, lo, hi = spearman_ci(*perfect)
    assert rho == 1.0 and lo == 1.0 and hi == 1.0
    noisy = [float(i) for i in range(8)], [7.0, 2.0, 5.0, 1.0, 6.0, 3.0, 8.0, 4.5]
    r2, l2, h2 = spearman_ci(*noisy)
    assert l2 <= r2 <= h2 and (h2 - l2) > 0.2       # small n -> wide CI


def test_benjamini_hochberg():
    from bionexus.benchmark import benjamini_hochberg
    p = [0.001, 0.008, 0.039, 0.041, 0.21, 0.6]
    flags = benjamini_hochberg(p, fdr=0.10)
    # BH at fdr .1: 0.001<=.0166, 0.008<=.033, 0.039<=.05, 0.041<=.0664 -> 4 hits
    assert flags[:4] == [True] * 4 and flags[4:] == [False] * 2
    assert benjamini_hochberg([]) == []


def test_mechanistic_fields_flow_and_bonus():
    from bionexus.core.hypothesis import (HypothesisTracker, ProblemStatement,
                                          explanatory_bonus)
    t = HypothesisTracker(SqliteProvenanceStore(), system_actor())
    p = ProblemStatement(objective="o")
    hs = t.propose_portfolio(p, [
        {"statement": "A binds", "candidate": "A", "predicted": "<=20",
         "predicted_value": 20.0, "mechanism": "covalent-Cys",
         "refutation_condition": "Cys-mut kills activity",
         "citation": "PMID:12345",
         "predicted_observables": ["mass adduct on peptide"]},
        {"statement": "B binds", "candidate": "B", "predicted": "<=20",
         "predicted_value": 20.0}])
    a, b = hs
    assert a.mechanism == "covalent-Cys" and a.citation == "PMID:12345"
    assert a.predicted_observables == ["mass adduct on peptide"]
    # a: mechanism + refutation + UNVERIFIED citation = 0.15 (citation adds 0)
    # verified citation: +0.05 -> 0.20; invalid citation: -0.10 -> 0.05
    assert abs(explanatory_bonus(a) - 0.15) < 1e-9
    assert explanatory_bonus(b) == 0.0
    a.citation_status = "verified"
    assert abs(explanatory_bonus(a) - 0.2) < 1e-9
    a.citation_status = "invalid"
    assert abs(explanatory_bonus(a) - 0.05) < 1e-9
    sel = t.select_portfolio(p, hs, lambda h: 0.5, k=1)
    assert sel == [a]                       # explanatory power broke the tie
    recs = t.store.branch_records(f"problem/{p.problem_id}")
    decisions = [x for r in recs if r.event_type.value == "hypotheses_filtered"
                 for x in (r.decision or {}).get("decisions", [])]
    assert any("explanatory power" in d.get("reason", "") for d in decisions)


def test_dose_designer_posterior_converges():
    from bionexus.adaptive import DoseDesigner
    d = DoseDesigner(rmax=500.0, sigma=10.0)
    true = 6.0
    seen = set()
    for _ in range(8):
        c = d.next_dose()
        if c is None:
            break
        seen.add(c)
        d.observe(c, 500.0 / (1 + true / c))
    est, ci = d.estimate()
    assert ci[0] <= true <= ci[1]
    assert abs(est - true) / true < 0.5
    assert len(seen) >= 3          # actually explored distinct doses
    assert d.entropy() < math.log(len(d.grid))   # posterior shrank


def test_citation_parsing_and_verification(tmp_path, monkeypatch):
    from bionexus import citations
    monkeypatch.setattr(citations, "CACHE", tmp_path / "citations.json")
    assert citations.parse("PMID:35377565") == ("pmid", "35377565")
    assert citations.parse("10.1021/acs.jmedchem.4c02631") == \
        ("doi", "10.1021/acs.jmedchem.4c02631")
    assert citations.parse("see Smith 2020 for details") is None

    def fake_fetch(url):
        if "esummary" in url:
            return b'{"result": {"35377565": {"title": "HPK1 inhibitors",' \
                    b'"pubdate": "2025 Jan 1", "source": "J Med Chem"}}}'
        return b'{"esearchresult": {"idlist": []}}'
    v = citations.verify("PMID:35377565", fetch=fake_fetch)
    assert v["status"] == "verified" and "J Med Chem" in v["detail"]
    v2 = citations.verify("10.9999/nonexistent.2099", fetch=fake_fetch)
    assert v2["status"] == "invalid"

    def dead_fetch(url):
        raise OSError("offline")
    v3 = citations.verify("PMID:99999999", fetch=dead_fetch)
    assert v3["status"] == "check-failed"      # network != fake
