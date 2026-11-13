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
    monkeypatch.setattr("bionexus.views.ids.PROVENANCE_DB",
                        str(tmp_path / "prov.db"))
    # routes capture the constant at call time via views; patch there
    with TestClient(app) as c:
        yield c


def test_health(client):
    r = client.get("/api/system/health")
    assert r.status_code == 200 and r.json()["ok"] is True


def client_get_workspace():
    from fastapi.testclient import TestClient
    from bionexus.api.app import app
    with TestClient(app) as c:
        return c.get("/api/programs").json()


def test_spawn_plan_forwards_program_fence(monkeypatch, tmp_path):
    """The fence the creator ticked must reach the leaf campaigns."""
    import bionexus.api.launch as L
    seen = {}

    class P:
        pid = 1

        def poll(self):
            return None
    monkeypatch.setattr(L.subprocess, "Popen",
                        lambda cmd, **kw: seen.update(cmd=cmd) or P())
    monkeypatch.setattr(L, "CAMPAIGN_DIR", tmp_path)
    L._spawn_plan({"objective": "o", "autonomy": "gate",
                   "labs": [{"instrument": "bionexus-virtual-lab"}]},
                  "FenceTestProg")
    assert "--labs-json" in seen["cmd"]
    import json
    i = seen["cmd"].index("--labs-json")
    assert json.loads(seen["cmd"][i + 1])[0]["instrument"] == \
        "bionexus-virtual-lab"
    import bionexus.program as pcfg
    pcfg.delete_program("FenceTestProg")


def test_empty_fence_defaults_to_virtual_lab_poolspec():
    from bionexus.cli import _campaign_from_doc
    doc = {
        "problem": {"objective": "o", "constraints": [],
                    "success_metric": "s"},
        "hypotheses": [{"statement": "S1 binds", "candidate": "S1",
                        "assay_type": "binding", "predicted": "<= 20",
                        "predicted_value": 20.0}],
        "autonomy": "act",
    }
    cfg = _campaign_from_doc(doc)
    assert cfg.labs == [{"instrument": "bionexus-virtual-lab"}]
    doc2 = dict(doc); doc2["lab"] = {"adapter": "x:Y"}
    assert _campaign_from_doc(doc2).labs is None   # explicit single-lab
    doc3 = dict(doc)
    doc3["labs"] = [{"instrument": "labmcp-ika"}]
    assert _campaign_from_doc(doc3).labs == [{"instrument": "labmcp-ika"}]
