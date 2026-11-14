"""P0.1 view read-model tests: pure functions over real provenance
records, in a tmp store (never the user's data)."""
from __future__ import annotations

from pathlib import Path

import pytest

from proef.views import (dmta_counts, resolve_problem, round_markers,
                            row_status)


@pytest.fixture()
def prov_db(tmp_path):
    """A provenance store on tmp with one mini campaign branch:
    problem_defined -> 2 proposed -> filtered(1) -> lab_run ->
    hypothesis_tested(validated) + round markers."""
    from proef.adapters.store.sqlite import SqliteProvenanceStore
    from proef.core.contracts import Envelope, EventType
    from proef.core.interfaces import record_for, system_actor
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
    from proef.adapters.store.sqlite import SqliteProvenanceStore
    recs = SqliteProvenanceStore(str(prov_db)).branch_records(
        "problem/prob-aaa1")
    c = dmta_counts(recs)
    assert c["proposed"] == 2
    assert c["selected"] == 1
    assert c["submitted"] == 1 and c["runs"] == 1
    assert c["verdicts"] == 1 and c["validated"] == 1


def test_round_markers_sorted(prov_db):
    from proef.adapters.store.sqlite import SqliteProvenanceStore
    recs = SqliteProvenanceStore(str(prov_db)).branch_records(
        "problem/prob-aaa1")
    assert round_markers(recs) == [(1, ["C1", "C2"]), (2, ["C3"])]


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


def test_pipeline_cards_states(tmp_path):
    """Cards classify each hypothesis into exactly one state, in
    proposed order, with verdict/CI/margin attached."""
    from proef.adapters.store.sqlite import SqliteProvenanceStore
    from proef.core.contracts import Envelope, EventType
    from proef.core.interfaces import record_for, system_actor
    from proef.views import pipeline_cards
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


def test_reviewer_direction_aware_max_gate():
    """A max-direction verdict (observed >= gate) must NOT be flagged
    label-vs-data — the reviewer reads `direction` from the record."""
    from proef.reviewer import review_campaign
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


# ------------------------------------------------- verdict recency (P0-A)
def _recency_store(tmp_path):
    """Tracker-written branch: C-a preliminary VALIDATED then orthogonal
    confirmation REFUTES it; C-b preliminary VALIDATED then the CI straddles
    the gate -> INCONCLUSIVE. A round-1 marker froze both as validated."""
    from proef.adapters.store.sqlite import SqliteProvenanceStore
    from proef.core.contracts import Envelope, EventType
    from proef.core.hypothesis import HypothesisTracker
    from proef.core.interfaces import record_for, system_actor

    branch = "problem/prob-recency"
    store = SqliteProvenanceStore(str(tmp_path / "prov.db"))
    actor = system_actor("t")
    tracker = HypothesisTracker(store, actor)
    ha = tracker.propose("C-a beats the gate", candidate="C-a",
                         assay_type="binding", predicted="< 20",
                         predicted_value=20.0, branch_id=branch)
    hb = tracker.propose("C-b beats the gate", candidate="C-b",
                         assay_type="binding", predicted="< 20",
                         predicted_value=20.0, branch_id=branch)
    store.append(record_for(
        Envelope(experiment_branch_id=branch), EventType.lab_run, actor,
        decision={"run_id": "sim-1"}))
    for h in (ha, hb):
        h.status = "validated"
        h.observed_value, h.observed_ci = 18.0, (10.0, 19.0)
        h.evidence_run_id = "sim-1"
        tracker.record_outcome(h)
    store.append(record_for(  # round marker freezes both as validated
        Envelope(experiment_branch_id=branch), EventType.stage_transition,
        actor, decision={"stage": "round-1-complete",
                         "verdicts": {"C-a": "validated", "C-b": "validated"}}))
    # confirmation REFUTES C-a (methods disagree beyond CI overlap)
    ha.status = "refuted"
    ha.observed_value, ha.observed_ci = 45.0, (30.0, 60.0)
    ha.evidence_run_id = "sim-2"
    tracker.record_outcome(ha, extra={"confirmation": {
        "run_id": "sim-2", "primary_ic50": 18.0, "secondary_ic50": 45.0,
        "rule": "ci-overlap", "agreed": False}})
    # borderline CI: C-b abstains
    hb.status = "inconclusive"
    hb.observed_value, hb.observed_ci = 19.5, (10.0, 25.0)
    hb.evidence_run_id = None          # abstention with NO evidence run
    tracker.record_outcome(hb)
    return branch, store, tracker, ha.hypothesis_id, hb.hypothesis_id


def test_pipeline_cards_are_recency_wins(tmp_path):
    """A later REFUTED confirmation and a later abstention supersede the
    preliminary VALIDATED and the round marker that froze it — the card
    shows the FINAL verdict, not the most confident one."""
    from proef.views import pipeline_cards

    branch, store, _, ha_id, hb_id = _recency_store(tmp_path)
    cards = {c["key"]: c for c in pipeline_cards(
        store.branch_records(branch))}
    assert cards[ha_id]["state"] == "refuted"
    assert cards[ha_id]["verdict"]["observed"] == 45.0
    assert cards[hb_id]["state"] == "inconclusive"
    assert cards[hb_id]["verdict"]["ci"] == [10.0, 25.0]


def test_reviewer_audits_refuted_and_inconclusive(tmp_path):
    """The deterministic reviewer no longer skips the verdicts that matter
    most: refuted confirmations and abstentions are in verdicts_reviewed
    and their evidence is audited."""
    from proef.reviewer import review_campaign

    branch, store, _, _, _ = _recency_store(tmp_path)
    rev = review_campaign(store.branch_records(branch))
    assert rev["verdicts_reviewed"] == 2          # was 0 pre-fix
    kinds = {f["kind"] for f in rev["findings"]}
    # C-b abstention recorded without an evidence run -> warning
    assert "no-evidence" in kinds
    # C-a refuted with an evidence run that was never a recorded lab_run
    assert "evidence-unrecorded" in kinds


def test_diary_shows_refutation_and_abstention(tmp_path):
    """Every verdict renders in the swimlane diary: refuted lines, honest
    abstentions, and the inconclusive counter counts."""
    from proef.diary import build_diary_html

    branch, store, _, _, _ = _recency_store(tmp_path)
    html = build_diary_html(store.branch_records(branch), branch)
    assert "REFUTED" in html
    assert "INCONCLUSIVE" in html
    assert "inconclusive" in html          # lane status word
    assert "refuted" in html           # lane status glyph
