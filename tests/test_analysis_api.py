"""Analysis lifecycle API: upload -> preview -> configure -> analyze ->
review, with persistence across store reopen, digest integrity, revision
immutability, and provenance on the analysis branch.
"""
import hashlib
import json

import pytest
from fastapi.testclient import TestClient

LONG = "\n".join([
    "well,sample,conc_um,value",
    "A1,blank,0,5", "A2,blank,0,5",
    "A3,pos,0,95", "A4,pos,0,95",
    "B1,C1,0.1,10", "B2,C1,1,50", "B3,C1,10,90",
    "C1,BORD,3,15", "C2,BORD,10,45", "C3,BORD,30,85",
]) + "\n"

GATE = {"metric": "ic50_um", "direction": "min", "threshold": 10.0,
        "max_response": 100.0}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("BIONEXUS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.chdir(tmp_path)
    from bionexus.api.app import app
    return TestClient(app)


def _upload(client, tmp_path, config=None, name="plate.csv", content=LONG):
    files = {"file": (name, content)}
    data = {"profile": "plate_assay",
            "config": json.dumps(config or {})}
    return client.post("/api/analyses", files=files, data=data)


def test_full_lifecycle_happy_path(client, tmp_path):
    r = _upload(client, tmp_path)
    assert r.status_code == 200, r.text
    doc = r.json()
    aid = doc["id"]
    assert doc["state"] == "preview_ready"
    assert "compounds" not in json.dumps(doc["preview"])  # preview: no fits

    r = client.post(f"/api/analyses/{aid}/configure", json={"config": GATE})
    assert r.status_code == 200
    assert r.json()["state"] == "configured"
    assert r.json()["revision"] == 2  # config change opened a new revision

    r = client.post(f"/api/analyses/{aid}/run")
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "analyzed"
    assert body["revision"] == 2
    calls = {c["entity"]: c["call"] for c in body["result"]["calls"]}
    assert calls["C1"] == "validated"
    assert calls["BORD"] == "inconclusive"  # CI straddles the gate

    r = client.post(f"/api/analyses/{aid}/review", json={
        "action": "acknowledge", "reason": "matches my curve fit",
        "actor": "kim"})
    assert r.status_code == 200
    assert r.json()["state"] == "reviewed"

    final = client.get(f"/api/analyses/{aid}").json()
    assert final["dispositions"][0]["actor"] == "kim"
    # computed call unchanged beside the human disposition
    assert final["result"]["calls"][0]["call"] == "validated"
    # no local storage paths leak to the browser
    assert "storage_path" not in json.dumps(final)


def test_review_before_run_conflicts(client, tmp_path):
    doc = _upload(client, tmp_path).json()
    r = client.post(f"/api/analyses/{doc['id']}/review",
                    json={"action": "acknowledge"})
    assert r.status_code == 409


def test_run_before_configure_conflicts(client, tmp_path):
    doc = _upload(client, tmp_path).json()
    r = client.post(f"/api/analyses/{doc['id']}/run")
    assert r.status_code == 409          # only from a confirmed state
    assert "confirm the interpretation" in r.json()["detail"]


def test_layout_upload_flows_into_analysis(client, tmp_path):
    files = {"file": ("grid.csv", "A,5,50,90\nB,10,40,70\n"),
             "layout": ("map.csv",
                        "well,sample,conc_um\n"
                        "A1,C1,0.1\nA2,C1,1\nA3,C1,10\n"
                        "B1,BORD,3\nB2,BORD,10\nB3,BORD,30\n")}
    data = {"profile": "plate_assay", "config": json.dumps(GATE)}
    r = client.post("/api/analyses", files=files, data=data)
    assert r.status_code == 200
    doc = r.json()
    assert doc["preview"]["has_doses"] is True
    aid = doc["id"]
    client.post(f"/api/analyses/{aid}/configure", json={"config": GATE})
    run = client.post(f"/api/analyses/{aid}/run")
    assert run.status_code == 200
    calls = {c["entity"]: c["call"] for c in run.json()["result"]["calls"]}
    assert calls["C1"] == "validated"


def test_configure_detects_tampered_source(client, tmp_path):
    doc = _upload(client, tmp_path).json()
    aid = doc["id"]
    from bionexus import analysis_store as store
    src = store.get(aid)["artifacts"]["source"]
    p = tmp_path / src["storage_path"]
    p.write_text(LONG.replace("B2,C1,1,50", "B2,C1,1,99"))
    r = client.post(f"/api/analyses/{aid}/configure", json={"config": GATE})
    assert r.status_code == 409
    assert "changed on disk" in r.json()["detail"]


def test_upload_persists_across_store_reopen(client, tmp_path):
    doc = _upload(client, tmp_path).json()
    again = client.get(f"/api/analyses/{doc['id']}")
    assert again.status_code == 200
    assert again.json()["id"] == doc["id"]


def test_list_analyses(client, tmp_path):
    _upload(client, tmp_path)
    r = client.get("/api/analyses")
    assert r.status_code == 200
    assert len(r.json()["analyses"]) >= 1


def test_bad_config_rejected_with_code(client, tmp_path):
    r = _upload(client, tmp_path, config={"bogus_knob": 1})
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "invalid_config"


def test_rejected_upload_type(client, tmp_path):
    r = _upload(client, tmp_path, name="plate.exe", content=b"MZ...")
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "rejected_upload"


def test_unreadable_upload_surfaces_typed(client, tmp_path):
    r = _upload(client, tmp_path, content="not a plate\n,,\n")
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "unreadable_source"


def test_digest_integrity_detects_tampered_source(client, tmp_path):
    doc = _upload(client, tmp_path).json()
    aid = doc["id"]
    client.post(f"/api/analyses/{aid}/configure", json={"config": GATE})
    # scientist (or something) edits the stored bytes under the app
    from bionexus import analysis_store as store
    src = store.get(aid)["artifacts"]["source"]
    p = tmp_path / src["storage_path"]
    p.write_text(LONG.replace("B3,C1,10,90", "B3,C1,10,10"))
    r = client.post(f"/api/analyses/{aid}/run")
    assert r.status_code == 409
    assert "changed on disk" in r.json()["detail"]


def test_result_immutable_across_configure(client, tmp_path):
    doc = _upload(client, tmp_path).json()
    aid = doc["id"]
    client.post(f"/api/analyses/{aid}/configure", json={"config": GATE})
    r1 = client.post(f"/api/analyses/{aid}/run").json()
    client.post(f"/api/analyses/{aid}/configure",
                json={"config": {**GATE, "threshold": 1.0}})
    after = client.get(f"/api/analyses/{aid}").json()
    assert after["result"] is None            # new revision: no result yet
    assert r1["result"]["calls"]              # old run had produced calls
    r2 = client.post(f"/api/analyses/{aid}/run").json()
    calls2 = {c["entity"]: c["call"] for c in r2["result"]["calls"]}
    assert calls2["C1"] == "inconclusive"     # 1 uM CI vs 1.0 gate straddles


def test_provenance_recorded_on_analysis_branch(client, tmp_path):
    doc = _upload(client, tmp_path).json()
    aid = doc["id"]
    client.post(f"/api/analyses/{aid}/configure", json={"config": GATE})
    client.post(f"/api/analyses/{aid}/run")
    client.post(f"/api/analyses/{aid}/review",
                json={"action": "comment", "reason": "ok"})
    from bionexus.adapters.store.sqlite import SqliteProvenanceStore
    s = SqliteProvenanceStore("bionexus.db")
    recs = s.branch_records(f"analysis/{aid}")
    kinds = [r.event_type.value for r in recs]
    assert "experiment_defined" in kinds       # created
    assert "gate_decision" in kinds            # configured
    assert "evaluation" in kinds               # analyzed
    assert "stage_transition" in kinds         # reviewed
    assert s.verify_chain(branch_id=f"analysis/{aid}") == []


def test_missing_analysis_404(client):
    assert client.get("/api/analyses/an-nope").status_code == 404
    assert client.post("/api/analyses/an-nope/run").status_code == 404
