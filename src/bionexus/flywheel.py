"""The flywheel — negative results are data.

Every verdict (validated / invalidated / inconclusive) is submitted here.
Future campaigns consult it twice:

1. the hypothesis AGENT is shown what the lab already ruled out (prompt
   context — don't re-propose dead mechanisms), and
2. the portfolio SCORER gets a family prior (families that keep failing are
   discounted; families that win are favored).

Backed by a small local SQLite table — append-only submissions, no
durability theater (this is a hint store, provenance remains the record).
"""
from __future__ import annotations

import sqlite3
import threading
import time
from typing import Any


class Flywheel:
    def __init__(self, path: str | None = ".data/flywheel.db"):
        self._conn = None if path is None else sqlite3.connect(
            path, check_same_thread=False)
        self._lock = threading.Lock()
        if self._conn is not None:
            import os
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            self._conn.execute(
                """CREATE TABLE IF NOT EXISTS outcomes (
                    ts REAL NOT NULL,
                    problem_id TEXT,
                    candidate TEXT NOT NULL,
                    family TEXT,
                    assay TEXT,
                    outcome TEXT NOT NULL,
                    observed REAL,
                    ci_low REAL,
                    ci_high REAL
                )""")
            self._conn.commit()

    # -- write side -----------------------------------------------------------

    def submit(self, candidate: str, family: str | None, assay: str,
               outcome: str, observed: float | None = None,
               ci: tuple | None = None, problem_id: str | None = None) -> None:
        if self._conn is None or outcome == "tested":
            return
        with self._lock:
            self._conn.execute(
                "INSERT INTO outcomes VALUES (?,?,?,?,?,?,?,?,?)",
                (time.time(), problem_id, candidate, family or "unassigned",
                 assay, outcome, observed,
                 ci[0] if ci else None, ci[1] if ci else None))
            self._conn.commit()

    # -- read side --------------------------------------------------------------

    def negative_summary(self, problem_id: str | None = None,
                         limit: int = 20) -> list[dict[str, Any]]:
        q = ("SELECT candidate, family, assay, outcome, observed, ts "
             "FROM outcomes WHERE outcome IN ('invalidated','refuted')")
        args: list = []
        if problem_id:
            q += " AND problem_id = ?"
            args.append(problem_id)
        q += " ORDER BY ts DESC LIMIT ?"
        args.append(limit)
        rows = self._conn.execute(q, args).fetchall()
        return [{"candidate": c, "family": f, "assay": a, "outcome": o,
                 "observed": obs, "ts": ts} for c, f, a, o, obs, ts in rows]

    def family_prior(self, family: str | None) -> float:
        """Multiplicative prior in [0.5, 1.5]: what does history say about
        this mechanistic family? Neutral (1.0) when unseen."""
        if self._conn is None or not family:
            return 1.0
        rows = self._conn.execute(
            "SELECT outcome, COUNT(*) FROM outcomes WHERE family=? "
            "GROUP BY outcome", (family,)).fetchall()
        counts = dict(rows)
        good = counts.get("validated", 0) + counts.get("confirmed", 0)
        bad = counts.get("invalidated", 0) + counts.get("refuted", 0)
        if good + bad == 0:
            return 1.0
        rate = good / (good + bad)
        return round(0.5 + rate, 3)

    def prior_bonus(self, family: str | None) -> float:
        """Additive portfolio bonus: unseen neutral, all-win +0.15,
        all-fail -0.15 — enough to steer, not to silence a strong score."""
        p = self.family_prior(family)
        return round((p - 1.0) * 0.3, 4)

    def prompt_context(self, limit: int = 10) -> str:
        """The block injected into the hypothesis-agent prompt."""
        negs = self.negative_summary(limit=limit)
        if not negs:
            return ""
        lines = [f"- {n['candidate']} ({n['family']} family, {n['assay']}): "
                 f"{n['outcome']}"
                 + (f" — observed IC50 {n['observed']:.1f} µM"
                    if n.get("observed") else "")
                 for n in negs]
        return ("ALREADY RULED OUT BY THE LAB (do NOT re-propose these "
                "candidates or near-clones of their mechanisms):\n"
                + "\n".join(lines))
