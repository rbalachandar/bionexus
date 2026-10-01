"""SSE support (P0.6): event log + watcher.

Campaigns run in subprocesses, so in-process append hooks cannot see
their writes. The watcher polls the stores (2s) and records diffs to
the api_events table; /api/events streams new rows per connection with
Last-Event-ID replay. Poll-based also survives multi-process writes.
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from bionexus.wizard_store import WizardStore


def _ws() -> WizardStore:
    return WizardStore()


def ensure_events_table() -> None:
    ws = _ws()
    ws._conn.execute("""
        CREATE TABLE IF NOT EXISTS api_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic TEXT NOT NULL,
            kind TEXT NOT NULL,
            payload TEXT NOT NULL,
            created_at REAL NOT NULL
        )""")
    ws._conn.commit()


def record_event(topic: str, kind: str, payload: dict) -> int:
    ws = _ws()
    ensure_events_table()
    cur = ws._conn.execute(
        "INSERT INTO api_events (topic, kind, payload, created_at) "
        "VALUES (?,?,?,?)",
        (topic, kind, json.dumps(payload, default=str), time.time()))
    ws._conn.commit()
    return int(cur.lastrowid)


def replay_events(last_id: int, topics: set[str], limit: int = 200) -> list:
    ws = _ws()
    ensure_events_table()
    rows = ws._conn.execute(
        "SELECT id, topic, kind, payload FROM api_events "
        "WHERE id > ? ORDER BY id LIMIT ?", (last_id, limit)).fetchall()
    return [{"id": r[0], "topic": r[1], "kind": r[2],
             "payload": json.loads(r[3])}
            for r in rows if r[1] in topics]


def _branch_map() -> dict:
    """Campaign id -> problem branch, announced by the campaign itself
    the moment its problem is defined (no log parsing needed)."""
    from bionexus.paths import CAMPAIGN_DIR
    f = CAMPAIGN_DIR / "branch-map.json"
    if not f.exists():
        return {}
    try:
        return json.loads(f.read_text())
    except Exception:
        return {}


def _branch_for(ws: WizardStore, eid: str) -> str | None:
    """Problem id for an experiment: the campaign's own announcement,
    else payload, else the program relation, else the agent log."""
    bm = _branch_map()
    if eid in bm:
        return bm[eid]
    row = ws.get(eid)
    if not row:
        return None
    ag = (row["payload"] or {}).get("agent") or {}
    if ag.get("problem_id"):
        return ag["problem_id"]
    from bionexus import program as program_cfg
    for p in program_cfg.list_programs():
        for l in program_cfg.links_for(p["slug"]):
            if l["eid"] == eid and l.get("campaign_root"):
                return l["campaign_root"]
    log = ag.get("log")
    if log and Path(log).is_file():
        from bionexus.views import resolve_problem
        pid = resolve_problem({}, Path(log))
        if pid:
            return pid
    return None


def _snapshot(ws: WizardStore, prov) -> dict:
    """State fingerprint: experiments (with LIVE log-derived status —
    the registry status column never changes after 'executing') +
    branch record counts."""
    from bionexus.views import row_status
    rows = ws._conn.execute(
        "SELECT id, status, updated_at, payload FROM experiments").fetchall()
    exps = {}
    for r in rows:
        exps[r[0]] = {"status": row_status(
            {"payload": json.loads(r[3]) if r[3] else {},
             "status": r[1]}), "updated_at": r[2]}
    counts: dict[str, int] = {}         # problem_id -> record count
    eid_by_pid: dict[str, str] = {}
    if prov is not None:
        for eid in exps:
            pid = _branch_for(ws, eid)
            if not pid:
                continue
            eid_by_pid[pid] = eid
            try:
                counts[pid] = len(
                    prov.branch_records(f"problem/{pid}"))
            except Exception:
                pass
    return {"exps": exps, "counts": counts, "eid_by_pid": eid_by_pid}


def watch_once(prev: dict | None, ws: WizardStore, prov) -> tuple[dict, list]:
    """One watcher tick: diff against prev, emit events. Returns
    (new_snapshot, events[{topic, kind, payload}])."""
    snap = _snapshot(ws, prov)
    events: list[dict] = []
    if prev is None:
        return snap, events
    for eid, meta in snap["exps"].items():
        old = prev["exps"].get(eid)
        if old is None:
            events.append({"topic": "workspace", "kind": "experiment_added",
                           "payload": {"eid": eid}})
            events.append({"topic": f"campaign:{eid}", "kind": "status",
                           "payload": {"eid": eid,
                                       "status": meta["status"]}})
        elif old["status"] != meta["status"]:
            events.append({"topic": f"campaign:{eid}", "kind": "status",
                           "payload": {"eid": eid,
                                       "status": meta["status"]}})
        elif old["updated_at"] != meta["updated_at"]:
            events.append({"topic": f"campaign:{eid}", "kind": "updated",
                           "payload": {"eid": eid}})
    for eid in prev["exps"]:
        if eid not in snap["exps"]:
            events.append({"topic": "workspace", "kind": "experiment_removed",
                           "payload": {"eid": eid}})
    for br, n in snap["counts"].items():
        if prev["counts"].get(br) != n:
            events.append({"topic": f"campaign:{snap['eid_by_pid'][br]}",
                           "kind": "records",
                           "payload": {"branch": f"problem/{br}",
                                       "record_count": n}})
    return snap, events


def _eid_for_branch(ws: WizardStore, problem_id: str) -> str:
    """Which experiment id a problem branch belongs to (spec or payload)."""
    rows = ws._conn.execute(
        "SELECT id, payload FROM experiments ORDER BY updated_at DESC"
    ).fetchall()
    for eid, payload in rows:
        spec = ws.get_campaign_spec(eid)
        ag = (json.loads(payload).get("agent") or {}) if payload else {}
        if (spec and spec.get("objective")) \
                and ag.get("problem_id") == problem_id:
            return eid
        if ag.get("problem_id") == problem_id:
            return eid
    return problem_id or "workspace"


async def watcher_loop(queue: asyncio.Queue, interval: float = 2.0) -> None:
    """Background task: poll stores, record events, push to broker."""
    ensure_events_table()
    prov_path = Path("bionexus.db")
    prov = None
    prev = None
    while True:
        try:
            ws = _ws()
            prov = __import__(
                "bionexus.adapters.store.sqlite",
                fromlist=["SqliteProvenanceStore"]).SqliteProvenanceStore(
                "bionexus.db") if prov_path.exists() else None
            prev, events = watch_once(prev, ws, prov)
            for ev in events:
                eid = ev["payload"].get("eid")
                topic = (f"campaign:{eid}" if eid
                         and ev["topic"].startswith("campaign")
                         else ev["topic"])
                event_id = record_event(topic, ev["kind"], ev["payload"])
                await queue.put({"id": event_id, "topic": topic,
                                 "kind": ev["kind"],
                                 "payload": ev["payload"]})
        except Exception:
            pass
        await asyncio.sleep(interval)
