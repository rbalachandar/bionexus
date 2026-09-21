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
            "executing", "results_uploaded", "verdict_recorded",
            "completed", "failed", "interrupted"]


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
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS programs (
                slug TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                doc TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )""")
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS campaign_specs (
                experiment_id    TEXT PRIMARY KEY
                    REFERENCES experiments(id) ON DELETE CASCADE,
                program_slug     TEXT REFERENCES programs(slug),
                objective        TEXT NOT NULL,
                constraints_json TEXT,
                success_metric   TEXT,
                k                INTEGER,
                rounds           INTEGER,
                autonomy         TEXT,
                hypothesis_source TEXT,
                n_candidates     INTEGER,
                modality         TEXT,
                created_at       REAL NOT NULL
            )""")
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS program_experiments (
                program_slug TEXT NOT NULL
                    REFERENCES programs(slug) ON DELETE CASCADE,
                experiment_id TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'leaf',
                campaign_root TEXT,
                question TEXT,
                status TEXT,
                created_at REAL NOT NULL,
                PRIMARY KEY (program_slug, experiment_id)
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

    def set_status(self, eid: str, status: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE experiments SET status=?, updated_at=? WHERE id=?",
                (status, time.time(), eid))
            self._conn.commit()

    def register_agent(self, eid: str, objective: str, log: str,
                       autonomy: str = "act", pid: int | None = None,
                       status: str = "executing",
                       program: str | None = None) -> str:
        """One registry: agent-driven experiments live in the same table as
        wizard-defined ones, tagged by origin (and program when launched
        from one)."""
        with self._lock:
            now = time.time()
            payload = {"agent": {"log": log, "autonomy": autonomy,
                                 "pid": pid, "problem_id": None}}
            if program:
                payload["program"] = program
            self._conn.execute(
                "INSERT OR REPLACE INTO experiments VALUES (?,?,?,?,?,?)",
                (eid, now, now, status, objective, json.dumps(payload)))
            self._conn.commit()
        return eid

    # ------------------------------------------------ program relations
    def upsert_program(self, slug: str, name: str, doc: dict) -> None:
        with self._lock:
            now = time.time()
            self._conn.execute(
                "INSERT INTO programs VALUES (?,?,?,?,?) "
                "ON CONFLICT(slug) DO UPDATE SET name=?, doc=?, updated_at=?",
                (slug, name, json.dumps(doc), now, now,
                 name, json.dumps(doc), now))
            self._conn.commit()

    def delete_program(self, slug: str) -> None:
        """Remove the program and its links (relations cascade via FK;
        experiments survive unlinked)."""
        with self._lock:
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.execute(
                "DELETE FROM program_experiments WHERE program_slug=?",
                (slug,))
            # campaign specs survive with the experiment; detach the program
            self._conn.execute(
                "UPDATE campaign_specs SET program_slug=NULL "
                "WHERE program_slug=?", (slug,))
            self._conn.execute(
                "DELETE FROM programs WHERE slug=?", (slug,))
            self._conn.commit()

    def get_program(self, slug: str) -> dict | None:
        row = self._conn.execute(
            "SELECT doc FROM programs WHERE slug=?", (slug,)).fetchone()
        return json.loads(row[0]) if row else None

    def db_programs(self) -> list[dict]:
        out = []
        for slug, name, doc, ts in self._conn.execute(
                "SELECT slug, name, doc, updated_at FROM programs "
                "ORDER BY created_at"):
            out.append({"slug": slug, "name": name,
                        "doc": json.loads(doc), "updated_at": ts})
        return out

    def db_program_count(self) -> int:
        return self._conn.execute(
            "SELECT COUNT(*) FROM programs").fetchone()[0]

    def link_experiment(self, program_slug: str, eid: str,
                        role: str = "leaf", campaign_root: str | None = None,
                        question: str = "", status: str = "executing") -> None:
        """The Program-Experiment relation: role 'campaign' marks a
        problem-tree ROOT (campaign container), role 'leaf' marks a
        single experiment under the program (campaign_root set when it
        belongs to a decomposed campaign)."""
        with self._lock:
            now = time.time()
            self._conn.execute(
                "INSERT INTO program_experiments VALUES (?,?,?,?,?,?,?) "
                "ON CONFLICT(program_slug, experiment_id) DO UPDATE SET "
                "role=?, campaign_root=?, question=?, status=?",
                (program_slug, eid, role, campaign_root,
                 (question or "")[:120], status, now,
                 role, campaign_root, (question or "")[:120], status))
            self._conn.commit()

    def program_links(self, slug: str) -> list[dict]:
        return [{"program": r[0], "eid": r[1], "role": r[2],
                 "campaign_root": r[3], "question": r[4], "status": r[5]}
                for r in self._conn.execute(
                    "SELECT program_slug, experiment_id, role, "
                    "campaign_root, question, status "
                    "FROM program_experiments WHERE program_slug=? "
                    "ORDER BY created_at", (slug,))]

    def set_campaign_spec(self, eid: str, *, objective: str,
                          program_slug: str | None = None,
                          constraints: list | None = None,
                          success_metric: str | None = None,
                          k: int | None = None, rounds: int | None = None,
                          autonomy: str | None = None,
                          hypothesis_source: str | None = None,
                          n_candidates: int | None = None,
                          modality: str | None = None) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO campaign_specs VALUES "
                "(?,?,?,?,?,?,?,?,?,?,?,?)",
                (eid, program_slug, objective,
                 json.dumps(constraints) if constraints else None,
                 success_metric, k, rounds, autonomy, hypothesis_source,
                 n_candidates, modality, time.time()))
            self._conn.commit()

    def get_campaign_spec(self, eid: str) -> dict | None:
        row = self._conn.execute(
            "SELECT experiment_id, program_slug, objective, "
            "constraints_json, success_metric, k, rounds, autonomy, "
            "hypothesis_source, n_candidates, modality "
            "FROM campaign_specs WHERE experiment_id=?", (eid,)).fetchone()
        if not row:
            return None
        return {"experiment_id": row[0], "program_slug": row[1],
                "objective": row[2],
                "constraints": json.loads(row[3]) if row[3] else [],
                "success_metric": row[4], "k": row[5], "rounds": row[6],
                "autonomy": row[7], "hypothesis_source": row[8],
                "n_candidates": row[9], "modality": row[10]}

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

    def purge_archived(self) -> int:
        """Hard-delete archived REGISTRY rows. Provenance (bionexus.db)
        is untouched — only the working-set registration is removed."""
        cur = self._conn.execute(
            "DELETE FROM experiments "
            "WHERE payload LIKE '%\"archived\": true%'")
        # drop program links whose experiment no longer exists
        self._conn.execute(
            "DELETE FROM program_experiments WHERE experiment_id NOT IN "
            "(SELECT id FROM experiments)")
        self._conn.commit()
        return cur.rowcount

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
