"""API v1: the campaign cockpit contract, over a REAL simulated campaign."""
from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from bionexus.adapters.lab.simulator import SimulatorLab  # noqa: E402
from bionexus.adapters.store.sqlite import SqliteProvenanceStore  # noqa: E402
from bionexus.api.app import app  # noqa: E402
from bionexus.autoloop import CampaignConfig, run_campaign  # noqa: E402
from bionexus.core.hypothesis import Constraint, ProblemStatement  # noqa: E402
from bionexus.flywheel import Flywheel  # noqa: E402
from bionexus.wizard_store import WizardStore  # noqa: E402

SPECS = [("AD1", 2.0, True), ("H1", 5.0, False), ("H2", 8.0, False),
         ("H3", 11.0, False), ("M1", 90.0, False)]


@pytest.fixture(scope="module")
def seeded(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("v1")
    store_path = str(tmp / "prov.db")
    store = SqliteProvenanceStore(store_path)
    hyps = [{"statement": f"{c} binds", "candidate": c,
             "assay_type": "binding", "predicted": f"{pv} uM",
             "predicted_value": pv,
             "metadata": {"predicted_sd": 0.2, "extrapolation": ad}}
            for c, pv, ad in SPECS]
    problem = ProblemStatement(objective="find IC50<=20", constraints=[
        Constraint(name="potency", description="IC50", kind="hard",
                   limit=20.0, unit="uM")])
    cfg = CampaignConfig(problem=problem, hypotheses=hyps, k=3, rounds=2,
                         autonomy="act", inbox=str(tmp / "inbox"),
                         poll_secs=0.05, seed=5,
                         flywheel=Flywheel(":memory:"))
    report = run_campaign(cfg, SimulatorLab(seed=3), store,
                          notify=lambda m: None)
    ws = WizardStore()
    eid = f"v1-{report.problem_id}"
    ws.register_agent(eid, "find IC50<=20", log="", autonomy="act")
    ws.link_problem(eid, report.problem_id)
    return {"eid": eid, "db": store_path, "report": report}


@pytest.fixture()
def client(seeded, monkeypatch):
    monkeypatch.setattr("bionexus.views.ids.PROVENANCE_DB", seeded["db"])
    with TestClient(app) as c:
        yield c


def test_list_contains_the_campaign(client, seeded):
    rows = client.get("/api/v1/campaigns").json()
    row = next(r for r in rows if r["id"] == seeded["eid"])
    assert row["title"] == "find IC50<=20" and row["autonomy"] == "act"


def test_cockpit_funnel_rounds_and_chain(client, seeded):
    d = client.get(f"/api/v1/campaigns/{seeded['eid']}").json()
    f = d["funnel"]
    assert f["proposed"] == 5 and f["judged"] == 5
    assert f["claimed"] + f["refuted"] + f["abstained"] == 5
    assert d["chain"]["verified"] is True and d["chain"]["records"] > 20
    assert len(d["rounds"]) == 2
    assert all(r["why"] and r["why"]["picks"] for r in d["rounds"])
    assert d["gate"]["threshold"] == 20.0 and d["gate"]["direction"] == "min"
    assert d["budget"]["runs_used"] >= 5
    assert d["reviewer"] is not None and d["reviewer"]["critical"] == 0


def test_states_are_the_v1_vocabulary(client, seeded):
    d = client.get(f"/api/v1/campaigns/{seeded['eid']}").json()
    states = {h["state"] for h in d["hypotheses"]}
    assert states <= {"confirmed", "validated", "abstained", "refuted",
                      "refused", "in_lab", "selected", "not_selected",
                      "proposed"}
    assert "inconclusive" not in states and "invalidated" not in states
    ab = next(h for h in d["hypotheses"] if h["state"] == "abstained")
    assert ab["verdict"]["status"] == "abstained" and ab["verdict"]["ci"]


def test_hypothesis_detail_has_events_and_derivation(client, seeded):
    d = client.get(f"/api/v1/campaigns/{seeded['eid']}").json()
    hid = next(h["id"] for h in d["hypotheses"] if h["candidate"] == "H1")
    r = client.get(f"/api/v1/campaigns/{seeded['eid']}/hypotheses/{hid}")
    assert r.status_code == 200
    h = r.json()
    assert h["candidate"] == "H1" and h["events"] and h["derivation"]
    assert any("VALIDATED" in e["text"] or "REFUTED" in e["text"]
               or "ABSTAINED" in e["text"] for e in h["events"])


def test_activity_is_newest_first_and_human_readable(client, seeded):
    a = client.get(f"/api/v1/campaigns/{seeded['eid']}/activity?limit=10").json()
    assert 0 < len(a) <= 10
    ts = [x["ts"] for x in a if x["ts"]]
    assert ts == sorted(ts, reverse=True)
    assert all(x["text"] for x in a)


def test_provenance_view_verifies(client, seeded):
    p = client.get(f"/api/v1/campaigns/{seeded['eid']}/provenance").json()
    assert p["chain"]["verified"] is True and p["records"]
    assert p["records"][0]["event"] == "problem_defined"


def test_404s_are_problem_details(client):
    r = client.get("/api/v1/campaigns/nope")
    assert r.status_code == 404
    assert r.json()["detail"]["type"] == "campaign-not-found"


def test_openapi_describes_v1():
    paths = app.openapi()["paths"]
    assert "/api/v1/campaigns/{eid}" in paths
    schemas = app.openapi()["components"]["schemas"]
    assert {"CampaignDetail", "Funnel", "Round", "Why"} <= set(schemas)


def test_system_status_for_the_trust_strip(client):
    s = client.get("/api/v1/system/status").json()
    assert s["halted"] is False and s["pending_approvals"] >= 0
    assert s["chain"]["verified"] is True and s["chain"]["records"] > 0
