"""T3 polish tests — ELN export, Merkle anchoring, instrument versioning."""
import json

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
