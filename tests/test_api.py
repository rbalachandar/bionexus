"""FastAPI endpoint tests (P0.5): seeded tmp stores, real branches."""
from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from bionexus import program as program_cfg  # noqa: E402
from bionexus.api.app import app  # noqa: E402
from bionexus.views import PROVENANCE_DB  # noqa: E402
from bionexus.wizard_store import WizardStore  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """API over a seeded tmp environment; provenance db is patched to
    the tmp path via monkeypatched module constant."""
    ws = WizardStore()
    program_cfg.save_program_record(
        {"program": "Api-1", "custom": True, "objective": "api objective",
         "modality": "material", "metric": "strength_mpa",
         "direction": "max", "gate_value": 70, "unit": "MPa",
         "mode": "autonomous"})
    eid = "api-exp-1"
    ws.register_agent(eid, "api objective", log="", autonomy="act")
    ws.set_campaign_spec(eid, objective="api objective",
                         program_slug="api-1", k=2, rounds=2,
                         autonomy="act", hypothesis_source="agent",
                         n_candidates=0, modality="material")
    program_cfg.record_launch("Api-1", "prob-api1", "api objective")
    program_cfg.link_leaf("Api-1", eid, campaign_root="prob-api1",
                          question="api objective", status="executing")
    from bionexus.adapters.store.sqlite import SqliteProvenanceStore
    from bionexus.core.contracts import Envelope, EventType
    from bionexus.core.interfaces import record_for, system_actor
    store = SqliteProvenanceStore(str(tmp_path / "prov.db"))
    store.append(record_for(
        Envelope(experiment_branch_id="problem/prob-api1"),
        EventType.problem_defined, system_actor("test"),
        decision={"objective": "registered objective",
                  "constraints": [{"name": "strength_mpa",
                                   "description": ">= 70 MPa"}]}))
    monkeypatch.setattr("bionexus.views.PROVENANCE_DB",
                        str(tmp_path / "prov.db"))
    # routes capture the constant at call time via views; patch there
    with TestClient(app) as c:
        yield c


def test_health(client):
    r = client.get("/api/system/health")
    assert r.status_code == 200 and r.json()["ok"] is True


def test_modalities(client):
    packs = client.get("/api/system/modalities").json()["packs"]
    assert {p["name"] for p in packs} >= {"cell therapy", "material"}


def test_programs_workspace(client):
    data = client.get("/api/programs").json()
    prog = next(p for p in data["programs"] if p["slug"] == "api-1")
    assert prog["mode"] == "autonomous"
    assert {a["eid"] for a in prog["links"]} >= {"api-exp-1"}


def test_experiment_detail(client):
    d = client.get("/api/experiments/api-exp-1").json()
    assert d["status"] in ("executing", "running")
    assert d["program"]["slug"] == "api-1"
    assert d["spec"]["hypothesis_source"] == "agent"
    assert d["objective"] == "registered objective"   # provenance wins
    assert d["branch"] == "problem/prob-api1"


def test_experiment_404(client):
    assert client.get("/api/experiments/nope").status_code == 404


def test_pipeline_and_trace(client):
    p = client.get("/api/experiments/api-exp-1/pipeline").json()
    assert "cards" in p and "counts" in p
    t = client.get("/api/experiments/api-exp-1/trace").json()
    assert t["lines"] == []
    rec = client.get("/api/experiments/api-exp-1/record").json()
    assert rec["title"] == "The record of this run"
    assert "trust" in rec
