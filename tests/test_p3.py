"""T3 polish tests — ELN export, Merkle anchoring, instrument versioning."""
import json

import pytest

from bionexus.anchor import merkle_root, store_hashes
from bionexus.eln import branch_to_rows, export_eln
from bionexus.adapters.store.sqlite import SqliteProvenanceStore
from bionexus.core.contracts import Envelope, EventType
from bionexus.core.interfaces import record_for, system_actor


def _branch(tmp_path):
    db = str(tmp_path / "t.db")
    store = SqliteProvenanceStore(db)
    for i in range(5):
        store.append(record_for(
            Envelope(experiment_branch_id="problem/p1"),
            EventType.hypothesis_validated, system_actor("a"),
            decision={"verdict": "validated", "observed": 1.0 + i,
                      "observed_ci": [0.5, 1.5], "threshold": 20.0,
                      "run_id": f"r{i}", "instrument": "simulator",
                      "instrument_version": "sim-v1"}))
    return db, store


def test_merkle_root_stable_and_order_sensitive():
    a = merkle_root(["x1", "x2", "x3", "x4"])
    assert a == merkle_root(["x1", "x2", "x3", "x4"])
    assert a != merkle_root(["x2", "x1", "x3", "x4"])
    assert a != merkle_root(["x1", "x2", "x3"])


def test_anchor_roundtrip(tmp_path, monkeypatch):
    import bionexus.anchor as A
    monkeypatch.setattr(A, "ANCHORS", tmp_path / "anchors.json")
    db, _ = _branch(tmp_path)
    entry = A.anchor(db)
    assert entry["records"] == 5
    res = A.verify(db)
    assert res["match"]
    # tamper: append a record -> root changes, verify fails
    store = SqliteProvenanceStore(db)
    store.append(record_for(Envelope(experiment_branch_id="problem/p1"),
                            EventType.stage_transition, system_actor()))
    assert not A.verify(db)["match"]


def test_eln_export(tmp_path):
    _, store = _branch(tmp_path)
    recs = store.branch_records("problem/p1")
    rows = branch_to_rows(recs)
    assert len(rows) == 5
    assert rows[0]["verdict"] == "validated"
    assert rows[0]["ci95_low_uM"] == 0.5
    out = tmp_path / "eln.csv"
    export_eln(recs, out, out.with_suffix(".json"))
    assert out.exists() and out.with_suffix(".json").exists()
    assert len(json.loads(out.with_suffix(".json").read_text())) == 5


def test_simulator_reports_version():
    from bionexus.adapters.lab.simulator import SimulatorLab
    assert SimulatorLab().version == "sim-v1"


def test_fixtures_freeze_verify_materialize(tmp_path):
    from bionexus import fixtures
    study = tmp_path / "case-studies" / "s1"
    study.mkdir(parents=True)
    (tmp_path / ".data").mkdir()
    live = tmp_path / ".data" / "x.csv"
    live.write_text("a,b\n1,2\n")
    # patch root resolution: freeze uses study.resolve().parents[1]
    m = fixtures.freeze(study, [("x.csv", live)])
    assert m["entries"][0]["target"] == ".data/x.csv"
    ok, problems = fixtures.verify(study)
    assert ok, problems
    live.unlink()
    n = fixtures.materialize(study)
    assert n == 1 and live.read_text() == "a,b\n1,2\n"
    # tamper detection
    (study / "fixtures" / "x.csv.gz").write_bytes(
        (__import__("gzip").compress(b"a,b\n9,9\n")))
    ok, problems = fixtures.verify(study)
    assert not ok and "MISMATCH" in problems[0]


def test_safety_engine_molecule_gates():
    from bionexus.core.contracts import (
        Envelope, ProtocolOp, ProtocolStep, ProtocolSubmission, ReagentSpec,
        SampleKind, SampleSpec,
    )
    from bionexus.core.safety import SafetyEngine

    pytest.importorskip("rdkit", reason="toxicophore SMARTS need rdkit")

    def proto(smi, intent=""):
        return ProtocolSubmission(
            envelope=Envelope(experiment_branch_id="t"), title="screen",
            assay_type="binding",
            steps=[ProtocolStep(seq=1, op=ProtocolOp.dispense,
                                params={"volume_ul": 50})],
            samples=[SampleSpec(sample_id="X", kind=SampleKind.compound,
                                concentration="10uM",
                                metadata={"smiles": smi, "intent": intent})],
            reagents=[ReagentSpec(name="buffer", amount="5 mL", bsl_level=1)])

    eng = SafetyEngine()
    ok, why = eng.check(proto("O=[N+]([O-])c1ccccc1"))       # nitrobenzene
    assert not ok and "aromatic_nitro" in why
    ok, _ = eng.check(proto("C=CC(=O)N"))                     # bare acrylamide
    assert not ok
    ok, _ = eng.check(proto("C=CC(=O)N", intent="covalent"))  # declared warhead
    assert ok
    ok, _ = eng.check(proto("CC(=O)Oc1ccccc1C(=O)O"))        # aspirin
    assert ok


def test_durc_campaign_refusal(tmp_path):
    import pytest
    from bionexus.autoloop import CampaignConfig, run_campaign
    from bionexus.adapters.lab.simulator import SimulatorLab
    from bionexus.adapters.store.sqlite import SqliteProvenanceStore
    from bionexus.core.hypothesis import ProblemStatement
    problem = ProblemStatement(objective="Screen inhibitors of Bacillus anthracis lethal factor")
    with pytest.raises(ValueError, match="DURC"):
        run_campaign(CampaignConfig(problem=problem, hypotheses=[],
                                    autonomy="act", inbox=str(tmp_path)),
                     SimulatorLab(), SqliteProvenanceStore())


def test_charridge_attribution_sums_to_prediction():
    from bionexus.benchmark import CharRidgePolicy
    from bionexus.interpret import explain_prediction
    pol = CharRidgePolicy(dim=256)
    data = [("CCO", 1.0), ("CCCO", 1.4), ("c1ccccc1O", 2.2),
            ("CC(=O)O", 0.6), ("CCCCO", 1.8), ("c1ccccc1", 2.5)]
    pol.fit(data)
    ex = explain_prediction(pol, "c1ccccc1O")
    assert ex["method"] == "ngram-contributions"
    assert ex["top_positive"], "should find positive drivers"
    total = (ex["baseline_mean"]
             + sum(w for _, w in ex["top_positive"])
             + sum(w for _, w in ex["top_negative"]))
    assert abs(total - ex["prediction"]) < 0.6   # contribution accounting


def test_rf_attribution_reports_bits():
    pytest.importorskip("sklearn")
    pytest.importorskip("rdkit")
    from bionexus.adapters.models.sklearn_policy import MorganFingerprintRF
    from bionexus.interpret import explain_prediction
    pol = MorganFingerprintRF(n_estimators=20)
    pol.fit([("CCO", 1.0), ("CCCO", 1.4), ("c1ccccc1O", 2.2),
             ("CC(=O)O", 0.6), ("CCCCO", 1.8), ("c1ccccc1", 2.5)])
    ex = explain_prediction(pol, "c1ccccc1CCO")
    assert ex["method"] == "importance-weighted-bits"
    assert ex["top_bits"] and "caveat" in ex


def test_safety_rules_data_file_versioned():
    from bionexus.adapters.bio import tox_alerts
    assert tox_alerts.RULES_VERSION == "safety-rules-v1"
    assert len(tox_alerts.ALERTS) >= 18


def test_gate_refusals_are_recorded_in_provenance():
    import pytest
    pytest.importorskip("rdkit")
    from bionexus.adapters.lab.simulator import SimulatorLab
    from bionexus.adapters.store.sqlite import SqliteProvenanceStore
    from bionexus.core.contracts import (Envelope, ProtocolOp, ProtocolStep,
                                         ProtocolSubmission, ReagentSpec,
                                         SampleKind, SampleSpec)
    from bionexus.core.interfaces import system_actor
    from bionexus.core.safety import LabGateway, SafetyEngine
    store = SqliteProvenanceStore()
    gw = LabGateway(SimulatorLab(), SafetyEngine(), store, system_actor())
    proto = ProtocolSubmission(
        envelope=Envelope(experiment_branch_id="problem/p-ref"),
        title="t", assay_type="binding",
        steps=[ProtocolStep(seq=1, op=ProtocolOp.dispense,
                            params={"volume_ul": 50})],
        samples=[SampleSpec(sample_id="BAD-1", kind=SampleKind.compound,
                            concentration="10uM",
                            metadata={"smiles": "O=[N+]([O-])c1ccccc1"})],
        reagents=[ReagentSpec(name="b", amount="5 mL", bsl_level=1)])
    run_id, reason = gw.submit(proto)
    assert run_id is None
    refusals = [r for r in store.branch_records("problem/p-ref")
                if (r.decision or {}).get("kind") == "safety_refusal"]
    assert refusals and "BAD-1" in refusals[-1].decision["samples"]
