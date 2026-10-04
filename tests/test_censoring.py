"""Censored dose-response: a plate whose transition lies outside the
measurable window must yield an EXPLICIT abstention — never a silent
'tested' (implicit claim) and never a floor-pinned number dressed as IC50."""
import pytest

from bionexus.adapters.store.sqlite import SqliteProvenanceStore
from bionexus.core.hypothesis import (HypothesisTracker, ProblemStatement,
                                      SuccessCriteria)
from bionexus.core.interfaces import system_actor
from bionexus.labread import analyze_records
from bionexus.watch import AutoAnalysisAgent, LabEvent


def _saturated_records(cand="EG-X", doses=(0.003, 0.01, 0.03, 0.1, 0.3, 1.0)):
    """Every dose sits on the plateau: a sub-nanomolar compound on a ladder
    that starts 3 log-units too high."""
    recs = [{"well": "A1", "sample": "ctrl", "conc_um": 10, "value": 100,
             "control": True},
            {"well": "A2", "sample": "ctrl", "conc_um": 10, "value": 104,
             "control": True}]
    for i, d in enumerate(doses, start=3):
        for r in range(3):
            recs.append({"well": f"A{i}", "sample": cand, "conc_um": d,
                         "value": 499 + (i + r) % 4, "control": False})
    return recs


def test_analyze_flags_left_censoring():
    an = analyze_records(_saturated_records())
    c = an["compounds"]["EG-X"]
    assert c["left_censored"] is True
    # the pinned estimate never presents as a trustworthy number: either
    # falsy or at/below the grid floor
    assert not c["ic50_um"] or c["ic50_um"] <= 0.00105


def test_censored_plate_abstains_explicitly(tmp_path):
    """watch.handle: right- OR left-censored -> status inconclusive,
    recorded as a verdict (hypothesis_inconclusive) with the censoring
    reason in derivation.method."""
    from bionexus.labread import PlateResult
    import csv

    db = str(tmp_path / "p.db")
    store = SqliteProvenanceStore(db)
    tracker = HypothesisTracker(store, system_actor("t"))
    h = tracker.propose("EG-X is a sub-nM EGFR binder", candidate="EG-X",
                        assay_type="binding", predicted="<= 1 uM",
                        predicted_value=1.0)
    h.criteria = SuccessCriteria(metric="ic50_um", direction="min",
                                 threshold=1.0)
    # write the saturated plate where handle() can read it
    f = tmp_path / "run-1.csv"
    with f.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["Well ID", "Compound", "Conc (uM)", "RFU"])
        for r in _saturated_records():
            w.writerow([r["well"], r["sample"], r["conc_um"], r["value"]])
    msgs = []
    agent = AutoAnalysisAgent(store=store, tracker=tracker,
                              notify=msgs.append)
    agent.handle(LabEvent(kind="plate_ready", source="t", path=f))
    assert h.status == "inconclusive"
    assert h.observed_value is None            # no number is a no-number
    rec = [r for r in store.branch_records(h.branch_id)
           if r.event_type.value == "hypothesis_inconclusive"]
    assert len(rec) == 1
    _der = rec[0].decision.get("derivation") or {}
    method = (_der.get("derived") or {}).get("method", "")
    assert "left-censored" in method
    assert any("INCONCLUSIVE" in m for m in msgs)
