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
