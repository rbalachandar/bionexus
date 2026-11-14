"""A person submits a measured plate to a campaign: judged by the campaign's
pre-registered criteria through the engine's own verdict code, only for open
hypotheses, sealed under their name, idempotent per file digest."""
import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from proef.adapters.store.sqlite import SqliteProvenanceStore  # noqa: E402
from proef.api.app import app  # noqa: E402
from proef.core.contracts import Actor, ActorKind  # noqa: E402
from proef.core.hypothesis import (Constraint, HypothesisTracker, ProblemStatement,  # noqa: E402
                                      SuccessCriteria)
from proef.wizard_store import WizardStore  # noqa: E402

PLATE = ("well,sample,conc_um,value\nA1,blank,0,5\nA2,blank,0,5\nA3,pos,0,95\nA4,pos,0,95\n"
         "B1,C1,0.1,10\nB2,C1,1,50\nB3,C1,10,90\nC1,BORD,3,15\nC2,BORD,10,45\nC3,BORD,30,85\n"
         "D1,STRAY,1,20\nD2,STRAY,10,60\nD3,STRAY,30,90\n")
PID = "prob-resultsv1"


@pytest.fixture()
def camp(tmp_path, monkeypatch):
    db = str(tmp_path / "prov.db")
    store = SqliteProvenanceStore(db)
    t = HypothesisTracker(store, Actor(kind=ActorKind.agent, id="designer"))
    t.define_problem(ProblemStatement(problem_id=PID, objective="find IC50<=10", constraints=[
        Constraint(name="potency", description="IC50", kind="hard", limit=10.0, unit="uM")]))
    crit = SuccessCriteria(metric="ic50_um", direction="min", threshold=10.0)
    for c in ("C1", "BORD", "WAITING", "DONE"):
        t.propose(f"{c} binds", c, "binding", "5 uM", 5.0, criteria=crit, branch_id=f"problem/{PID}")
    done = next(h for h in t.hypotheses.values() if h.candidate == "DONE")
    done.status, done.observed_value, done.observed_ci = "validated", 2.0, (1.0, 3.0)
    t.record_outcome(done)
    ws = WizardStore()
    eid = f"res-{tmp_path.name}"
    ws.register_agent(eid, "find IC50<=10", log="", autonomy="observe")
    ws.link_problem(eid, PID)
    monkeypatch.setattr("proef.views.ids.PROVENANCE_DB", db)
    with TestClient(app) as c:
        yield c, eid, db


def _post(c, eid, dry, origin="measured", content=PLATE, name="plate.csv"):
    return c.post(f"/api/v1/campaigns/{eid}/results", files={"file": (name, content)},
                  data={"dry_run": str(dry).lower(), "origin": origin})


def test_preview_writes_nothing_and_says_what_would_happen(camp):
    c, eid, db = camp
    before = len(SqliteProvenanceStore(db).branch_records(f"problem/{PID}"))
    p = _post(c, eid, True).json()
    assert {m["candidate"] for m in p["matches"]} == {"C1", "BORD"}
    assert p["matches"][0]["gate"] == "ic50_um ≤ 10"
    assert p["waiting_for_data"] == ["WAITING"] and p["in_file_only"] == ["STRAY"]
    assert p["already_submitted"] is False and p["z_prime"] is not None
    assert len(SqliteProvenanceStore(db).branch_records(f"problem/{PID}")) == before


def test_submit_judges_open_hypotheses_only_and_seals_under_the_person(camp):
    c, eid, db = camp
    out = _post(c, eid, False).json()
    got = {v["candidate"]: v["status"] for v in out["verdicts"]}
    assert got["C1"] == "validated" and got["BORD"] in ("invalidated", "inconclusive")
    assert "DONE" not in got and "WAITING" not in got          # judged stays judged; no data stays open
    s = SqliteProvenanceStore(db)
    recs = s.branch_records(f"problem/{PID}")
    sub = next(r for r in recs if (r.decision or {}).get("kind") == "results_submitted")
    assert sub.actor.id == "local-user" and sub.decision["evidence_origin"] == "measured"
    verdicts = [r for r in recs if r.event_type.value.startswith("hypothesis_") and (r.decision or {}).get("evidence_run_id") == out["run_id"]]
    assert len(verdicts) == 2 and all(v.actor.id == "local-user" for v in verdicts)
    assert s.verify_chain(branch_id=f"problem/{PID}") == []
    # the evidence curve and the activity line exist for a submitted plate
    hid = next(h["id"] for h in c.get(f"/api/v1/campaigns/{eid}").json()["hypotheses"] if h["head"] == "C1")
    cv = c.get(f"/api/v1/campaigns/{eid}/hypotheses/{hid}/curves").json()
    assert cv["curves"] and cv["curves"][0]["fit"]["ic50_um"] and len(cv["curves"][0]["points"]) == 3
    assert any("submitted a plate (plate.csv)" in a["text"] for a in c.get(f"/api/v1/campaigns/{eid}/activity").json())
    # the cockpit now shows the new verdict
    d = c.get(f"/api/v1/campaigns/{eid}").json()
    assert any(h["candidate"] == "C1" and h["verdict"]["status"] == "validated" for h in d["hypotheses"])


def test_same_file_cannot_be_submitted_twice(camp):
    c, eid, _ = camp
    assert _post(c, eid, False).status_code == 200
    r = _post(c, eid, False)
    assert r.status_code == 409 and r.json()["detail"]["type"] == "already-submitted"
    assert _post(c, eid, True).json()["already_submitted"] is True


def test_proxy_evidence_cannot_judge(camp):
    c, eid, _ = camp
    r = _post(c, eid, False, origin="simulated")
    assert r.status_code == 422 and r.json()["detail"]["type"] == "proxy-evidence"


def test_file_with_nothing_for_this_campaign_is_refused(camp):
    c, eid, _ = camp
    other = PLATE.replace("C1", "X1").replace("BORD", "X2").replace("STRAY", "X3")
    r = _post(c, eid, False, content=other)
    assert r.status_code == 409 and r.json()["detail"]["type"] == "nothing-to-judge"


def test_non_csv_and_unreadable_are_typed(camp):
    c, eid, _ = camp
    assert _post(c, eid, True, name="x.xlsx").json()["detail"]["type"] == "rejected-upload"
    assert _post(c, eid, True, content="not a plate\n,,\n").status_code == 422


def test_hand_run_campaign_registers_the_gate_then_judges_a_submitted_plate(tmp_path, monkeypatch):
    from proef import program as program_cfg
    db = str(tmp_path / "prov.db")
    monkeypatch.setattr("proef.views.ids.PROVENANCE_DB", db)
    name = f"Hand Prog {tmp_path.name}"
    program_cfg.save_program_record(
        {"program": name, "custom": True, "objective": "sub-10 uM binder", "modality": "small molecule",
         "metric": "ic50_um", "direction": "min", "gate_value": 10, "unit": "µM", "mode": "autonomous"})
    slug = program_cfg._slug(name)
    with TestClient(app) as c:
        bad = c.post(f"/api/v1/programs/{slug}/campaigns", json={"mode": "hand", "candidates": []})
        assert bad.status_code == 422 and bad.json()["detail"]["type"] == "candidates-required"
        made = c.post(f"/api/v1/programs/{slug}/campaigns",
                      json={"mode": "hand", "candidates": ["C1", "BORD", "C1", " "], "objective": "bench plate 1"})
        assert made.status_code == 201 and made.json()["status"] == "awaiting_results"
        eid = made.json()["id"]
        d = c.get(f"/api/v1/campaigns/{eid}").json()
        assert d["status"] == "awaiting_results" and d["autonomy"] == "observe"
        assert sorted(h["head"] for h in d["hypotheses"]) == ["BORD", "C1"]      # de-duplicated
        assert d["gate"]["threshold"] == 10
        steps = c.get(f"/api/v1/programs/{slug}").json()["next_steps"]
        assert any(s["kind"] == "submit_results" and s["campaign_id"] == eid for s in steps)
        out = _post(c, eid, False).json()
        assert {v["candidate"]: v["status"] for v in out["verdicts"]}["C1"] == "validated"
        assert c.get(f"/api/v1/campaigns/{eid}").json()["status"] == "completed"
