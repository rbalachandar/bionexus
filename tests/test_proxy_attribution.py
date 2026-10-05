"""The proxy ladder (Goodhart guard) + attribution panel (bn why, admet why)."""
import pytest

import subprocess
import sys
from pathlib import Path

from bionexus.core.hypothesis import SuccessCriteria
from bionexus.proxy import chain, distance, evidence_line

REPO = Path(__file__).parent.parent


def test_ladder_walks_to_clinical():
    assert chain("ic50_um") == ["ic50_um", "target_engagement",
                                "cellular_efficacy", "animal_efficacy",
                                "clinical_efficacy"]
    d = distance("ic50_um")
    assert d["rungs"] == 4 and d["resolved"]
    assert "4 rungs" in evidence_line("ic50_um")


def test_declared_proxy_of_overrides_first_rung():
    d = distance("ic50_um", proxy_of="cellular_efficacy")
    assert d["chain"][1] == "cellular_efficacy" and d["rungs"] == 3


def test_unresolved_chain_is_reported_not_zeroed():
    d = distance("mystery_assay")           # not on the ladder
    assert d["resolved"] is False and d["rungs"] is None
    assert "unresolved" in evidence_line("mystery_assay")


def test_criteria_carry_proxy_of_in_the_chain_payload():
    crit = SuccessCriteria(metric="ic50_um", direction="min", threshold=10.0)
    assert crit.model_dump()["proxy_of"] is None
    assert crit.evidence()["rungs"] == 4
    assert "4 rungs" in crit.evidence_line()


def test_program_rollup_prints_evidence_distance():
    from bionexus.views import program_verdict
    trees = [{"root_id": "r",
              "nodes": [{"id": "r", "parent": None, "status": "achieved",
                         "metric": "ic50_um", "objective": "potent"}],
              "rollup": {"r": "achieved"}}]
    v = program_verdict(trees)
    assert v["evidence_distance"] and "4 rungs" in v["evidence_distance"]
    assert "clinical" in v["evidence_distance"]


def test_card_gate_label_carries_rungs():
    from bionexus.adapters.store.sqlite import SqliteProvenanceStore
    from bionexus.core.contracts import Envelope, EventType
    from bionexus.core.interfaces import record_for, system_actor
    from bionexus.views import pipeline_cards

    store = SqliteProvenanceStore(":memory:")
    env = Envelope(experiment_branch_id="problem/p-x")
    crit = SuccessCriteria(metric="ic50_um", direction="min",
                           threshold=25.0).model_dump()
    store.append(record_for(env, EventType.hypothesis_proposed,
                            system_actor("t"),
                            decision={"hypothesis_id": "h-1",
                                      "candidate": "X", "statement": "X",
                                      "criteria": crit, "predicted": "<=25"}))
    store.append(record_for(env, EventType.hypothesis_validated,
                            system_actor("t"),
                            decision={"hypothesis_id": "h-1",
                                      "candidate": "X", "verdict": "validated",
                                      "observed": 3.0,
                                      "evidence": distance("ic50_um")}))
    card = next(c for c in pipeline_cards(store.branch_records("problem/p-x"))
                if c["candidate"] == "X")
    assert "4 proxy rungs from clinical" in card["gate_label"]
    assert card["evidence"]["rungs"] == 4


TRAIN = ("smiles,value\nCCO,6.0\nCCCO,9.0\nCCCCO,12.0\nCCN,7.0\n"
         "CCCN,10.0\nCCCCN,13.0\nCCCCCO,15.0\nCCCCCO,15.5\n")


def test_cli_why_char_ridge(tmp_path):
    data = tmp_path / "train.csv"
    data.write_text(TRAIN)
    r = subprocess.run(
        [sys.executable, "-m", "bionexus.cli", "why", "char-ridge",
         str(data), "CCCCO", "c1ccccc1O"],
        capture_output=True, text=True, cwd=REPO)
    assert r.returncode == 0, r.stderr
    assert "prediction=" in r.stdout
    assert "in-domain" in r.stdout            # near chemistry: spared
    assert "EXTRAPOLATION" in r.stdout       # aromatic: flagged
    assert "caveat:" in r.stdout             # hashed-slot honesty


def test_cli_why_morgan_rf(tmp_path):
    pytest.importorskip("rdkit")
    pytest.importorskip("sklearn")
    data = tmp_path / "train.csv"
    data.write_text(TRAIN)
    r = subprocess.run(
        [sys.executable, "-m", "bionexus.cli", "why", "morgan-rf",
         str(data), "CCCCO"], capture_output=True, text=True, cwd=REPO)
    assert r.returncode == 0, r.stderr
    assert "importance-weighted-bits" in r.stdout
    assert "folded Morgan bits" in r.stdout   # stated limitation


def test_admet_tool_carries_why():
    from bionexus.core.interfaces import system_actor
    from bionexus.toolkit import AgentToolkit

    tk = AgentToolkit(None, None, system_actor("tk"), branch_id="why")
    out = tk.executors()["predict_admet"]("CCOC=O")
    assert "why" in out and out["why"]["method"] == "triggered-rules"
    assert isinstance(out["why"]["reasons"], list) and out["why"]["reasons"]
