"""Merkle anchoring — make the hash chain tamper-evident to others.

Per-branch chains prove internal consistency; a Merkle root over ALL record
hashes lets a third party verify the entire store's state at a point in
time with one number. Publishing the root somewhere you don't control
(public repo, gist, certificate log, timestamping service) turns "trust me"
into "check me". We anchor locally; publishing is an operator choice via
--publish-cmd.
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


def anchor(db_path: str = "bionexus.db",
           publish_cmd: str | None = None) -> dict:
    """Compute + append the store's Merkle anchor; optionally publish."""
    hashes = store_hashes(db_path)
    entry = {"ts": time.time(), "records": len(hashes),
             "merkle_root": merkle_root(hashes)}
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
    """Recompute and compare against the latest (or given) anchor."""
    hashes = store_hashes(db_path)
    current = merkle_root(hashes)
    anchors = json.loads(ANCHORS.read_text()) if ANCHORS.exists() else []
    target = root or (anchors[-1]["merkle_root"] if anchors else None)
    return {"current_root": current, "anchored_root": target,
            "records": len(hashes),
            "match": target is not None and current == target}
