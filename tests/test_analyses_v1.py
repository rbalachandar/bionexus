"""/api/v1/analyses: upload -> detect -> run (confirm gate) -> review -> attach.

Honesty properties: no fit before confirmation, abstention when the interval
straddles the gate, digest-bound source, reviews beside (never over) the
computed call, proxy evidence cannot be attached as measured, tampered ledger
refuses the report.
"""
import json

import pytest
from fastapi.testclient import TestClient

LONG = "\n".join([
    "well,sample,conc_um,value",
    "A1,blank,0,5", "A2,blank,0,5", "A3,pos,0,95", "A4,pos,0,95",
    "B1,C1,0.1,10", "B2,C1,1,50", "B3,C1,10,90",
    "C1,BORD,3,15", "C2,BORD,10,45", "C3,BORD,30,85",
]) + "\n"
GATE = {"threshold": 10.0, "direction": "min", "max_response": 100.0}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("BIONEXUS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.chdir(tmp_path)
    from bionexus.api.app import app
    return TestClient(app)


def _up(client, name="plate.csv", content=LONG):
    return client.post("/api/v1/analyses", files={"file": (name, content)})


@pytest.fixture()
def analyzed(client):
    aid = _up(client).json()["id"]
    r = client.post(f"/api/v1/analyses/{aid}/run", json=GATE)
    assert r.status_code == 200, r.text
    return aid


def test_upload_detects_without_fitting(client):
    d = _up(client).json()
    assert d["state"] == "preview_ready" and d["result"] is None
    p = d["preview"]
    assert p["n_controls"] == 4 and p["has_doses"] and set(p["samples"]) == {"C1", "BORD"}
    assert p["z_prime"] == 1.0 and "storage_path" not in json.dumps(d)


def test_run_gives_interval_calls_and_abstains_on_straddle(client, analyzed):
    r = client.get(f"/api/v1/analyses/{analyzed}").json()["result"]
    by = {c["entity"]: c for c in r["compounds"]}
    assert by["C1"]["call"] == "validated" and by["BORD"]["call"] == "inconclusive"
    lo, hi = by["BORD"]["ci"]
    assert lo < 10 < hi                                  # straddles the gate: abstain
    assert by["C1"]["curve"]["points"] and by["C1"]["curve"]["fit"]["line"]
    assert r["gate"]["label"] == "IC50 (µM) ≤ 10"


def test_run_without_gate_is_estimate_only(client):
    aid = _up(client).json()["id"]
    r = client.post(f"/api/v1/analyses/{aid}/run", json={}).json()["result"]
    assert r["gate"] is None and all(c["call"] is None for c in r["compounds"])
    assert all(c["ic50_um"] for c in r["compounds"])


def test_changed_gate_opens_new_revision(client, analyzed):
    r = client.post(f"/api/v1/analyses/{analyzed}/run", json={**GATE, "threshold": 1.0}).json()
    assert r["revision"] == 3
    assert {c["entity"]: c["call"] for c in r["result"]["compounds"]}["C1"] == "inconclusive"


def test_layout_file_flows_through(client):
    files = {"file": ("grid.csv", "A,5,50,90\nB,10,40,70\n"),
             "layout": ("map.csv", "well,sample,conc_um\nA1,C1,0.1\nA2,C1,1\nA3,C1,10\n"
                                   "B1,BORD,3\nB2,BORD,10\nB3,BORD,30\n")}
    d = client.post("/api/v1/analyses", files=files).json()
    assert d["preview"]["has_doses"]
    r = client.post(f"/api/v1/analyses/{d['id']}/run", json=GATE)
    assert r.status_code == 200


def test_bad_uploads_are_typed_problems(client):
    r = _up(client, name="plate.exe", content=b"MZ...")
    assert r.status_code == 422 and r.json()["detail"]["type"] == "rejected-upload"
    r = _up(client, content="not a plate\n,,\n")
    assert r.status_code == 422 and r.json()["detail"]["type"] == "unreadable_source"


def test_changed_source_bytes_refuse_to_run(client, tmp_path):
    from bionexus import analysis_store as store
    aid = _up(client).json()["id"]
    p = tmp_path / store.get(aid)["artifacts"]["source"]["storage_path"]
    p.write_text(LONG.replace("B3,C1,10,90", "B3,C1,10,10"))
    r = client.post(f"/api/v1/analyses/{aid}/run", json=GATE)
    assert r.status_code == 409 and r.json()["detail"]["type"] == "source-changed"


def test_review_needs_a_result_and_sits_beside_the_call(client):
    aid = _up(client).json()["id"]
    assert client.post(f"/api/v1/analyses/{aid}/review", json={"action": "acknowledge"}).status_code == 409
    client.post(f"/api/v1/analyses/{aid}/run", json=GATE)
    d = client.post(f"/api/v1/analyses/{aid}/review",
                    json={"action": "override", "reason": "shallow curve", "target": "C1"}).json()
    assert d["state"] == "reviewed" and d["reviews"][0]["by"] == "local-user"
    assert next(c for c in d["result"]["compounds"] if c["entity"] == "C1")["call"] == "validated"


def test_ledger_records_every_step_and_verifies(client, analyzed):
    client.post(f"/api/v1/analyses/{analyzed}/review", json={"action": "comment", "reason": "ok"})
    from bionexus.adapters.store.sqlite import SqliteProvenanceStore
    s = SqliteProvenanceStore("bionexus.db")
    kinds = [r.event_type.value for r in s.branch_records(f"analysis/{analyzed}")]
    assert kinds == ["experiment_defined", "evaluation", "stage_transition"]
    assert s.verify_chain(branch_id=f"analysis/{analyzed}") == []


def test_report_and_csv(client, analyzed):
    html = client.get(f"/api/v1/analyses/{analyzed}/report")
    assert html.status_code == 200 and "intact (recomputed)" in html.text
    csv = client.get(f"/api/v1/analyses/{analyzed}/export.csv")
    header = csv.text.splitlines()[0].split(",")
    assert {"value", "value_raw", "call", "call_reason", "evidence_origin"} <= set(header)


def test_report_refuses_tampered_chain(client, analyzed):
    from bionexus.adapters.store.sqlite import SqliteProvenanceStore
    s = SqliteProvenanceStore("bionexus.db")
    row = s._conn.execute("SELECT record_id, payload FROM provenance WHERE branch_id=? "
                          "ORDER BY rowid LIMIT 1", (f"analysis/{analyzed}",)).fetchone()
    s._conn.executescript("DROP TRIGGER provenance_no_update;")
    payload = json.loads(row[1])
    payload["decision"]["kind"] = "forged"
    s._conn.execute("UPDATE provenance SET payload=? WHERE record_id=?", (json.dumps(payload), row[0]))
    s._conn.commit()
    r = client.get(f"/api/v1/analyses/{analyzed}/report")
    assert r.status_code == 409 and r.json()["detail"]["type"] == "chain-tampered"


def test_attach_requires_review_and_measured_data_then_seals_on_campaign(client, analyzed, monkeypatch):
    monkeypatch.setattr("bionexus.api.v1.campaigns._load",
                        lambda eid: (None, None, {}, "problem/prob-x", []))
    body = {"campaign_id": "e1", "candidate": "C1"}
    r = client.post(f"/api/v1/analyses/{analyzed}/attach", json=body)
    assert r.status_code == 409 and r.json()["detail"]["type"] == "review-first"
    client.post(f"/api/v1/analyses/{analyzed}/review", json={"action": "acknowledge"})
    d = client.post(f"/api/v1/analyses/{analyzed}/attach", json=body).json()
    assert d["attachments"][0]["campaign_id"] == "e1"
    from bionexus.adapters.store.sqlite import SqliteProvenanceStore
    rec = SqliteProvenanceStore("bionexus.db").branch_records("problem/prob-x")[-1]
    assert rec.decision["kind"] == "analysis_attached" and rec.decision["calls"]["C1"] == "validated"
    assert "no campaign verdict" in rec.decision["effect"]


def test_proxy_evidence_cannot_be_attached(client, monkeypatch):
    monkeypatch.setattr("bionexus.api.v1.campaigns._load",
                        lambda eid: (None, None, {}, "problem/prob-x", []))
    aid = _up(client).json()["id"]
    client.post(f"/api/v1/analyses/{aid}/run", json={**GATE, "evidence_origin": "simulated"})
    client.post(f"/api/v1/analyses/{aid}/review", json={"action": "acknowledge"})
    r = client.post(f"/api/v1/analyses/{aid}/attach", json={"campaign_id": "e1"})
    assert r.status_code == 409 and r.json()["detail"]["type"] == "proxy-evidence"


def test_missing_analysis_404(client):
    assert client.get("/api/v1/analyses/an-nope").status_code == 404
    assert client.post("/api/v1/analyses/an-nope/run", json={}).status_code == 404
