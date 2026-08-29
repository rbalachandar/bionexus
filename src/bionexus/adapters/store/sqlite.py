"""SQLite provenance store — hash-chained, append-only (P5). Default store."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading

from bionexus.core.contracts import ProvenanceRecord


class SqliteProvenanceStore:
    name = "sqlite"

    def __init__(self, path: str = ":memory:"):
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS provenance (
                record_id TEXT PRIMARY KEY,
                branch_id TEXT NOT NULL,
                artifact_id TEXT,
                created_at REAL NOT NULL,
                record_hash TEXT,
                payload TEXT NOT NULL
            )"""
        )
        self._conn.commit()

    def append(self, record: ProvenanceRecord) -> ProvenanceRecord:
        with self._lock:
            prev = self._conn.execute(
                "SELECT record_hash FROM provenance WHERE branch_id=? "
                "ORDER BY created_at DESC, rowid DESC LIMIT 1",
                (record.envelope.experiment_branch_id,),
            ).fetchone()
            record.prev_record_hash = prev[0] if prev else None
            record.record_hash = self._hash(record)
            self._conn.execute(
                "INSERT INTO provenance VALUES (?,?,?,?,?,?)",
                (
                    record.record_id,
                    record.envelope.experiment_branch_id,
                    record.artifact.artifact_id if record.artifact else None,
                    record.envelope.created_at,
                    record.record_hash,
                    record.model_dump_json(),
                ),
            )
            self._conn.commit()
        return record

    def lineage(self, artifact_id: str) -> list[ProvenanceRecord]:
        rows = self._conn.execute(
            "SELECT payload FROM provenance WHERE artifact_id=? ORDER BY created_at, rowid",
            (artifact_id,),
        ).fetchall()
        return [ProvenanceRecord.model_validate_json(r[0]) for r in rows]

    def branch_records(self, branch_id: str) -> list[ProvenanceRecord]:
        rows = self._conn.execute(
            "SELECT payload FROM provenance WHERE branch_id=? ORDER BY created_at, rowid",
            (branch_id,),
        ).fetchall()
        return [ProvenanceRecord.model_validate_json(r[0]) for r in rows]

    @staticmethod
    def _hash(record: ProvenanceRecord) -> str:
        material = json.dumps(
            {
                "prev": record.prev_record_hash,
                "record_id": record.record_id,
                "event_type": record.event_type.value,
                "artifact": record.artifact.model_dump() if record.artifact else None,
                "decision": record.decision,
                "created_at": record.envelope.created_at,
            },
            sort_keys=True,
        )
        return hashlib.sha256(material.encode()).hexdigest()
