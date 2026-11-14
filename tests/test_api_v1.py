"""API v1: the campaign cockpit contract, over a REAL simulated campaign."""
from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from proef.adapters.lab.simulator import SimulatorLab  # noqa: E402
from proef.adapters.store.sqlite import SqliteProvenanceStore  # noqa: E402
from proef.api.app import app  # noqa: E402
from proef.autoloop import CampaignConfig, run_campaign  # noqa: E402
from proef.core.hypothesis import Constraint, ProblemStatement  # noqa: E402
from proef.flywheel import Flywheel  # noqa: E402
from proef.paths import DATA_DIR  # noqa: E402
from proef.wizard_store import WizardStore  # noqa: E402

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
                         autonomy="act", inbox=str(DATA_DIR / "inbox"),
                         poll_secs=0.05, seed=5,
                         flywheel=Flywheel(":memory:"))
    report = run_campaign(cfg, SimulatorLab(seed=3), store,
                          notify=lambda m: None)
    ws = WizardStore()
    eid = f"v1-{report.problem_id}"
    ws.register_agent(eid, "find IC50<=20", log="", autonomy="act")
    ws.link_problem(eid, report.problem_id)
    return {"eid": eid, "db": store_path, "report": report}


@pytest.fixture(scope="module")
def seeded_ei(tmp_path_factory):
    """A campaign whose batches were chosen by EI acquisition (has an AD veto)."""
    tmp = tmp_path_factory.mktemp("v1ei")
    store = SqliteProvenanceStore(str(tmp / "prov.db"))
    hyps = [{"statement": f"{c} binds", "candidate": c,
             "assay_type": "binding", "predicted": f"{pv} uM",
             "predicted_value": pv,
             "metadata": {"predicted_sd": 0.2, "extrapolation": ad}}
            for c, pv, ad in SPECS]
    problem = ProblemStatement(objective="find IC50<=20", constraints=[
        Constraint(name="potency", description="IC50", kind="hard",
                   limit=20.0, unit="uM")])
    cfg = CampaignConfig(problem=problem, hypotheses=hyps, k=2, rounds=2,
                         autonomy="act", inbox=str(DATA_DIR / "inbox"),
                         poll_secs=0.05, seed=7, acquisition="bo-ei",
                         flywheel=Flywheel(":memory:"))
    report = run_campaign(cfg, SimulatorLab(seed=3), store,
                          notify=lambda m: None)
    ws = WizardStore()
    eid = f"ei-{report.problem_id}"
    ws.register_agent(eid, "find IC50<=20 (EI)", log="", autonomy="act")
    ws.link_problem(eid, report.problem_id)
    return {"eid": eid, "db": str(tmp / "prov.db")}


def test_acquisition_rounds_explain_picks_and_ad_veto(seeded_ei, monkeypatch):
    monkeypatch.setattr("proef.views.ids.PROVENANCE_DB", seeded_ei["db"])
    with TestClient(app) as c:
        d = c.get(f"/api/v1/campaigns/{seeded_ei['eid']}")
    assert d.status_code == 200, d.text
    r1 = d.json()["rounds"][0]["why"]
    assert r1["policy"] == "bo-ei" and r1["picks"]
    assert all(p["score"] is not None for p in r1["picks"])
    veto = next(x for x in r1["refusals"] if x["candidate"] == "AD1")
    assert "extrapolation" in veto["reason"]


@pytest.fixture()
def client(seeded, monkeypatch):
    monkeypatch.setattr("proef.views.ids.PROVENANCE_DB", seeded["db"])
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


def test_curves_return_points_fit_and_qc(client, seeded):
    d = client.get(f"/api/v1/campaigns/{seeded['eid']}").json()
    h1 = next(h for h in d["hypotheses"] if h["candidate"] == "H1")
    c = client.get(f"/api/v1/campaigns/{seeded['eid']}/hypotheses/{h1['id']}/curves").json()
    assert c["candidate"] == "H1" and c["curves"]
    cur = c["curves"][0]
    assert cur["label"] == "Primary screen" and len(cur["points"]) >= 4
    assert cur["fit"]["ic50_um"] > 0 and len(cur["fit"]["line"]) == 60
    assert cur["fit"]["ci"] and cur["z_prime"] is not None
    # a confirmed verdict is judged on the LATEST measurement: the last curve's
    # IC50 is the number the verdict shows
    last = c["curves"][-1]
    assert last["label"].startswith("Confirmation")
    assert abs(last["fit"]["ic50_um"] - h1["verdict"]["observed"]) \
        / h1["verdict"]["observed"] < 0.05


def test_status_comes_from_the_ledger_and_eliminated_excludes_tested(client, seeded):
    d = client.get(f"/api/v1/campaigns/{seeded['eid']}").json()
    assert d["status"] == "completed"
    tested = {c for r in d["rounds"] for c in r["candidates"]}
    assert not ({e["candidate"] for e in d["eliminated"]} & tested)
    row = next(r for r in client.get("/api/v1/campaigns").json()
               if r["id"] == seeded["eid"])
    assert row["status"] == "completed"


def _ensure_program(seeded):
    from proef import program as program_cfg
    program_cfg.save_program_record(
        {"program": "V1 Prog", "custom": True, "objective": "sub-20 uM binder",
         "modality": "small molecule", "metric": "ic50_um", "direction": "min",
         "gate_value": 20, "unit": "µM", "mode": "autonomous"})
    program_cfg.link_leaf("V1 Prog", seeded["eid"], campaign_root="x",
                          question="find IC50<=20")


def test_program_aggregates_its_campaigns_against_one_gate(client, seeded):
    _ensure_program(seeded)
    p = client.get("/api/v1/programs/v1-prog").json()
    assert p["campaigns"] == 1 and p["gate"]["threshold"] == 20.0
    assert p["goal"]["met"] is True and p["goal"]["claimed"] == 2
    assert p["goal"]["best"]["state"] in ("confirmed", "validated")
    assert p["goal"]["best"]["observed"] < 20          # direction-aware: lowest IC50
    assert p["campaign_list"][0]["status"] == "completed"
    assert p["results"] and all(r["campaign_id"] == seeded["eid"] for r in p["results"])
    assert client.get("/api/v1/programs/nope").status_code == 404


def test_today_surfaces_programs_attention_and_standalone(client, seeded):
    _ensure_program(seeded)
    t = client.get("/api/v1/today").json()
    assert any(p["slug"] == "v1-prog" for p in t["programs"])
    ab = [a for a in t["attention"]["abstentions"] if a["campaign_id"] == seeded["eid"]]
    assert ab and "AD1" in ab[0]["candidates"]
    assert t["attention"]["halted"] is False
    # the campaign is linked to a program, so it is not 'standalone'
    assert all(c["id"] != seeded["eid"] for c in t["standalone"])


def test_agents_and_traces_show_who_did_what(client, seeded):
    ag = client.get(f"/api/v1/campaigns/{seeded['eid']}/agents").json()
    ids = {a["id"] for a in ag}
    assert {"campaign", "reviewer"} <= ids
    camp = next(a for a in ag if a["id"] == "campaign")
    assert camp["events"] > 10 and "orchestrator" in camp["role"]
    tr = client.get(f"/api/v1/campaigns/{seeded['eid']}/provenance?actor=reviewer").json()
    assert tr["records"] and all(r["actor"] == "reviewer" for r in tr["records"])
    assert tr["records"][0]["detail"]["kind"] == "review_report"


def test_human_review_is_sealed_and_clears_the_attention_item(client, seeded):
    d = client.get(f"/api/v1/campaigns/{seeded['eid']}").json()
    ab = next(h for h in d["hypotheses"] if h["state"] == "abstained")
    before = d["chain"]["records"]
    inbox = client.get("/api/v1/inbox").json()
    assert any(i["kind"] == "review" and i["hypothesis_id"] == ab["id"] for i in inbox)
    r = client.post(f"/api/v1/campaigns/{seeded['eid']}/hypotheses/{ab['id']}/review",
                    json={"decision": "follow_up", "note": "add replicates near 20"})
    assert r.status_code == 200 and r.json()["by"] == "local-user"
    d2 = client.get(f"/api/v1/campaigns/{seeded['eid']}").json()
    assert d2["chain"]["verified"] is True and d2["chain"]["records"] == before + 1
    ab2 = next(h for h in d2["hypotheses"] if h["id"] == ab["id"])
    assert ab2["review"]["decision"] == "follow_up"
    inbox = client.get("/api/v1/inbox").json()
    assert not any(i["kind"] == "review" and i["hypothesis_id"] == ab["id"] for i in inbox)
    # ...but the decision stays visible in the history, with who decided
    hist = client.get("/api/v1/inbox?status=all").json()
    done = next(i for i in hist if i["kind"] == "review" and i["hypothesis_id"] == ab["id"])
    assert done["status"] == "reviewed" and done["decided_by"] == "local-user"
    act = client.get(f"/api/v1/campaigns/{seeded['eid']}/activity").json()
    assert any("decided to follow up" in a["text"] for a in act)


def test_gate_approval_appears_on_the_campaign_and_can_be_decided(client, seeded):
    from proef.approvals import ApprovalInbox
    from proef.paths import APPROVALS_FILE
    d = client.get(f"/api/v1/campaigns/{seeded['eid']}").json()
    aid = ApprovalInbox(str(APPROVALS_FILE)).request(
        f"screen-H9 [problem/{d['problem_id']}]", "1 well, 4 doses")
    d = client.get(f"/api/v1/campaigns/{seeded['eid']}").json()
    assert [a["id"] for a in d["awaiting_approvals"]] == [aid]
    items = client.get("/api/v1/inbox").json()
    it = next(i for i in items if i["id"] == aid)
    assert it["kind"] == "approval" and it["campaign_id"] == seeded["eid"]
    r = client.post(f"/api/v1/inbox/{aid}/decision", json={"approve": True})
    assert r.status_code == 200 and r.json()["status"] == "approved"
    assert r.json()["decided_by"] == "local-user"
    assert client.get(f"/api/v1/campaigns/{seeded['eid']}").json()["awaiting_approvals"] == []
    # the human decision is sealed in the campaign's chain, under the approver's name
    tr = client.get(f"/api/v1/campaigns/{seeded['eid']}/provenance?actor=local-user").json()
    assert any(r["detail"]["kind"] == "human_approval" and r["detail"]["approve"] for r in tr["records"])
    assert tr["chain"]["verified"] is True


def test_create_program_and_launch_a_campaign(client, monkeypatch):
    launched = {}

    def fake_spawn(doc, name):
        launched.update(doc=doc, name=name)
        return "cmp-fake-1"
    monkeypatch.setattr("proef.api.v1.programs.spawn_campaign", fake_spawn)
    import uuid
    name = f"Launch Test {uuid.uuid4().hex[:6]}"
    slug = name.lower().replace(" ", "-")
    r = client.post("/api/v1/programs", json={
        "name": name, "objective": "sub-10 uM", "gate_value": 10})
    assert r.status_code == 201 and r.json()["gate"]["label"].startswith("IC50")
    assert client.post("/api/v1/programs", json={"name": name}).status_code == 409
    c = client.post(f"/api/v1/programs/{slug}/campaigns",
                    json={"candidates": ["A-1", "A-2"], "rounds": 3})
    assert c.status_code == 201 and c.json()["id"] == "cmp-fake-1"
    assert launched["doc"]["autonomy"] == "gate"          # safe default
    assert launched["doc"]["candidates"] == "A-1,A-2" and launched["doc"]["rounds"] == 3


def test_halt_is_attributed_and_clearable(client):
    r = client.post("/api/v1/halt", json={"halted": True, "reason": "spill"})
    assert r.json()["halted"] is True and "by local-user" in r.json()["reason"]
    assert client.get("/api/v1/system/status").json()["halted"] is True
    assert client.post("/api/v1/halt", json={"halted": False}).json()["halted"] is False


def test_next_steps_are_deterministic_and_actionable(client, seeded):
    _ensure_program(seeded)
    p = client.get("/api/v1/programs/v1-prog").json()
    kinds = {n["kind"] for n in p["next_steps"]}
    assert "milestone" in kinds                     # the goal is met
    fu = [n for n in p["next_steps"] if n["kind"] == "follow_up"]
    # AD1 abstained (earlier tests may have recorded a decision on it)
    assert all(n["action"] == "launch" and n["candidates"] for n in fu)


def test_evidence_ledger_verify_anchor_and_exports(client, seeded, tmp_path, monkeypatch):
    monkeypatch.setattr("proef.anchor.ANCHORS", tmp_path / "anchors.json")
    led = client.post("/api/v1/evidence/verify").json()
    assert led["chain"]["verified"] is True and led["chain"]["records"] > 20
    camp = [b for b in led["branches"] if b["kind"] == "campaign"
            and b["campaign_id"] == seeded["eid"]]
    assert camp and camp[0]["verified"] is True
    # no anchor yet -> an honest note, no check
    a = client.get("/api/v1/evidence/anchor").json()
    assert a["anchors"] == [] and "PUBLISHED" in a["note"]
    a = client.post("/api/v1/evidence/anchor").json()
    assert len(a["anchors"]) == 1 and a["check"]["match"] is True
    assert a["check"]["appended_since_anchor"] == 0
    # exports
    base = f"/api/v1/evidence/export/{seeded['eid']}"
    assert "<html" in client.get(base + "?kind=report").text.lower()
    assert "<html" in client.get(base + "?kind=notebook").text.lower()
    eln = client.get(base + "?kind=eln")
    assert eln.status_code == 200 and "text/csv" in eln.headers["content-type"]
    assert client.get("/api/v1/evidence/export/nope").status_code == 404


def test_lab_lists_instruments_with_honest_labels_and_authority(client):
    ins = client.get("/api/v1/lab/instruments").json()
    assert ins and all("simulated" in i and "hardware_validated" in i for i in ins)
    sim = next(i for i in ins if i["id"] == "proef-virtual-lab")
    assert sim["simulated"] is True and sim["hardware_validated"] is False
    a = client.get("/api/v1/lab/authority").json()
    cols = [r["column"] for r in a["rules"]]
    assert cols[0] == "never" and cols[-1] == "autonomous"
    assert a["halt"]["halted"] is False and a["safety_rules"]


def test_authority_description_matches_what_classify_does():
    """The Lab screen shows DEFAULT_POLICY; pin it to the real classifier."""
    from proef.core.contracts import (ProtocolOp, ProtocolStep, ProtocolSubmission, ReagentSpec,
                                         SampleKind, SampleSpec, Envelope)
    from proef.governance import AuthorizationMatrix
    m = AuthorizationMatrix()

    def proto(bsl):
        return ProtocolSubmission(
            envelope=Envelope(experiment_branch_id="b"), title="assay",
            assay_type="binding", steps=[ProtocolStep(seq=1, op=ProtocolOp.dispense, params={"volume_ul": 50})],
            samples=[SampleSpec(sample_id="S", kind=SampleKind.compound,
                                concentration="1uM")],
            reagents=[ReagentSpec(name="buffer", amount="1 mL", bsl_level=bsl)])
    assert m.classify(proto(1))[0] == "autonomous"
    assert m.classify(proto(2))[0] == "human"
    assert m.classify(proto(3))[0] == "never"
    cols = [c for c, _ in AuthorizationMatrix.DEFAULT_POLICY]
    assert cols == ["never", "never", "human", "human", "autonomous"]


def test_campaign_says_whether_a_language_model_took_part(client, seeded):
    # the seeded campaign is the engine's own deterministic loop: no model anywhere
    assert client.get(f"/api/v1/campaigns/{seeded['eid']}").json()["llm"] is None


def test_llm_use_is_read_from_the_record_not_from_config():
    from types import SimpleNamespace as NS

    from proef.api.v1.campaigns import llm_use

    def rec(event, decision):
        return NS(event_type=NS(value=event), decision=decision)
    recs = [rec("hypothesis_proposed", {"predicted_by": {"source": "llm", "model": "m-1"}}),
            rec("hypothesis_proposed", {"predicted_by": {"source": "llm", "model": "m-1"}}),
            rec("hypothesis_proposed", {"predicted_by": {"source": "config"}}),
            rec("stage_transition", {"kind": "review_report_llm", "model": "openai_compat/m-1"})]
    u = llm_use(recs)
    assert u.models == ["m-1"] and u.proposed_hypotheses == 2 and u.reviewed is True
    assert llm_use(recs[2:3]) is None
    assert llm_use([rec("stage_transition", {"kind": "review_report_llm", "model": "x", "unavailable": True})]) is None


def test_system_status_reports_the_model_without_the_key(client, monkeypatch):
    for k in ("PROEF_LLM_PRESET", "PROEF_LLM_API", "PROEF_LLM_BASE_URL", "ANTHROPIC_AUTH_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.delenv("PROEF_LLM_MODEL", raising=False)
    monkeypatch.delenv("PROEF_LLM_TOKEN", raising=False)
    assert client.get("/api/v1/system/status").json()["model"]["configured"] is False
    monkeypatch.setenv("PROEF_LLM_MODEL", "some-model")
    monkeypatch.setenv("PROEF_LLM_TOKEN", "super-secret-key")
    r = client.get("/api/v1/system/status")
    assert r.json()["model"]["configured"] is True and r.json()["model"]["model"] == "some-model"
    assert "super-secret-key" not in r.text


def test_program_limits_cap_every_campaign_and_reach_the_engine_budget(client, monkeypatch):
    import uuid
    launched = {}
    monkeypatch.setattr("proef.api.v1.programs.spawn_campaign",
                        lambda doc, name: launched.update(doc=doc) or "cmp-fake-2")
    name = f"Limits Test {uuid.uuid4().hex[:6]}"
    slug = name.lower().replace(" ", "-")
    made = client.post("/api/v1/programs", json={"name": name, "limits": {
        "max_rounds": 2, "max_lab_runs": 7, "max_hypotheses": 5, "max_families": 2,
        "max_variants_per_family": 2, "breadth": 2}})
    assert made.status_code == 201 and made.json()["limits"]["max_lab_runs"] == 7
    assert client.get(f"/api/v1/programs/{slug}").json()["limits"]["breadth"] == 2
    # asking for more than the program allows is capped, not obeyed
    client.post(f"/api/v1/programs/{slug}/campaigns", json={"candidates": ["A-1"], "rounds": 8, "k": 12})
    d = launched["doc"]
    assert (d["rounds"], d["k"]) == (2, 2)
    assert (d["max_families"], d["max_variants_per_family"]) == (2, 2)
    assert d["budget"] == {"max_total_runs": 7, "max_hypotheses_total": 5}
    # asking for less is honoured
    client.post(f"/api/v1/programs/{slug}/campaigns", json={"candidates": ["A-1"], "rounds": 1, "k": 1})
    assert (launched["doc"]["rounds"], launched["doc"]["k"]) == (1, 1)
    # the engine receives a real, enforced budget
    from proef.api.launch import build_cfg
    from proef.cli import _campaign_from_doc
    cfg = _campaign_from_doc(build_cfg(d))
    assert (cfg.budget.max_total_runs, cfg.budget.max_hypotheses_total) == (7, 5)
    assert (cfg.max_families, cfg.max_variants_per_family) == (2, 2)


def test_limits_are_validated_and_old_programs_get_defaults(client):
    import uuid
    bad = client.post("/api/v1/programs", json={"name": f"Bad {uuid.uuid4().hex[:6]}", "limits": {"max_rounds": 99}})
    assert bad.status_code == 422
    from proef import program as program_cfg
    name = f"Legacy {uuid.uuid4().hex[:6]}"
    program_cfg.save_program_record({"program": name, "custom": True, "objective": "x", "modality": "small molecule",
                                     "metric": "ic50_um", "direction": "min", "gate_value": 10, "unit": "µM",
                                     "mode": "autonomous"})          # no 'limits' key: created before limits existed
    got = client.get(f"/api/v1/programs/{program_cfg._slug(name)}").json()["limits"]
    assert got == {"max_rounds": 3, "max_lab_runs": 20, "max_hypotheses": 12, "max_families": 3,
                   "max_variants_per_family": 3, "breadth": 3}


def test_a_research_plan_is_reviewed_in_the_inbox_and_removals_are_sealed(client, seeded):
    from proef.approvals import ApprovalInbox
    from proef.paths import APPROVALS_FILE
    d = client.get(f"/api/v1/campaigns/{seeded['eid']}").json()
    plan = {"n_hypotheses": 2, "families": [{
        "id": "hinge", "claim": "Reversible hinge binders work", "mechanism": "occupies the ATP site",
        "refuted_if": "IC50 > 20 uM", "confidence": 0.8, "citation": "", "citation_status": "",
        "variants": [{"hypothesis_id": "hyp-a", "candidate": "H1", "statement": "H1 binds"},
                     {"hypothesis_id": "hyp-b", "candidate": "H2", "statement": "H2 binds"}]}]}
    aid = ApprovalInbox(str(APPROVALS_FILE)).request(
        f"[problem/{d['problem_id']}] Approve the research plan: 2 hypotheses in 1 family",
        "Review what the model proposed.", payload=plan)
    # the plan rides on the approval, on the campaign and in the inbox
    waiting = client.get(f"/api/v1/campaigns/{seeded['eid']}").json()["awaiting_approvals"]
    assert waiting[0]["plan"]["families"][0]["mechanism"] == "occupies the ATP site"
    item = next(i for i in client.get("/api/v1/inbox").json() if i["id"] == aid)
    assert item["plan"]["n_hypotheses"] == 2 and item["plan"]["families"][0]["refuted_if"] == "IC50 > 20 uM"
    # approving WITH a removal: the decision data reaches the campaign process, and is sealed under the person
    r = client.post(f"/api/v1/inbox/{aid}/decision", json={"approve": True, "exclude": ["hyp-b"], "note": "H2 is a PAINS"})
    assert r.status_code == 200 and r.json()["status"] == "approved"
    state = ApprovalInbox(str(APPROVALS_FILE)).state()[aid]
    assert state["data"] == {"exclude": ["hyp-b"], "note": "H2 is a PAINS"} and state["decided_by"] == "local-user"
    tr = client.get(f"/api/v1/campaigns/{seeded['eid']}/provenance?actor=local-user").json()
    sealed = [x["detail"] for x in tr["records"] if x["detail"].get("approval_id") == aid]
    assert sealed and sealed[0]["removed"] == ["hyp-b"] and sealed[0]["note"] == "H2 is a PAINS"
    assert tr["chain"]["verified"] is True


def test_a_declined_plan_gives_the_campaign_an_honest_status():
    from types import SimpleNamespace as NS

    from proef.api.v1.campaigns import _status
    rec = lambda d: NS(event_type=NS(value="gate_decision"), decision=d, artifact=None)
    assert _status("executing", [rec({"kind": "plan_decision", "approved": False})]) == "declined"
    assert _status("executing", [rec({"kind": "plan_decision", "approved": True})]) == "executing"


def test_a_running_campaign_shows_what_it_is_waiting_for_on_its_own_page(client, monkeypatch):
    """A running campaign is not linked to its problem branch in the registry yet; it announces the branch."""
    from proef.approvals import ApprovalInbox
    from proef.paths import APPROVALS_FILE
    from proef.wizard_store import WizardStore
    eid = "running-wait-1"
    WizardStore().register_agent(eid, "wait for me", log="", autonomy="gate")          # no link_problem yet
    monkeypatch.setattr("proef.autoloop.announced_branches", lambda: {eid: "prob-announced-1"})
    aid = ApprovalInbox(str(APPROVALS_FILE)).request("[problem/prob-announced-1] Approve the research plan: 1 hypotheses in 1 family",
                                                     payload={"n_hypotheses": 1, "families": [{"id": "f", "variants": [{"hypothesis_id": "h1"}]}]})
    d = client.get(f"/api/v1/campaigns/{eid}").json()
    assert d["problem_id"] == "prob-announced-1"
    assert [a["id"] for a in d["awaiting_approvals"]] == [aid] and d["awaiting_approvals"][0]["plan"]["n_hypotheses"] == 1
    from proef.api.v1.campaigns import problem_id_for
    assert problem_id_for("x", {"agent": {"problem_id": "prob-real"}}) == "prob-real"     # a recorded id wins
