"""Persistent experiment state for the workbench wizard (DMTA spans days).

The wizard saves each experiment after every step, so an experiment defined
today can be resumed next week. One SQLite table, explicit status; status
only moves forward.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path

from bionexus.paths import DATA_DIR

DB_PATH = DATA_DIR / "wizard.db"

# ordered; index = wizard step to resume from (1-based, +2 for steps 3..6)
STATUSES = ["defining", "designing", "readiness_ok", "ready_blocked",
            "executing", "results_uploaded", "verdict_recorded"]


class WizardStore:
    def __init__(self, path: Path | str = DB_PATH):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._lock = threading.Lock()
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS experiments (
                id TEXT PRIMARY KEY,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                status TEXT NOT NULL,
                question TEXT NOT NULL,
                payload TEXT NOT NULL
            )""")

    def _row(self, r) -> dict:
        return {"id": r[0], "created_at": r[1], "updated_at": r[2],
                "status": r[3], "question": r[4], "payload": json.loads(r[5])}

    def create(self, question: str, claim: str, target: str,
               eid: str | None = None) -> str:
        eid = eid or uuid.uuid4().hex[:12]
        with self._lock:
            now = time.time()
            self._conn.execute(
                "INSERT OR REPLACE INTO experiments VALUES (?,?,?,?,?,?)",
                (eid, now, now, "defining", question,
                 json.dumps({"problem": {"question": question, "claim": claim,
                                         "target": target}})))
            self._conn.commit()
        return eid

    def register_agent(self, eid: str, objective: str, log: str,
                       autonomy: str = "act", pid: int | None = None,
                       status: str = "executing") -> str:
        """One registry: agent-driven experiments live in the same table as
        wizard-defined ones, tagged by origin."""
        with self._lock:
            now = time.time()
            self._conn.execute(
                "INSERT OR REPLACE INTO experiments VALUES (?,?,?,?,?,?)",
                (eid, now, now, status, objective,
                 json.dumps({"agent": {"log": log, "autonomy": autonomy,
                                       "pid": pid, "problem_id": None}})))
            self._conn.commit()
        return eid

    def set_question(self, eid: str, question: str) -> None:
        """Retitle: question is a column, not payload fields."""
        with self._lock:
            self._conn.execute(
                "UPDATE experiments SET question=?, updated_at=? "
                "WHERE id=?", (question, time.time(), eid))
            self._conn.commit()

    def link_problem(self, eid: str, problem_id: str) -> None:
        with self._lock:
            row = self._conn.execute(
                "SELECT payload FROM experiments WHERE id=?", (eid,)).fetchone()
            if not row:
                return
            payload = json.loads(row[0])
            if payload.get("agent") is not None:
                payload["agent"]["problem_id"] = problem_id
                self._conn.execute(
                    "UPDATE experiments SET payload=?, updated_at=? WHERE id=?",
                    (json.dumps(payload), time.time(), eid))
                self._conn.commit()

    def update(self, eid: str, status: str, **fields) -> None:
        assert status in STATUSES
        with self._lock:
            row = self._conn.execute(
                "SELECT payload FROM experiments WHERE id=?", (eid,)).fetchone()
            if not row:
                raise KeyError(eid)
            payload = json.loads(row[0])
            payload.update(fields)
            self._conn.execute(
                "UPDATE experiments SET status=?, payload=?, updated_at=? WHERE id=?",
                (status, json.dumps(payload, default=str), time.time(), eid))
            self._conn.commit()

    def get(self, eid: str) -> dict | None:
        r = self._conn.execute(
            "SELECT * FROM experiments WHERE id=?", (eid,)).fetchone()
        return self._row(r) if r else None

    def _visible(self, where: str, limit: int | None = None) -> list[dict]:
        sql = (f"SELECT * FROM experiments WHERE {where} "
               "AND (payload NOT LIKE '%\"archived\": true%') "
               "ORDER BY updated_at DESC")
        args = ()
        if limit is not None:
            sql += " LIMIT ?"
            args = (limit,)
        return [self._row(r) for r in
                self._conn.execute(sql, args).fetchall()]

    def ongoing(self) -> list[dict]:
        return self._visible("status != 'verdict_recorded'")

    def finished(self, limit: int = 20) -> list[dict]:
        return self._visible("status = 'verdict_recorded'", limit)

    def archived(self, limit: int = 100) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM experiments "
            "WHERE payload LIKE '%\"archived\": true%' "
            "ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
        return [self._row(r) for r in rows]

    def set_archived(self, eid: str, archived: bool = True) -> None:
        """Archive = out of the working set, but never deleted: the
        provenance record is WORM, so experiments are retired, not
        erased."""
        self.update(eid, self.get(eid)["status"], archived=archived)
