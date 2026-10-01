"""The Anthropic-ART-inspired trio: graveyard read-model, taste
distillation, and the sweep fan-out harness."""
from pathlib import Path

from bionexus.adapters.lab.simulator import SimulatorLab
from bionexus.adapters.store.sqlite import SqliteProvenanceStore
from bionexus.core.contracts import Artifact, ArtifactKind, Envelope, EventType
from bionexus.core.interfaces import record_for, system_actor


def _seed_portfolio(store, base="prob-taste"):
    """One branch: 3 proposed hypotheses (rich vs bare), filter takes 2.
    Records mirror the engine's shape: hypothesis_proposed carries the
    hypothesis artifact (id = hypothesis_id, metadata.candidate)."""
    br = Envelope(experiment_branch_id=f"problem/{base}")
    ids = {}
    proposals = []
    for cid, extra in (("RICH-1", {"mechanism": "covalent Cys",
                                   "refutation_condition": "Cys mut loses "
                                   "activity",
                                   "citation": "PMID:1",
                                   "citation_status": "verified"}),
                       ("BARE-1", {}),
                       ("BARE-2", {})):
        hid = f"hyp-{base}-{cid}"
        ids[cid] = hid
        proposals.append(record_for(
            Envelope(experiment_branch_id=f"problem/{base}"),
            EventType.hypothesis_proposed, system_actor("test"),
            artifact=Artifact(artifact_id=hid, kind=ArtifactKind.hypothesis,
                              uri=f"mem://{base}/{hid}",
                              metadata={"candidate": cid}),
            decision={"statement": f"{cid} binds", "candidate": cid,
                      "predicted": "<= 20", **extra}))
    store.append(proposals[0])
    store.append(proposals[1])
    store.append(proposals[2])
    store.append(record_for(
        br, EventType.hypotheses_filtered, system_actor("test"),
        decision={"k": 2, "decisions": [
            {"hypothesis_id": ids["RICH-1"], "selected": True,
             "score": 0.9, "reason": "top-k by score"},
            {"hypothesis_id": ids["BARE-1"], "selected": False,
             "score": 0.5, "reason": "below cut"},
            {"hypothesis_id": ids["BARE-2"], "selected": False,
             "score": 0.5, "reason": "below cut"}]}))
    return ids


def test_graveyard_read_model(tmp_path):
    """experiment_detail.eliminated lists rejected hypotheses with the
    filter's recorded reasons (latest decision per candidate wins)."""
    from bionexus.views import experiment_detail
    from bionexus.wizard_store import WizardStore

    ws = WizardStore()
    ws.register_agent("gy-exp-1", "obj", log="", autonomy="act")
    store = SqliteProvenanceStore(str(tmp_path / "prov.db"))
    _seed_portfolio(store, base="prob-gy")
    ws._conn.execute(
        "INSERT OR REPLACE INTO experiments VALUES (?,?,?,?,?,?)",
        ("gy-exp-1", 0, 0, "executing", "obj",
         '{"agent": {"problem_id": "prob-gy", "log": ""}}'))
    ws._conn.commit()
    d = experiment_detail("gy-exp-1", ws, tmp_path / "prov.db")
    elim = {e["candidate"]: e for e in d["eliminated"]}
    assert set(elim) == {"BARE-1", "BARE-2"}
    assert elim["BARE-1"]["reason"] == "below cut"
    assert elim["BARE-1"]["score"] == 0.5
    assert "RICH-1" not in elim


def test_taste_report_and_amendments(tmp_path):
    """Taste distillation: accept-rate deltas by feature, deterministic
    advisory amendments; rich-vs-bare seeds make mechanism/citation the
    winning features and surface the never-selected bare pattern."""
    from bionexus.taste import render_taste, taste_report

    store = SqliteProvenanceStore(str(tmp_path / "prov.db"))
    for i in range(4):            # 4 portfolios: enough sample for deltas
        _seed_portfolio(store, base=f"prob-taste-{i}")
    rep = taste_report(tmp_path / "prov.db")
    assert rep["n"] == 12 and rep["accepted"] == 4
    assert rep["by_feature"]["mechanism"]["rate"] == 1.0
    assert rep["by_feature"]["mechanism"]["rate_without"] == 0.0
    text = render_taste(rep)
    assert "advisory" in text
    assert any("mechanism" in a for a in rep["amendments"])


def test_sweep_fan_and_rollup(tmp_path):
    """Sweep partitions the pool across shards, merges verdicts, and
    writes a sweep-rollup record on the parent branch."""
    from bionexus.core.hypothesis import ProblemStatement
    from bionexus.sweep import run_sweep

    store = SqliteProvenanceStore(str(tmp_path / "prov.db"))
    problem = ProblemStatement(objective="find potent compounds",
                               problem_id="prob-sweep")
    cands = [f"S-{i:02d}" for i in range(1, 7)]
    res = run_sweep(problem, cands, lambda: SimulatorLab(seed=3), store,
                    fan=3, k_per_shard=2, threshold=20.0, seed=3)
    assert res["verdicts"], "no verdicts recorded"
    assert sum(res["tally"].values()) == len(res["verdicts"])
    # every candidate appears in exactly one shard
    shard_cands = [c for s in res["shards"] for c in s["candidates"]]
    assert sorted(shard_cands) == cands
    # roll-up record on the parent branch
    recs = store.branch_records("problem/prob-sweep")
    roll = [r for r in recs
            if (r.decision or {}).get("kind") == "sweep-rollup"]
    assert len(roll) == 1
    assert roll[0].decision["fan"] == 3
    assert set(roll[0].decision["tally"]) == set(res["tally"])
    assert len(roll[0].decision["shards"]) == 3
    shard_branches = [f"problem/{s['problem_id']}" for s in res["shards"]]
    for sb in shard_branches:
        assert store.branch_records(sb), f"shard branch empty: {sb}"
