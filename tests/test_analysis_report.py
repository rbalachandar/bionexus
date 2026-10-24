"""Analysis report + CSV export: honest artifacts that agree with the
browser result, regenerate deterministically from the stored revision,
and REFUSE a tampered provenance chain."""
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
    data = {"profile": "plate_assay", "config": json.dumps(config or {})}
    return client.post("/api/analyses", files=files, data=data)


@pytest.fixture()
def analyzed(client, tmp_path):
    """An upload taken through configure + run."""
    doc = _upload(client, tmp_path).json()
    aid = doc["id"]
    client.post(f"/api/analyses/{aid}/configure", json={"config": GATE})
    r = client.post(f"/api/analyses/{aid}/run")
    assert r.status_code == 200
    return aid


def test_report_agrees_with_api_result(client, analyzed):
    doc = client.get(f"/api/analyses/{analyzed}").json()
    r = client.get(f"/api/analyses/{analyzed}/report")
    assert r.status_code == 200
    html = r.text
    assert "text/html" in r.headers["content-type"]
    # identity + digest + origin + config + chain status all present
    assert doc["artifacts"]["source"]["sha256"] in html
    assert "measured" in html
    assert "intact (recomputed)" in html
    # calls agree with the API read-model
    for c in doc["result"]["calls"]:
        assert c["entity"] in html and c["call"] in html


def test_report_declares_no_disposition_honestly(client, analyzed):
    html = client.get(f"/api/analyses/{analyzed}/report").text
    assert "No human disposition recorded" in html


def test_report_shows_disposition_after_review(client, analyzed):
    client.post(f"/api/analyses/{analyzed}/review", json={
        "action": "override", "reason": "curve is shallow", "actor": "kim"})
    html = client.get(f"/api/analyses/{analyzed}/report").text
    assert "override" in html and "kim" in html and "curve is shallow" in html
    assert "No human disposition" not in html


def test_report_requires_result(client, tmp_path):
    doc = _upload(client, tmp_path).json()
    r = client.get(f"/api/analyses/{doc['id']}/report")
    assert r.status_code == 409


def test_export_csv_raw_and_normalized_separate(client, analyzed):
    r = client.get(f"/api/analyses/{analyzed}/export.csv")
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    lines = r.text.strip().splitlines()
    header = lines[0].split(",")
    assert "value" in header and "value_raw" in header
    assert "call" in header and "call_reason" in header
    assert "evidence_origin" in header
    # the validated compound's row carries its call
    rows = [dict(zip(header, ln.split(","))) for ln in lines[1:]]
    c1 = [x for x in rows if x["sample"] == "C1"]
    assert c1 and any(x["call"] == "validated" for x in c1)


def test_export_refuses_changed_source_bytes(client, analyzed, tmp_path):
    from bionexus import analysis_store as store
    src = store.get(analyzed)["artifacts"]["source"]
    p = tmp_path / src["storage_path"]
    p.write_text(LONG.replace("B2,C1,1,50", "B2,C1,1,90"))
    r = client.get(f"/api/analyses/{analyzed}/export.csv")
    # regeneration no longer matches the stored revision: refuse loudly
    assert r.status_code == 409
    assert "changed on disk" in r.json()["detail"]


def test_report_refuses_tampered_chain(client, analyzed, tmp_path):
    from bionexus.adapters.store.sqlite import SqliteProvenanceStore
    s = SqliteProvenanceStore("bionexus.db")
    branch = f"analysis/{analyzed}"
    row = s._conn.execute(
        "SELECT record_id, payload FROM provenance WHERE branch_id=? "
        "ORDER BY rowid LIMIT 1", (branch,)).fetchone()
    assert row, "analysis branch should have provenance records"
    # simulate an attacker with raw db write access: the engine's
    # append-only trigger is the FIRST defense; this test is about the
    # read-path recomputation catching what slips past it
    s._conn.executescript("DROP TRIGGER provenance_no_update;")
    payload = json.loads(row[1])
    payload["decision"]["kind"] = "forged"
    s._conn.execute("UPDATE provenance SET payload=? WHERE record_id=?",
                    (json.dumps(payload), row[0]))
    s._conn.commit()
    r = client.get(f"/api/analyses/{analyzed}/report")
    assert r.status_code == 409
    assert "TAMPERED" in r.json()["detail"]
