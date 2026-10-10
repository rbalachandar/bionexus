"""Provenance physics (P0-C): the store blocks rewrites at the DATABASE
level, readers RECOMPUTE hashes instead of trusting copied ones, and
fixture materialization is checksum-gated."""
import json
import sqlite3

import pytest

from bionexus.adapters.store.sqlite import SqliteProvenanceStore
from bionexus.core.contracts import Envelope, EventType
from bionexus.core.interfaces import record_for, system_actor


def _branch(db, n=4):
    store = SqliteProvenanceStore(db)
    for i in range(n):
        store.append(record_for(
            Envelope(experiment_branch_id="problem/sec"),
            EventType.stage_transition, system_actor("t"),
            decision={"kind": "beat", "i": i}))
    return store


def test_database_blocks_update_and_delete(tmp_path):
    db = str(tmp_path / "p.db")
    _branch(db)
    conn = sqlite3.connect(db)
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        conn.execute("UPDATE provenance SET payload='{}' WHERE rowid=1")
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        conn.execute("DELETE FROM provenance WHERE rowid=1")
    conn.close()


def test_verify_chain_detects_payload_tampering(tmp_path):
    """A file-level attacker can drop the triggers and rewrite a payload —
    that edit changes the RECOMPUTED hash, which is what readers check."""
    db = str(tmp_path / "p.db")
    _branch(db)
    conn = sqlite3.connect(db)
    conn.executescript("DROP TRIGGER provenance_no_update;")
    rid, payload = conn.execute(
        "SELECT record_id, payload FROM provenance WHERE rowid=2").fetchone()
    doc = json.loads(payload)
    doc["decision"] = {"kind": "beat", "i": 999}      # quiet rewrite
    conn.execute("UPDATE provenance SET payload=? WHERE record_id=?",
                 (json.dumps(doc), rid))
    conn.commit()
    conn.close()
    store = SqliteProvenanceStore(db)
    problems = store.verify_chain()
    assert len(problems) == 1
    assert problems[0]["record_id"] == rid
    assert problems[0]["problem"] == "payload-tampered"
    # an untouched branch verifies clean
    assert store.verify_chain("problem/absent") == []


def test_anchor_flags_content_tampering(tmp_path, monkeypatch):
    import bionexus.anchor as A
    monkeypatch.setattr(A, "ANCHORS", tmp_path / "anchors.json")
    db = str(tmp_path / "p.db")
    _branch(db)
    entry = A.anchor(db)
    assert A.verify(db)["match"] and not A.verify(db)["content_tampered"]
    conn = sqlite3.connect(db)
    conn.executescript("DROP TRIGGER provenance_no_update;")
    payload = conn.execute(
        "SELECT payload FROM provenance WHERE rowid=1").fetchone()[0]
    doc = json.loads(payload)
    doc["decision"] = {"kind": "falsified"}
    conn.execute("UPDATE provenance SET payload=? WHERE rowid=1",
                 (json.dumps(doc),))
    conn.commit()
    conn.close()
    res = A.verify(db)
    # the columns still produce the OLD root — the CONTENT root differs
    assert res["content_tampered"]
    assert res["stored_root"] != res["current_root"]


def test_eln_export_carries_instrument_and_detached_checksum(tmp_path):
    """The flat ELN row shows WHICH instrument (with version) produced a
    verdict even when that lives only in the derivation blob, and the CSV
    ships a sha256 so silent edits are detectable."""
    import gzip  # noqa: F401  (keep import noise out of eln)
    from bionexus.eln import export_eln
    from bionexus.derivation import build

    store = SqliteProvenanceStore(str(tmp_path / "p.db"))
    store.append(record_for(
        Envelope(experiment_branch_id="problem/sec"),
        EventType.hypothesis_validated, system_actor("t"),
        decision={"candidate": "C-1", "verdict": "validated",
                  "observed": 12.0, "observed_ci": [9.0, 15.0],
                  "derivation": build(instrument="simulator",
                                      version="sim-v1",
                                      quantity="RFU", metric="ic50_um",
                                      method="hill+bootstrap")}))
    out = tmp_path / "eln.csv"
    export_eln(store.branch_records("problem/sec"), out,
               tmp_path / "eln.json")
    text = out.read_text()
    assert "sim-v1" in text                      # version surfaced
    check = out.with_suffix(".csv.sha256")
    assert check.exists()
    assert len(out.read_bytes().hex()) > 0
    import hashlib
    assert check.read_text().split()[0] == hashlib.sha256(
        out.read_bytes()).hexdigest()


def test_fixture_materialize_verifies_before_restoring(tmp_path):
    from bionexus import fixtures
    study = tmp_path / "case-studies" / "09-sec"
    study.mkdir(parents=True)
    root = tmp_path
    live = root / "cache" / "data.json"
    live.parent.mkdir(parents=True)
    live.write_text('{"rows": [1, 2, 3]}')
    fixtures.freeze(study, [("data.json", live)])
    live.unlink()
    assert fixtures.materialize(study) == 1       # restored, verified
    assert json.loads(live.read_text()) == {"rows": [1, 2, 3]}
    # corrupt the frozen copy -> materialize refuses instead of poisoning
    gz = study / "fixtures" / "data.json.gz"
    import gzip
    gz.write_bytes(gzip.compress(b'{"rows": [9, 9, 9]}'))
    with pytest.raises(ValueError, match="integrity"):
        fixtures.materialize(study)
    # existing-but-stale cache is REPLACED, not trusted
    gz.write_bytes(gzip.compress(b'{"rows": [1, 2, 3]}'))
    live.write_text('{"rows": [9, 9, 9]}')
    assert fixtures.materialize(study) == 1
    assert json.loads(live.read_text()) == {"rows": [1, 2, 3]}


def test_materialize_without_manifest_raises(tmp_path):
    from bionexus import fixtures
    empty = tmp_path / "case-studies" / "99-none"
    empty.mkdir(parents=True)
    with pytest.raises(FileNotFoundError):
        fixtures.materialize(empty)


def test_halt_stops_the_agent_facing_mcp_surface(tmp_path, monkeypatch):
    """P0-D: the MCP server is THE agent-facing gateway — the kill switch
    and authorization matrix bind there exactly as they do in campaigns."""
    import bionexus.governance as G
    monkeypatch.setattr(G, "HALT_FILE", tmp_path / "HALT")
    monkeypatch.setattr(G, "HALT_HISTORY", tmp_path / "HALT-history.json")
    monkeypatch.setattr(G, "SOPS_FILE", tmp_path / "sops.json")
    from bionexus.mcp_server import McpSession

    s = McpSession()
    call = lambda n, a: json.loads(s.handle(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": n, "arguments": a}}
    )["result"]["content"][0]["text"])

    assay = call("run_assay", {"compounds": ["CCO"], "assay": "binding"})
    assert "results" in assay                      # normally: it runs

    (tmp_path / "HALT").write_text(json.dumps(
        {"reason": "operator stop", "ts": 0, "id": "h-1"}))
    assay = call("run_assay", {"compounds": ["CCO"], "assay": "binding"})
    assert assay["status"] == "rejected"
    assert "[halt]" in assay["reason"]
    # the refusal itself is provenance
    recs = s.store.branch_records("mcp-session")
    kinds = [r.decision.get("kind") for r in recs
             if r.event_type.value == "gate_decision"]
    assert "halt_refusal" in kinds
