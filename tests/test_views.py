"""P0.1 view read-model tests: pure functions over real provenance
records, in a tmp store (never the user's data)."""
from __future__ import annotations

from pathlib import Path

import pytest

from bionexus.views import (dmta_counts, has_doubled_branch, leaf_pid,
                            problem_trees, resolve_problem, round_markers,
                            row_status)


@pytest.fixture()
def prov_db(tmp_path):
    """A provenance store on tmp with one mini campaign branch:
    problem_defined -> 2 proposed -> filtered(1) -> lab_run ->
    hypothesis_tested(validated) + round markers."""
    from bionexus.adapters.store.sqlite import SqliteProvenanceStore
    from bionexus.core.contracts import Envelope, EventType
    from bionexus.core.interfaces import record_for, system_actor
    db = tmp_path / "prov.db"
    store = SqliteProvenanceStore(str(db))

    def rec(branch, et, **decision):
        store.append(record_for(
            Envelope(experiment_branch_id=branch),
            et, system_actor("test"), decision=decision))

    b = "problem/prob-aaa1"
    rec(b, EventType.problem_defined, objective="find X",
        success_metric="x gate")
    rec(b, EventType.stage_transition, kind="round_start", round=1,
        candidates=["C1", "C2"])
    rec(b, EventType.hypothesis_proposed, statement="s1")
    rec(b, EventType.hypothesis_proposed, statement="s2")
    rec(b, EventType.hypotheses_filtered, decisions=[
        {"hypothesis_id": "hyp-1", "selected": True},
        {"hypothesis_id": "hyp-2", "selected": False}])
    rec(b, EventType.lab_run, run_id="run-1")
    rec(b, EventType.hypothesis_tested, hypothesis_id="hyp-1",
        verdict="validated")
    rec(b, EventType.stage_transition, kind="round_start", round=2,
        candidates=["C3"])
    return db


def test_dmta_counts(prov_db):
    from bionexus.adapters.store.sqlite import SqliteProvenanceStore
    recs = SqliteProvenanceStore(str(prov_db)).branch_records(
        "problem/prob-aaa1")
    c = dmta_counts(recs)
    assert c["proposed"] == 2
    assert c["selected"] == 1
    assert c["submitted"] == 1 and c["runs"] == 1
    assert c["verdicts"] == 1 and c["validated"] == 1


def test_round_markers_sorted(prov_db):
    from bionexus.adapters.store.sqlite import SqliteProvenanceStore
    recs = SqliteProvenanceStore(str(prov_db)).branch_records(
        "problem/prob-aaa1")
    assert round_markers(recs) == [(1, ["C1", "C2"]), (2, ["C3"])]


def test_leaf_pid_forms(tmp_path):
    # no db -> run_tree doubled convention is default for single-node
    assert has_doubled_branch("r1", tmp_path / "nope.db") is True
    assert leaf_pid("r1", "r1", tmp_path / "nope.db") == "r1-r1"
    assert leaf_pid("r1", "lf2", tmp_path / "nope.db") == "r1-lf2"
    assert leaf_pid("r1", "lf2", tmp_path) == "r1-lf2"
    # single-node leaf aliases cover both forms
    from bionexus.views import pid_aliases
    assert pid_aliases("r1", "r1") == {"r1", "r1-r1"}
    assert pid_aliases("r1", "lf2") == {"r1-lf2"}


def test_resolve_problem_from_log(tmp_path):
    logf = tmp_path / "c.log"
    logf.write_text("[agent] hypothesis X\n"
                    "CAMPAIGN COMPLETE prob-4368cca5: a=confirmed\n")
    assert resolve_problem({}, logf) == "prob-4368cca5"
    # the log's latest token WINS over stale metadata (it records the
    # problem actually registered by the agent)
    assert resolve_problem({"problem_id": "prob-1111"}, logf) == \
        "prob-4368cca5"
    # metadata is the fallback when no log exists
    assert resolve_problem({}, tmp_path / "nope.log") is None


def test_row_status_log_and_pid(tmp_path):
    logf = tmp_path / "done.log"
    logf.write_text("CAMPAIGN COMPLETE prob-1: x=confirmed\n")
    done = {"payload": {"agent": {"log": str(logf)}}, "status": "executing"}
    assert row_status(done) == "completed"
    dead = {"payload": {"agent": {"log": str(tmp_path / "x.log"),
                                  "pid": 999999999}}, "status": "executing"}
    assert row_status(dead) == "interrupted"
    leaf = {"payload": {}, "status": "verdict_recorded"}
    assert row_status(leaf) == "verdict recorded"


def test_problem_trees_shape(prov_db):
    trees, leaf_pids = problem_trees(prov_db)
    assert trees == [] and leaf_pids == set()   # no problem-tree env yet


def test_pipeline_cards_states(tmp_path):
    """Cards classify each hypothesis into exactly one state, in
    proposed order, with verdict/CI/margin attached."""
    from bionexus.adapters.store.sqlite import SqliteProvenanceStore
    from bionexus.core.contracts import Envelope, EventType
    from bionexus.core.interfaces import record_for, system_actor
    from bionexus.views import pipeline_cards
    db = tmp_path / "prov.db"
    store = SqliteProvenanceStore(str(db))

    def rec(branch, et, **decision):
        store.append(record_for(
            Envelope(experiment_branch_id=branch),
            et, system_actor("test"), decision=decision))

    b = "problem/prob-card1"
    rec(b, EventType.hypothesis_proposed, hypothesis_id="h-conf",
        candidate="C-conf", statement="C-conf — will work",
        predicted=">= 5", criteria={"threshold": 5.0})
    rec(b, EventType.hypothesis_proposed, hypothesis_id="h-ref",
        candidate="C-ref", statement="C-ref — will fail",
        criteria={"threshold": 5.0})
    rec(b, EventType.hypothesis_proposed, statement="no candidate yet",
        criteria={"threshold": 5.0})
    rec(b, EventType.hypotheses_filtered, decisions=[
        {"hypothesis_id": "h-conf", "selected": True},
        {"hypothesis_id": "h-ref", "selected": False}])
    rec(b, EventType.hypothesis_validated, hypothesis_id="h-conf",
        verdict="confirmed", observed=7.1, observed_ci=[5.9, 8.9])
    rec(b, EventType.hypothesis_invalidated, hypothesis_id="h-ref",
        verdict="refuted", observed=1.2)
    cards = pipeline_cards(SqliteProvenanceStore(str(db)).branch_records(b))
    by_key = {c["key"]: c for c in cards}
    assert len(cards) == 3
    assert by_key["h-conf"]["state"] == "confirmed"
    assert by_key["h-conf"]["verdict"]["observed"] == 7.1
    assert by_key["h-conf"]["verdict"]["margin"] in (
        "clear margin", "narrow margin", "borderline: CI spans the gate")
    assert by_key["h-conf"]["selected"] is True
    assert by_key["h-ref"]["state"] == "refuted"
    # candidate-less variant: statement becomes the label, never None
    bare = next(c for c in cards if c["key"] == "no candidate yet")
    assert bare["state"] == "proposed"
    assert "None" not in bare["head"]
    assert bare["statement"] == "no candidate yet"
    assert bare["gate_label"] is not None


def test_experiment_detail_and_workspace(tmp_path):
    """The API assemblers: experiment detail merges spec + program +
    provenance with precedence; workspace groups programs/trees/rows."""
    from bionexus import program as program_cfg
    from bionexus.adapters.store.sqlite import SqliteProvenanceStore
    from bionexus.core.contracts import Envelope, EventType
    from bionexus.core.interfaces import record_for, system_actor
    from bionexus.views import experiment_detail, workspace
    from bionexus.wizard_store import WizardStore

    ws = WizardStore()
    program_cfg.save_program_record(
        {"program": "WS-1", "custom": True, "objective": "make it strong",
         "modality": "material", "metric": "strength_mpa",
         "direction": "max", "gate_value": 70, "unit": "MPa",
         "mode": "autonomous"})
    eid = "ws-exp-1"
    ws._conn.execute(
        "INSERT OR REPLACE INTO experiments VALUES (?,?,?,?,?,?)",
        (eid, 0, 0, "executing", "make it strong", "{}"))
    ws._conn.commit()
    ws.register_agent(eid, "make it strong", log="", autonomy="act")
    ws.set_campaign_spec(eid, objective="make it strong",
                         program_slug="ws-1",
                         constraints=[{"name": "strength_mpa",
                                       "description": ">= 70 MPa"}],
                         k=2, rounds=2, autonomy="act",
                         hypothesis_source="agent", n_candidates=0,
                         modality="material")
    program_cfg.record_launch("WS-1", "prob-ws1", "make it strong")
    program_cfg.link_leaf("WS-1", eid, campaign_root="prob-ws1",
                          question="make it strong", status="executing")
    # provenance branch: problem_defined should OVERRIDE the spec
    db = tmp_path / "prov.db"
    store = SqliteProvenanceStore(str(db))
    store.append(record_for(
        Envelope(experiment_branch_id="problem/prob-ws1"),
        EventType.problem_defined, system_actor("test"),
        decision={"objective": "registered objective",
                  "constraints": [{"name": "strength_mpa",
                                   "description": ">= 70 MPa"}]}))

    detail = experiment_detail(eid, ws, db)
    assert detail["program"]["slug"] == "ws-1"
    assert detail["program"]["gate"]["value"] == 70
    assert detail["spec"]["k"] == 2
    assert detail["objective"] == "registered objective"   # provenance wins
    assert detail["counts"] is not None

    wsview = workspace(ws, db)
    prog = next(p for p in wsview["programs"] if p["slug"] == "ws-1")
    assert eid in {a["eid"] for a in prog["links"]}
    assert prog["tally"] == {"executing": 1}   # leaf links only
    # the unlinked-row groups must not contain the linked experiment
    for g in wsview["groups"].values():
        assert all(x["eid"] != eid for x in g)


def test_workspace_link_stats(tmp_path):
    """Program links carry per-experiment execution stats (runs used,
    rounds done/planned, verdict tally) so the workspace card can render
    one dense aligned row instead of the repeated objective. Verdict
    buckets: validated counts as confirmed, invalidated as refuted."""
    from bionexus import program as program_cfg
    from bionexus.adapters.store.sqlite import SqliteProvenanceStore
    from bionexus.core.contracts import Envelope, EventType
    from bionexus.core.interfaces import record_for, system_actor
    from bionexus.views import workspace
    from bionexus.wizard_store import WizardStore

    ws = WizardStore()
    program_cfg.save_program_record(
        {"program": "LS-1", "custom": True, "objective": "obj",
         "metric": "m", "direction": "min", "gate_value": 1, "unit": "u",
         "mode": "autonomous"})
    eid = "ls-exp-1"
    ws.register_agent(eid, "obj", log="", autonomy="act")
    ws.set_campaign_spec(eid, objective="obj", program_slug="ls-1",
                         k=2, rounds=2, autonomy="act",
                         hypothesis_source="config", n_candidates=2)
    program_cfg.record_launch("LS-1", "prob-ls1", "obj")
    program_cfg.link_leaf("LS-1", eid, campaign_root="prob-ls1",
                          question="obj")
    br = Envelope(experiment_branch_id="problem/prob-ls1")
    store = SqliteProvenanceStore(str(tmp_path / "prov.db"))
    store.append(record_for(br, EventType.stage_transition,
                            system_actor("test"),
                            decision={"kind": "round_start", "round": 1,
                                      "candidates": ["A", "B"]}))
    store.append(record_for(br, EventType.lab_run, system_actor("test"),
                            decision={"run_id": "r-1"}))
    store.append(record_for(br, EventType.lab_run, system_actor("test"),
                            decision={"run_id": "r-2"}))
    # A: confirmed then INVALIDATED on the same hypothesis -> refuted wins
    store.append(record_for(br, EventType.hypothesis_tested,
                            system_actor("test"),
                            decision={"hypothesis_id": "hA",
                                      "verdict": "confirmed"}))
    store.append(record_for(br, EventType.hypothesis_invalidated,
                            system_actor("test"),
                            decision={"hypothesis_id": "hA",
                                      "verdict": "invalidated"}))
    store.append(record_for(br, EventType.hypothesis_validated,
                            system_actor("test"),
                            decision={"hypothesis_id": "hB",
                                      "verdict": "validated"}))

    prog = next(p for p in workspace(ws, tmp_path / "prov.db")["programs"]
                if p["slug"] == "ls-1")
    link = next(a for a in prog["links"] if a["eid"] == eid)
    assert link["runs"] == 2
    assert link["rounds_done"] == 1 and link["rounds_planned"] == 2
    assert link["verdicts"] == {"confirmed": 1, "refuted": 1,
                                "inconclusive": 0}
    assert link["candidates"] == ["A", "B"]

    # per-program taste slice: portfolio decisions on the program's
    # branches fold into links' own accept-rate report
    from bionexus.core.contracts import Envelope as _E
    from bionexus.core.interfaces import record_for as _rf, system_actor as _sa
    store.append(record_for(
        _E(experiment_branch_id="problem/prob-ls1"),
        EventType.hypothesis_proposed, _sa("test"),
        artifact=__import__("bionexus.core.contracts", fromlist=["Artifact"])
        .Artifact(artifact_id="hT1", kind=__import__(
            "bionexus.core.contracts", fromlist=["ArtifactKind"])
            .ArtifactKind.hypothesis, uri="mem://t1",
            metadata={"candidate": "A"}),
        decision={"statement": "A binds", "candidate": "A",
                  "mechanism": "covalent"}))
    store.append(record_for(
        _E(experiment_branch_id="problem/prob-ls1"),
        EventType.hypotheses_filtered, _sa("test"),
        decision={"k": 1, "decisions": [
            {"hypothesis_id": "hT1", "selected": True, "score": 0.9,
             "reason": "top-k"}]}))
    prog = next(p for p in workspace(ws, tmp_path / "prov.db")["programs"]
                if p["slug"] == "ls-1")
    assert prog["taste"]["n"] == 1 and prog["taste"]["accepted"] == 1
    assert prog["taste"]["by_feature"]["mechanism"]["rate"] == 1.0


def test_program_card_tree(tmp_path):
    """A decomposed program attaches its problem tree: the card can
    render sub-problems as sub-trees with leaves as experiment rows."""
    from bionexus import program as program_cfg
    from bionexus.adapters.store.sqlite import SqliteProvenanceStore
    from bionexus.core.contracts import Artifact, ArtifactKind, Envelope, EventType
    from bionexus.core.interfaces import record_for, system_actor
    from bionexus.problem_tree import ProblemTree
    from bionexus.views import workspace
    from bionexus.wizard_store import WizardStore

    ws = WizardStore()
    program_cfg.save_program_record(
        {"program": "TR-1", "custom": True, "objective": "root obj",
         "metric": "m", "direction": "min", "gate_value": 1, "unit": "u",
         "mode": "autonomous"})
    t = ProblemTree.create("root obj", metric="m", gate=1.0)
    t.add(t.root.id, objective="leaf one", metric="m", gate=1.0)
    leaf = t.leaves()[0]
    store = SqliteProvenanceStore(str(tmp_path / "prov.db"))
    store.append(record_for(
        Envelope(experiment_branch_id=f"problem/{t.root.id}"),
        EventType.problem_defined, system_actor("planner"),
        decision={"problem_id": t.root.id, "objective": "root obj",
                  "environment": {"kind": "problem-tree",
                                  "tree": t.model_dump()}}))
    program_cfg.record_launch("TR-1", t.root.id, "root obj")
    eid = "tree-exp-1"
    ws.register_agent(eid, "leaf one", log="", autonomy="act")
    pid = f"{t.root.id}-{leaf.id}"
    ws._conn.execute(
        "INSERT OR REPLACE INTO experiments VALUES (?,?,?,?,?,?)",
        (eid, 0, 0, "executing", "leaf one",
         '{"agent": {"problem_id": "%s", "log": ""}}' % pid))
    ws._conn.commit()
    program_cfg.link_leaf("TR-1", eid, campaign_root=t.root.id,
                          question="leaf one")

    prog = next(p for p in workspace(ws, tmp_path / "prov.db")["programs"]
                if p["slug"] == "tr-1")
    assert prog["tree"] is not None
    assert prog["tree"]["root_id"] == t.root.id
    assert any(n["id"] == leaf.id for n in prog["tree"]["nodes"])
    # the leaf maps to its experiment for the card's clickable rows
    assert prog["tree"]["leaf_stats"].get(leaf.id, {}).get("eid") == eid


def test_reviewer_direction_aware_max_gate():
    """A max-direction verdict (observed >= gate) must NOT be flagged
    label-vs-data — the reviewer reads `direction` from the record."""
    from bionexus.reviewer import review_campaign
    from types import SimpleNamespace as NS

    def rec(et, **d):
        return NS(event_type=NS(value=et), decision=d,
                  artifact=None)

    recs = [
        rec("problem_defined", objective="maximize potency"),
        rec("lab_run", run_id="run-1"),
        rec("hypothesis_tested", hypothesis_id="h1", candidate="C1",
            verdict="validated", run_id="run-1"),
        rec("hypothesis_validated", hypothesis_id="h1", candidate="C1",
            verdict="confirmed", metric="potency_pct", direction="max",
            threshold=80.0, observed=363.2, evidence_run_id="run-1"),
    ]
    review = review_campaign(recs)
    label_findings = [f for f in review["findings"]
                      if f["kind"] == "label-vs-data"]
    assert label_findings == []
    # sanity: min-direction with the same numbers IS a contradiction
    recs_min = [recs[0], recs[1],
                rec("hypothesis_tested", hypothesis_id="h1",
                    candidate="C1", verdict="validated", run_id="run-1"),
                rec("hypothesis_validated", hypothesis_id="h1",
                    candidate="C1", verdict="confirmed", metric="ic50_um",
                    direction="min", threshold=80.0, observed=363.2,
                    evidence_run_id="run-1")]
    review_min = review_campaign(recs_min)
    assert any(f["kind"] == "label-vs-data"
               for f in review_min["findings"])
