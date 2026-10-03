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
        # append-only is enforced by the DATABASE, not by convention:
        # UPDATE/DELETE abort at the engine level, so even a bug (or an
        # adb shell session) cannot rewrite history without an error
        self._conn.executescript("""
            CREATE TRIGGER IF NOT EXISTS provenance_no_update
            BEFORE UPDATE ON provenance
            BEGIN SELECT RAISE(ABORT, 'provenance is append-only'); END;
            CREATE TRIGGER IF NOT EXISTS provenance_no_delete
            BEFORE DELETE ON provenance
            BEGIN SELECT RAISE(ABORT, 'provenance is append-only'); END;
        """)
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

    def branches(self) -> list[str]:
        rows = self._conn.execute(
            "SELECT DISTINCT branch_id FROM provenance ORDER BY branch_id").fetchall()
        return [r[0] for r in rows]

    def recent_records(self, limit: int = 15) -> list[ProvenanceRecord]:
        rows = self._conn.execute(
            "SELECT payload FROM provenance ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (limit,)).fetchall()
        recs = [ProvenanceRecord.model_validate_json(r[0]) for r in rows]
        return list(reversed(recs))

    def branch_records(self, branch_id: str) -> list[ProvenanceRecord]:
        rows = self._conn.execute(
            "SELECT payload FROM provenance WHERE branch_id=? ORDER BY created_at, rowid",
            (branch_id,),
        ).fetchall()
        return [ProvenanceRecord.model_validate_json(r[0]) for r in rows]

    def verify_chain(self, branch_id: str | None = None) -> list[dict]:
        """RECOMPUTE every record hash from its stored payload and re-link
        the chain. A hash proves nothing unless someone checks it — this is
        that someone, on the read path.

        Returns [] when the chain is sound; otherwise one entry per bad
        record: {record_id, branch, event, problem}, problem being
          'payload-tampered'   content no longer hashes to its stored hash
          'column-tampered'    the hash COLUMN diverges from the payload
          'prev-mismatch'      the prev link does not point at the record
                               before it in this branch
        What this CANNOT catch, stated honestly: a rewrite that updates
        payload, column and links all consistently — that is the job of
        `bn anchor` (an external Merkle root you published elsewhere)."""
        sql = ("SELECT record_id, branch_id, record_hash, payload "
               "FROM provenance")
        args: tuple = ()
        if branch_id is not None:
            sql += " WHERE branch_id=?"
            args = (branch_id,)
        rows = self._conn.execute(
            sql + " ORDER BY branch_id, created_at, rowid", args).fetchall()
        problems: list[dict] = []
        last_by_branch: dict[str, str | None] = {}
        for rid, br, col_hash, payload in rows:
            rec = ProvenanceRecord.model_validate_json(payload)
            entry = {"record_id": rid, "branch": br,
                     "event": rec.event_type.value}
            recomputed = self._hash(rec)
            if recomputed != rec.record_hash:
                problems.append({**entry, "problem": "payload-tampered",
                                 "detail": "content does not hash to the "
                                           "record's own hash"})
                stored = rec.record_hash
            elif col_hash != rec.record_hash:
                problems.append({**entry, "problem": "column-tampered",
                                 "detail": "hash column diverges from the "
                                           "payload's hash"})
                stored = rec.record_hash
            else:
                stored = col_hash
            expected = last_by_branch.get(br)
            if (rec.prev_record_hash or None) != expected:
                problems.append({**entry, "problem": "prev-mismatch",
                                 "detail": "prev link does not match the "
                                           "preceding record"})
            last_by_branch[br] = stored
        return problems

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
