"""S-T2.2 — the eval leaderboard is the product pitch: read-model + endpoint."""
import json

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from bionexus.evals.harness import leaderboard_payload  # noqa: E402


def test_leaderboard_reads_committed_run():
    p = leaderboard_payload()
    assert p["available"] is True
    assert p["mean"] is not None and p["mean"] >= 0.7
    assert p["all_pass"] is True and p["failing"] == []
    # the honesty framing is the point: sub-1.0 passing tasks are flagged
    assert p["honest_deductions"], "at least one honest-deduction task"
    by = {t["task"]: t for t in p["tasks"]}
    hr = by["hit-recovery"]
    assert hr["score"] < 1.0 and hr["passed"] and hr["honest_deduction"]
    assert "abstain" in hr["notes"].lower()       # graded down for abstentions
    assert all(t["suite"] for t in p["tasks"])


def test_leaderboard_degrades_gracefully(tmp_path, monkeypatch):
    monkeypatch.setenv("BIONEXUS_EVALS_DIR", str(tmp_path))  # empty -> missing
    p = leaderboard_payload()
    assert p["available"] is False
    assert "bn eval" in p["reason"]
    assert p["tasks"] == [] and p["mean"] is None


def test_leaderboard_survives_corrupt_artifacts(tmp_path, monkeypatch):
    (tmp_path / "results.json").write_text("{not json")
    monkeypatch.setenv("BIONEXUS_EVALS_DIR", str(tmp_path))
    p = leaderboard_payload()
    assert p["available"] is False and "results.json" in p["reason"]


def test_leaderboard_reflects_failing_run(tmp_path, monkeypatch):
    (tmp_path / "results.json").write_text(json.dumps([
        {"task": "hit-recovery", "score": 0.2, "passed": False,
         "metrics": {"duration_s": 1.0}, "notes": "under bar"},
        {"task": "verdict-honesty", "score": 1.0, "passed": True,
         "metrics": {}, "notes": "ok"}]))
    monkeypatch.setenv("BIONEXUS_EVALS_DIR", str(tmp_path))
    p = leaderboard_payload()
    assert p["available"] and p["all_pass"] is False
    assert p["failing"] == ["hit-recovery"]
    assert abs(p["mean"] - 0.6) < 1e-9            # (0.2 + 1.0) / 2


def test_api_evals_endpoint():
    from bionexus.api.app import app

    with TestClient(app) as c:
        r = c.get("/api/evals")
        assert r.status_code == 200
        body = r.json()
        assert body["available"] is True
        assert body["mean"] is not None
        assert any(t["honest_deduction"] for t in body["tasks"])
