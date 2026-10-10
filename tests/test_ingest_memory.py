"""S-T1.3 institutional memory: ELN CSV -> flywheel + provenance chain.

`bn ingest` is the inverse of `bn prove --eln`. The contract: what the
lab killed BEFORE BioNexus must show up in ALREADY RULED OUT and drag
family priors — stamped imported, sealed-checksummed, nothing silently
dropped.
"""
from pathlib import Path

from bionexus.adapters.store.sqlite import SqliteProvenanceStore
from bionexus.core.contracts import Envelope, EventType
from bionexus.core.hypothesis import Constraint, HypothesisTracker, \
    ProblemStatement
from bionexus.core.interfaces import record_for, system_actor
from bionexus.eln import export_eln
from bionexus.flywheel import Flywheel
from bionexus.ingest import ingest_eln


def _exported_chain(tmp_path):
    store = SqliteProvenanceStore(":memory:")
    tr = HypothesisTracker(store, system_actor("t"))
    prob = ProblemStatement(objective="legacy", constraints=[Constraint(
        name="potency", description="d", kind="hard", limit=60.0, unit="uM")])
    tr.define_problem(prob)
    branch = f"problem/{prob.problem_id}"
    hids = {}
    for cand, outcome, obs in (("OLD-DEAD", "invalidated", 140.0),
                               ("OLD-DEAD2", "invalidated", 120.0),
                               ("OLD-GOOD", "validated", 8.0)):
        h = tr.propose(statement=f"{cand} binds", candidate=cand,
                      assay_type="binding", predicted="<=60",
                      predicted_value=60.0, branch_id=branch)
        hids[cand] = h.hypothesis_id
        ev = (EventType.hypothesis_invalidated if outcome == "invalidated"
              else EventType.hypothesis_validated)
        store.append(record_for(
            Envelope(experiment_branch_id=branch), ev, system_actor("t"),
            decision={"hypothesis_id": hids[cand], "candidate": cand,
                      "family": "warhead-A", "verdict": outcome,
                      "observed": obs, "observed_ci": [obs * 0.8, obs * 1.2]}))
    csv_path = tmp_path / "legacy.csv"
    export_eln(store.branch_records(branch), csv_path)
    return csv_path, branch


def test_roundtrip_prove_then_ingest(tmp_path):
    csv_path, _ = _exported_chain(tmp_path)
    fw = Flywheel(str(tmp_path / "fw.db"))
    store2 = SqliteProvenanceStore(":memory:")
    rep = ingest_eln(csv_path, flywheel=fw, store=store2,
                     problem_id="imported-legacy")
    assert rep["rows"] > 0 and rep["ingested"] == 3
    assert rep["checksum_match"] is True
    negs = {n["candidate"] for n in fw.negative_summary()}
    assert {"OLD-DEAD", "OLD-DEAD2"} <= negs          # lab memory restored
    assert fw.family_prior("warhead-A") < 1.0      # prior drags honestly
    recs = store2.branch_records("external/legacy")
    assert len(recs) == rep["provenance_written"]
    kinds = {(r.decision or {}).get("kind") for r in recs}
    assert kinds == {"external_outcomes_imported", "external_outcome"}
    imported = [r.decision for r in recs
                if (r.decision or {}).get("kind") == "external_outcome"]
    assert all(d["imported"] and "eln:legacy.csv" in d["data_origin"]
               for d in imported)
    assert all("warhead-A" == d["family"] for d in imported)
    assert store2.verify_chain("external/legacy") == []


def test_edited_after_export_is_loud(tmp_path):
    csv_path, _ = _exported_chain(tmp_path)
    csv_path.write_text(
        csv_path.read_text().replace("140.0", "0.001"))  # tamper
    fw = Flywheel(str(tmp_path / "fw2.db"))
    rep = ingest_eln(csv_path, flywheel=fw, store=None)
    assert rep["checksum_match"] is False
    assert any("seal" in s["reason"] or "EDITED" in s["reason"].upper()
               or "edited" in s["reason"] for s in rep["skipped"])


def test_simple_lab_table_aliases(tmp_path):
    p = tmp_path / "lab.csv"
    p.write_text("compound,outcome,ic50_uM,family,assay_type\n"
                 "X-1,refuted,220,series-7,binding\n"
                 "X-2,hit,3.1,series-7,binding\n")
    fw = Flywheel(str(tmp_path / "fw3.db"))
    rep = ingest_eln(p, flywheel=fw, store=None)
    assert rep["ingested"] == 2
    assert {n["candidate"] for n in fw.negative_summary()} == {"X-1"}


def test_nothing_silently_dropped(tmp_path):
    p = tmp_path / "dirty.csv"
    p.write_text("candidate,verdict,observed_uM\n"
                 "D-1,bog_word,10\n"          # unknown verdict -> reported
                 ",refuted,10\n"              # verdict w/o candidate -> reported
                 "D-2,refuted,10\n"
                 "D-3,,\n")                   # structural row -> silently OK
    fw = Flywheel(str(tmp_path / "fw4.db"))
    rep = ingest_eln(p, flywheel=fw, store=None)
    assert rep["ingested"] == 1
    reasons = [s["reason"] for s in rep["skipped"]]
    assert any("unknown verdict" in r for r in reasons)
    assert any("no candidate" in r for r in reasons)
    assert not any("D-3" in r for r in reasons)


def test_dry_run_writes_nothing(tmp_path):
    csv_path, _ = _exported_chain(tmp_path)
    fw = Flywheel(str(tmp_path / "fw5.db"))
    store2 = SqliteProvenanceStore(":memory:")
    rep = ingest_eln(csv_path, flywheel=fw, store=store2, dry_run=True)
    assert rep["ingested"] == 3 and rep["provenance_written"] == 0
    assert fw.negative_summary() == []
    assert store2.branch_records("external/legacy") == []


def test_cli_ingest_wired(tmp_path):
    import subprocess, sys
    csv_path, _ = _exported_chain(tmp_path)
    out = subprocess.run(
        [sys.executable, "-m", "bionexus.cli", "ingest", str(csv_path),
         "--flywheel-db", str(tmp_path / "fw6.db"), "--no-chain"],
        capture_output=True, text=True, cwd=Path(__file__).parent.parent)
    assert out.returncode == 0
    assert "outcomes imported" in out.stdout and "seal verified" in out.stdout
