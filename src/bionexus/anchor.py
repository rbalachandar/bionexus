"""Merkle anchoring — make the hash chain tamper-evident to others.

Per-branch chains prove internal consistency; a Merkle root over ALL record
hashes lets a third party verify the entire store's state at a point in
time with one number. Publishing the root somewhere you don't control
(public repo, gist, certificate log, timestamping service) turns "trust me"
into "check me". We anchor locally; publishing is an operator choice via
--publish-cmd.

Stated limits (this is a physics claim, so say what the physics covers):
verification RECOMPUTES every hash from its payload — editing record
content breaks the root even if the hash column is left untouched. What
remains outside this mechanism: anchors.json itself is an ordinary local
file (an attacker with write access to BOTH the db and the anchors file
can rewrite history before the first publish), and a signature over the
anchor is exactly what --publish-cmd to an external transparency channel
provides. Tamper-evidence = recompute on read + at least one EXTERNALLY
PUBLISHED root.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import time
from pathlib import Path

ANCHORS = Path(".data/anchors.json")


def _h(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def merkle_root(leaf_hashes: list[str]) -> str:
    """Standard pairwise SHA-256 Merkle root; odd nodes promote."""
    level = [_h(x) for x in leaf_hashes]
    if not level:
        return _h("")
    while len(level) > 1:
        level = [_h(level[i] + level[i + 1]) if i + 1 < len(level)
                 else level[i] for i in range(0, len(level), 2)]
    return level[0]


def store_hashes(db_path: str) -> list[str]:
    conn = sqlite3.connect(db_path)
    try:
        return [row[0] for row in conn.execute(
            "SELECT record_hash FROM provenance ORDER BY created_at, rowid"
        ).fetchall() if row[0]]
    finally:
        conn.close()


def recomputed_hashes(db_path: str) -> tuple[list[str], list[dict]]:
    """Recompute every record hash FROM ITS PAYLOAD — the anchor verifies
    content, not copied metadata. Returns (hashes, problems)."""
    from bionexus.adapters.store.sqlite import SqliteProvenanceStore
    from bionexus.core.contracts import ProvenanceRecord

    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT record_id, branch_id, record_hash, payload "
            "FROM provenance ORDER BY created_at, rowid").fetchall()
    finally:
        conn.close()
    hashes, problems = [], []
    for rid, br, col_hash, payload in rows:
        rec = ProvenanceRecord.model_validate_json(payload)
        h = SqliteProvenanceStore._hash(rec)
        if h != rec.record_hash or h != col_hash:
            problems.append({"record_id": rid, "branch": br,
                             "problem": "hash-mismatch"})
        hashes.append(h or col_hash or "")
    return hashes, problems


def anchor(db_path: str = "bionexus.db",
           publish_cmd: str | None = None) -> dict:
    """Compute + append the store's Merkle anchor; optionally publish.

    The root is computed over RECOMPUTED payload hashes: an anchor
    commits to what the records actually contain, so a published root
    also pins content integrity, not just copied metadata."""
    hashes, problems = recomputed_hashes(db_path)
    entry = {"ts": time.time(), "records": len(hashes),
             "merkle_root": merkle_root(hashes),
             "content_issues": len(problems)}
    ANCHORS.parent.mkdir(parents=True, exist_ok=True)
    existing = json.loads(ANCHORS.read_text()) if ANCHORS.exists() else []
    existing.append(entry)
    ANCHORS.write_text(json.dumps(existing, indent=1))
    if publish_cmd:
        proc = subprocess.run(publish_cmd, shell=True, input=json.dumps(entry),
                              capture_output=True, text=True, timeout=120)
        entry["published"] = proc.returncode == 0
        if proc.returncode:
            entry["publish_error"] = (proc.stderr or proc.stdout)[-200:]
    return entry


def verify(db_path: str = "bionexus.db", root: str | None = None) -> dict:
    """Recompute and compare against the latest (or given) anchor.

    The current root is computed over RECOMPUTED payload hashes, so an
    edit that rewrites a record's content (leaving the hash column
    untouched) changes the root and breaks the match. `content_tampered`
    flags divergence between stored column hashes and recomputed ones
    even before anyone compares to an anchor."""
    hashes = store_hashes(db_path)
    recomputed, problems = recomputed_hashes(db_path)
    current = merkle_root(recomputed)
    stored_root = merkle_root(hashes)
    anchors = json.loads(ANCHORS.read_text()) if ANCHORS.exists() else []
    target = root or (anchors[-1]["merkle_root"] if anchors else None)
    return {"current_root": current, "anchored_root": target,
            "records": len(recomputed),
            "stored_root": stored_root,
            "content_tampered": stored_root != current or bool(problems),
            "problems": problems[:10],
            "match": target is not None and current == target}
