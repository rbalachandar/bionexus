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


def test_sse_watch_and_replay(tmp_path, monkeypatch):
    """watch_once diffs store state into events; record_event/replay
    give Last-Event-ID semantics."""
    from bionexus.api import sse
    from bionexus.adapters.store.sqlite import SqliteProvenanceStore
    from bionexus.core.contracts import Envelope, EventType
    from bionexus.core.interfaces import record_for, system_actor
    from bionexus.wizard_store import WizardStore

    from bionexus import program as program_cfg
    ws = WizardStore()
    program_cfg.save_program_record(
        {"program": "Sse-1", "custom": True, "objective": "objective",
         "metric": "m", "direction": "max", "gate_value": 1, "unit": "u",
         "mode": "autonomous"})
    ws.register_agent("sse-exp-1", "objective", log="", autonomy="act")
    ws.set_campaign_spec("sse-exp-1", objective="objective",
                         program_slug="sse-1", hypothesis_source="agent")
    program_cfg.record_launch("Sse-1", "prob-sse1", "objective")
    program_cfg.link_leaf("Sse-1", "sse-exp-1", campaign_root="prob-sse1",
                          question="objective")
    prov = SqliteProvenanceStore(str(tmp_path / "prov.db"))
    prov.append(record_for(
        Envelope(experiment_branch_id="problem/prob-sse1"),
        EventType.problem_defined, system_actor("test"),
        decision={"objective": "o"}))

    snap1, events1 = sse.watch_once(None, ws, prov)
    assert events1 == []                       # first tick only snapshots
    # branch grows -> a records event for that campaign
    prov.append(record_for(
        Envelope(experiment_branch_id="problem/prob-sse1"),
        EventType.lab_run, system_actor("test"), run_id="run-9"))
    snap2, events2 = sse.watch_once(snap1, ws, prov)
    assert any(e["kind"] == "records" for e in events2)

    # replay: record events, then read back after an id marker
    i1 = sse.record_event("campaign:sse-exp-1", "status", {"x": 1})
    i2 = sse.record_event("workspace", "experiment_added", {"eid": "e"})
    back = sse.replay_events(i1, {"workspace"})
    assert [e["kind"] for e in back] == ["experiment_added"]
    assert back[0]["id"] == i2


def test_live_branch_announcement(tmp_path, monkeypatch):
    """A campaign announces its branch the moment the problem is defined
    (autoloop.announce_branch); the watcher then streams that branch's
    records incrementally — no program link, payload, or log needed."""
    from bionexus import paths
    from bionexus.api import sse
    from bionexus.autoloop import announce_branch, announced_branches
    from bionexus.adapters.store.sqlite import SqliteProvenanceStore
    from bionexus.core.contracts import Envelope, EventType
    from bionexus.core.interfaces import record_for, system_actor
    from bionexus.wizard_store import WizardStore

    monkeypatch.setattr(paths, "CAMPAIGN_DIR", tmp_path / "campaigns")
    ws = WizardStore()
    ws.register_agent("cmp-live-1", "obj", log="", autonomy="act")
    prov = SqliteProvenanceStore(str(tmp_path / "prov.db"))

    # before the announcement the watcher cannot route the branch
    snap0, _ = sse.watch_once(None, ws, prov)
    assert "prob-live1" not in snap0["eid_by_pid"]

    announce_branch("cmp-live-1", "prob-live1")
    assert sse._branch_for(ws, "cmp-live-1") == "prob-live1"
    announce_branch("cmp-live-2", "prob-live2")   # merges, never clobbers
    assert announced_branches() == {"cmp-live-1": "prob-live1",
                                    "cmp-live-2": "prob-live2"}

    # records written after the announcement stream to the right campaign
    prov.append(record_for(
        Envelope(experiment_branch_id="problem/prob-live1"),
        EventType.lab_run, system_actor("test"), run_id="run-1"))
    snap1, events1 = sse.watch_once(snap0, ws, prov)
    recs = [e for e in events1 if e["kind"] == "records"]
    assert any(e["payload"]["branch"] == "problem/prob-live1" for e in recs)


def test_wizard_session_flow(tmp_path):
    """Guided wizard API: create -> design (readiness) -> execute ->
    upload -> analyze, with provenance on the wizard branch."""
    from fastapi.testclient import TestClient

    from bionexus.adapters.store.sqlite import SqliteProvenanceStore
    from bionexus.api.app import app

    with TestClient(app) as c:
        r = c.post("/api/wizard/sessions", json={
            "question": "Does S62 phosphorylation degrade c-Myc?",
            "target": "c-Myc", "claim": "causal_modification"})
        assert r.status_code == 200
        sid, eid = r.json()["sid"], r.json()["eid"]

        r = c.post(f"/api/wizard/sessions/{sid}/design", json={
            "site": "S62", "half_life": 120, "controls": ["ctrl-1"],
            "edited_frac": True, "mimetic": True,
            "mechanism": "phospho blocks degron", "citation": ""})
        assert r.status_code == 200
        body = r.json()
        assert body["readiness"]["verdict"] in ("ready", "ready_with_warnings",
                                                "blocked")

        r = c.post(f"/api/wizard/sessions/{sid}/execute")
        assert r.status_code == 200

        csv = ("sample,conc_um,value,control\n"
               "hit-1,1,10,0\nhit-1,10,50,0\nhit-1,100,90,0\n"
               "ctrl,10,5,1\n")
        r = c.post(f"/api/wizard/sessions/{sid}/upload",
                   files={"file": ("plate.csv", csv.encode())})
        assert r.status_code == 200
        assert "plate" in r.json()

        r = c.post(f"/api/wizard/sessions/{sid}/analyze",
                   json={"selected": ["hit-1"]})
        assert r.status_code == 200 and r.json()["done"] is True

        sess = c.get(f"/api/wizard/sessions/{sid}").json()
        assert sess["selected"] == ["hit-1"]
        assert sess["step"] == 6
        # provenance recorded on the wizard branch
        from bionexus.wizard_chain import wizard_branch
        recs = SqliteProvenanceStore("bionexus.db").branch_records(
            wizard_branch(eid))
        kinds = [(x.decision or {}).get("kind") for x in recs
                 if x.event_type.value == "gate_decision"]
        assert "wizard_verdict" in kinds


def test_wizard_session_links_program(tmp_path):
    """Guided wizard sessions launched from a program link the resulting
    experiment to it (program_experiments + campaign_spec)."""
    from fastapi.testclient import TestClient

    from bionexus import program as program_cfg
    from bionexus.api.app import app
    from bionexus.wizard_store import WizardStore

    ws = WizardStore()
    program_cfg.save_program_record(
        {"program": "Guide-1", "custom": True, "objective": "guided obj",
         "metric": "m", "direction": "max", "gate_value": 1, "unit": "u",
         "mode": "autonomous", "k": 3, "rounds": 1})
    with TestClient(app) as c:
        r = c.post("/api/wizard/sessions", json={
            "question": "guided question?", "target": "t",
            "claim": "causal_modification", "program": "Guide-1"})
        assert r.status_code == 200
        eid = r.json()["eid"]
        links = program_cfg.links_for("guide-1")
        assert any(l["eid"] == eid for l in links)
        spec = ws.get_campaign_spec(eid)
        assert spec and spec["program_slug"] == "guide-1"
        # the workspace nests it under the program
        data = client_get_workspace()
        prog = next(p for p in data["programs"] if p["slug"] == "guide-1")
        assert any(a["eid"] == eid for a in prog["links"])


def client_get_workspace():
    from fastapi.testclient import TestClient
    from bionexus.api.app import app
    with TestClient(app) as c:
        return c.get("/api/programs").json()


def test_program_delete(tmp_path):
    """DELETE /api/programs/{slug}: relations + program go (experiments
    survive), tombstone in provenance, 404 when already gone."""
    from bionexus import program as program_cfg
    from bionexus.adapters.store.sqlite import SqliteProvenanceStore
    from bionexus.api.app import app
    from bionexus.core.contracts import Envelope, EventType
    from bionexus.core.interfaces import record_for, system_actor
    from bionexus.wizard_store import WizardStore

    ws = WizardStore()
    program_cfg.save_program_record(
        {"program": "Del-Api", "custom": True, "objective": "o",
         "metric": "m", "direction": "max", "gate_value": 1, "unit": "u",
         "mode": "autonomous"})
    ws._conn.execute(
        "INSERT OR REPLACE INTO experiments VALUES (?,?,?,?,?,?)",
        ("del-keep", 0, 0, "failed", "kept", "{}"))
    ws._conn.commit()
    program_cfg.link_leaf("Del-Api", "del-keep", campaign_root=None,
                          question="kept")

    with TestClient(app) as c:
        r = c.delete("/api/programs/del-api")
        assert r.status_code == 200 and r.json()["deleted"] == "del-api"
        assert c.delete("/api/programs/del-api").status_code == 404
    assert ws.get_program("del-api") is None
    assert ws.program_links("del-api") == []
    assert ws._conn.execute(
        "SELECT COUNT(*) FROM experiments WHERE id='del-keep'"
    ).fetchone()[0] == 1
    recs = SqliteProvenanceStore("bionexus.db").branch_records(
        "programs/del-api")
    assert any((r.decision or {}).get("kind") == "program_deleted"
               for r in recs)


def test_delete_last_program_does_not_resurrect(tmp_path):
    """Deleting the last program must not re-import tombstoned programs
    from provenance (the auto-migration only runs on an empty table)."""
    from fastapi.testclient import TestClient

    from bionexus import program as program_cfg
    from bionexus.api.app import app

    with TestClient(app) as c:
        # create two programs, delete both
        for name in ("Resurrect-A", "Resurrect-B"):
            r = c.post("/api/programs", json={
                "program": name, "objective": "o", "custom": True,
                "metric": "m", "direction": "max", "gate_value": 1,
                "unit": "u", "mode": "autonomous"})
            assert r.status_code == 200
        assert c.delete("/api/programs/resurrect-a").status_code == 200
        assert c.delete("/api/programs/resurrect-b").status_code == 200
        # the table is now empty -> migration would run on next list:
        # tombstoned programs must stay dead
        slugs = [p["slug"] for p in program_cfg.list_programs()]
        assert "resurrect-a" not in slugs
        assert "resurrect-b" not in slugs
        # and the workspace reports none of them (other tests' programs
        # may legitimately exist in the shared data dir)
        data = c.get("/api/programs").json()
        slugs_ws = [p["slug"] for p in data["programs"]]
        assert "resurrect-a" not in slugs_ws
        assert "resurrect-b" not in slugs_ws


def test_program_delete_purge_vs_archive(tmp_path):
    """Program deletion modes: purge hard-removes linked experiments from
    the registry; archive retires them (recoverable)."""
    from bionexus import program as program_cfg
    from bionexus.wizard_store import WizardStore

    ws = WizardStore()
    program_cfg.save_program_record(
        {"program": "Purge-1", "custom": True, "objective": "o",
         "metric": "ic50_um", "direction": "min", "gate_value": 20.0,
         "unit": "uM", "mode": "autonomous"})
    ws.register_agent("purge-exp-1", "o", log="", autonomy="act")
    program_cfg.link_leaf("Purge-1", "purge-exp-1", campaign_root=None,
                          question="o")

    import bionexus.api.launch  # noqa: F401  (paths initialized)
    from bionexus.api.app import app as _  # app import for parity
    r = __import__("fastapi.testclient", fromlist=["TestClient"]) \
        .TestClient(__import__("bionexus.api.app", fromlist=["app"]).app)
    resp = r.delete("/api/programs/purge-1?purge=true")
    assert resp.status_code == 200
    assert resp.json()["purged_experiments"] == 1
    assert ws.get("purge-exp-1") is None
    assert program_cfg.list_programs() == [] or \
        all(p["slug"] != "purge-1" for p in program_cfg.list_programs())


def test_decomposed_launch_inherits_program_autonomy(tmp_path, monkeypatch):
    """Audit fix (Oct 10): _spawn_plan hardcoded --autonomy act — a
    gate-mode program must never silently spawn unattended campaigns."""
    import bionexus.api.launch as L
    seen = {}

    def fake_popen(cmd, **kw):
        seen["cmd"] = cmd

        class P:
            pid = 1

            def poll(self):
                return None
        return P()
    monkeypatch.setattr(L.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(L, "CAMPAIGN_DIR", tmp_path)
    L._spawn_plan({"objective": "o", "autonomy": "gate"}, "GateProgram-X")
    assert "gate" in seen["cmd"] and "act" not in seen["cmd"]
    L._spawn_plan({"objective": "o"}, "GateProgram-Y")   # absent -> gate
    assert seen["cmd"][-1] == "gate"
    import bionexus.program as pcfg
    pcfg.delete_program("GateProgram-X")
    pcfg.delete_program("GateProgram-Y")


def test_instruments_endpoint_lists_catalog(client):
    r = client.get("/api/instruments")
    assert r.status_code == 200
    body = r.json()
    ids = {e["id"] for e in body["instruments"]}
    assert "bionexus-virtual-lab" in ids
    for e in body["instruments"]:
        assert isinstance(e["installed"], bool)
        assert "simulated" in e


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
