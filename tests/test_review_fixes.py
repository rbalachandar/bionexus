"""Regression tests for the Nov-2026 code-review batch (see docs/ROADMAP)."""
from __future__ import annotations

import threading
from types import SimpleNamespace as NS

from bionexus.adapters.store.sqlite import SqliteProvenanceStore
from bionexus.core.contracts import Envelope, EventType
from bionexus.core.hypothesis import (HypothesisTracker, ProblemStatement,
                                      SuccessCriteria)
from bionexus.core.interfaces import record_for, system_actor
from bionexus.labread import fit_ic50_ci, replicate_ci


def _hyp(metric, threshold=20.0):
    tr = HypothesisTracker(SqliteProvenanceStore(), system_actor())
    h = tr.propose_portfolio(ProblemStatement(objective="o"), [
        {"statement": "s", "candidate": "C", "predicted": "x",
         "predicted_value": 1.0}])[0]
    h.criteria = SuccessCriteria(metric=metric, threshold=threshold)
    return tr, h


def _result(rows):
    return NS(measurements=rows, qc=NS(controls_passed=True), run_id="r1",
              instrument=None)


def _m(value, dm, unit="x"):
    return NS(sample_id="C", value=value, unit=unit, derived_metrics=dm,
              replicate=None)


def test_verdict_ci_uses_metric_keys_and_same_row():
    # non-IC50 metric: its own CI keys must veto a point estimate that
    # clears the gate (previously only ic50_ci_* keys were read)
    tr, h = _hyp("potency_pct", threshold=50.0)
    h.criteria.direction = "max"
    tr.verdict(h, _result([_m(60.0, {"potency_pct": 60.0,
                                     "potency_pct_ci_low": 40.0,
                                     "potency_pct_ci_high": 80.0})]))
    assert h.status == "inconclusive" and h.observed_ci == (40.0, 80.0)
    # two rows: the CI must come from the row the value came from
    tr, h = _hyp("ic50_um", threshold=20.0)
    h.criteria = SuccessCriteria(metric="ic50_um", threshold=20.0)
    tr.verdict(h, _result([
        _m(5.0, {"ic50_um": 5.0, "ic50_ci_low": 4.0, "ic50_ci_high": 6.0}),
        _m(500.0, {"ic50_ci_low": 400.0, "ic50_ci_high": 600.0})]))
    assert h.observed_ci == (4.0, 6.0) and h.status == "validated"


def test_verdict_records_preregistration_flag():
    store = SqliteProvenanceStore()
    tr = HypothesisTracker(store, system_actor())
    h = tr.propose_portfolio(ProblemStatement(objective="o"), [
        {"statement": "s", "candidate": "C", "predicted": "x",
         "predicted_value": 1.0}])[0]
    h.criteria = None
    tr.verdict(h, _result([_m(5.0, {})]), threshold=20.0)
    ev = [r.decision for r in store.branch_records(h.branch_id)
          if r.decision and "criteria_preregistered" in r.decision]
    assert ev and ev[-1]["criteria_preregistered"] is False


def test_failing_on_verdict_hook_is_logged_not_silent(caplog):
    tr, h = _hyp("ic50_um")
    tr.on_verdict = lambda hh: 1 / 0
    with caplog.at_level("WARNING"):
        tr.verdict(h, _result([_m(5.0, {"ic50_um": 5.0})]))
    assert "NOT fed to the flywheel" in caplog.text


def test_replicate_ci_small_n_is_t_interval_not_bootstrap():
    lo, hi = replicate_ci([10.0, 12.0, 14.0])
    # t(0.975, df=2)=4.303 -> mean 12 +- 4.303*2/sqrt(3) = +-4.97
    assert abs((hi - lo) / 2 - 4.969) < 0.01
    assert replicate_ci([1.0, 2.0]) is None


def test_ic50_ci_is_wider_with_df_correction():
    ci = fit_ic50_ci([(0.5, 7), (2, 26), (10, 111), (40, 267)], None)
    assert ci["ci_low"] < 17          # was 20.3 before the df correction


def test_ceiling_pinned_ic50_is_right_censored():
    from bionexus.labread import analyze_records
    recs = [{"well": f"A{i}", "sample": "W", "control": False, "conc_um": c, "value": v}
            for i, (c, v) in enumerate([(0.5, 0.2), (2, 0.4), (10, 0.9),
                                        (40, 1.8)], 1)]
    recs += [{"well": "B1", "sample": "ctrl", "control": True, "conc_um": None, "value": 0.1},
             {"well": "B2", "sample": "ctrl", "control": True, "conc_um": None, "value": 0.1}]
    out = analyze_records(recs, max_response=100.0)
    assert out["compounds"]["W"]["right_censored"] is True


def test_docker_env_flags_precede_image():
    from bionexus.adapters.sandbox.docker import DockerSandbox

    class R:
        binary = "docker"

        def run(self, *a, input=None):
            self.args = list(a)
            return "cid"

        def run_capped(self, *a, **k):
            return (0, "", False)

        def ok(self, *a):
            return True
    r = R()
    DockerSandbox(image="img:1", runner=r, env={"K": "V"}, read_only=True)
    a = r.args
    assert a.index("-e") < a.index("img:1") < a.index("sleep")
    assert "--read-only" in a and a.index("--read-only") < a.index("img:1")


def test_concurrent_writers_do_not_fork_the_chain(tmp_path):
    db = str(tmp_path / "p.db")

    def writer():
        st = SqliteProvenanceStore(db)       # own connection, like a CLI
        for _ in range(15):
            st.append(record_for(Envelope(experiment_branch_id="b"),
                                 EventType.stage_transition, system_actor()))
    ts = [threading.Thread(target=writer) for _ in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    st = SqliteProvenanceStore(db)
    assert len(st.branch_records("b")) == 60
    assert st.verify_chain() == []


def test_api_refuses_cross_origin_writes_and_requires_token(monkeypatch):
    from fastapi.testclient import TestClient
    from bionexus.api.app import app
    c = TestClient(app)
    r = c.post("/api/halt", headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    monkeypatch.setenv("BIONEXUS_API_TOKEN", "s3cret")
    assert c.post("/api/halt").status_code == 401
    ok = c.post("/api/halt", headers={"X-BioNexus-Token": "s3cret"})
    assert ok.status_code != 401
    assert c.get("/api/system/health",
                 headers={"Host": "evil.example"}).status_code == 403


def test_budget_fails_closed_when_store_unreadable():
    import pytest
    from bionexus.autoloop import ResourceBudget

    class Broken:
        def branch_records(self, b):
            raise RuntimeError("db locked")
    with pytest.raises(RuntimeError):
        ResourceBudget().lab_runs_used(Broken(), "p")
