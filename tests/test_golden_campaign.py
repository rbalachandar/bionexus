"""Golden characterization of the campaign + read-model path.

Guards the structural refactors (views / labread / watch / run_campaign
splits): the normalized provenance sequence, report and read-model output of
two fixed-seed simulator campaigns must not change. Regenerate ONLY for an
intended behaviour change:  UPDATE_GOLDEN=1 pytest tests/test_golden_campaign.py
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from proef import views
from proef.adapters.lab.simulator import SimulatorLab
from proef.adapters.store.sqlite import SqliteProvenanceStore
from proef.autoloop import CampaignConfig, run_campaign
from proef.core.hypothesis import Constraint, ProblemStatement
from proef.flywheel import Flywheel

GOLDEN = Path(__file__).parent / "golden" / "campaign.json"
_DROP = {"run_id", "evidence_run_id", "protocol_id", "id", "ts", "created_at",
         "path", "file", "sandbox_id", "contract_id", "record_id", "inbox",
         "hypothesis_id", "timestamp", "time", "elapsed", "created"}


def _norm(x):
    if isinstance(x, dict):
        return {k: _norm(v) for k, v in sorted(x.items())
                if k not in _DROP and not k.endswith("_id")}
    if isinstance(x, (list, tuple)):
        return [_norm(v) for v in x]
    if isinstance(x, float):
        return round(x, 3)
    if isinstance(x, str) and ("/" in x and "tmp" in x):
        return "<path>"
    return x


def _scenario(tmp_path, autonomy, acquisition, seed):
    specs = [("AD1", 2.0, True), ("H1", 5.0, False), ("H2", 8.0, False),
             ("H3", 11.0, False), ("M1", 90.0, False)]
    hyps = [{"statement": f"{c} binds", "candidate": c,
             "assay_type": "binding", "predicted": f"{pv} uM",
             "predicted_value": pv,
             "metadata": {"predicted_sd": 0.2, "extrapolation": ad}}
            for c, pv, ad in specs]
    problem = ProblemStatement(objective="find IC50<=20", constraints=[
        Constraint(name="potency", description="IC50", kind="hard",
                   limit=20.0, unit="uM")])
    cfg = CampaignConfig(problem=problem, hypotheses=hyps, k=3, rounds=2,
                         autonomy=autonomy, inbox=str(tmp_path),
                         poll_secs=0.05, acquisition=acquisition, seed=seed,
                         flywheel=Flywheel(":memory:"))
    store = SqliteProvenanceStore()
    report = run_campaign(cfg, SimulatorLab(seed=3), store)
    recs = store.branch_records(f"problem/{report.problem_id}")
    return {
        "report": _norm({"selected": report.selected,
                         "verdicts": report.verdicts,
                         "rounds_run": report.rounds_run,
                         "recommendations": report.recommendations}),
        "events": [[r.event_type.value, _norm(r.decision)] for r in recs],
        "tally": _norm(views.verdict_tally(recs)),
        "cards": _norm(views.pipeline_cards(recs)),
        "narrative": _norm(views.narrative_data(recs, data_dir=str(tmp_path))),
    }


def test_campaign_golden(tmp_path):
    got = {
        "observe_boei": _scenario(tmp_path / "a", "observe", "bo-ei", 7),
        "act_default": _scenario(tmp_path / "b", "act", None, 5),
    }
    got = json.loads(json.dumps(got, default=str))
    if os.environ.get("UPDATE_GOLDEN") or not GOLDEN.exists():
        GOLDEN.write_text(json.dumps(got, indent=1, sort_keys=True))
    want = json.loads(GOLDEN.read_text())
    assert got == want
