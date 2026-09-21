"""BioNexus web API (P0.5): thin FastAPI layer over the engine.

One uvicorn process serves REST + SSE; the SPA is mounted statically in
production. All state lives in the existing wizard/provenance stores.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import UploadFile
from pydantic import BaseModel

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse

from bionexus import program as program_cfg
from bionexus import views
from bionexus.adapters.store.sqlite import SqliteProvenanceStore
from bionexus.paths import DATA_DIR
from bionexus.wizard_store import WizardStore

app = FastAPI(title="BioNexus API", version="0.1.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["http://localhost:5173"],
    allow_methods=["*"], allow_headers=["*"])

# ------------------------------------------------------------- SSE broker
_subscribers: set[asyncio.Queue] = set()
_broker: asyncio.Queue = asyncio.Queue()
_watcher_task = None


@app.on_event("startup")
async def _start_watcher():
    global _watcher_task
    from bionexus.api.sse import watcher_loop
    if _watcher_task is None:
        _watcher_task = asyncio.create_task(watcher_loop(_broker))
        asyncio.create_task(_pump())


async def _pump():
    """Move watcher events to every subscriber queue."""
    while True:
        ev = await _broker.get()
        for q in list(_subscribers):
            q.put_nowait(ev)


def get_ws() -> WizardStore:
    return WizardStore()


def publish_workspace(kind: str, payload: dict) -> None:
    """Persist + fan out a workspace-level event (no subprocess needed —
    these originate in this process)."""
    from bionexus.api.sse import record_event
    record_event("workspace", kind, payload)


def get_prov():
    db = Path("bionexus.db")
    if not db.exists():
        return None
    return SqliteProvenanceStore(str(db))


# --------------------------------------------------------------- system
@app.get("/api/system/health")
def health() -> dict:
    return {"ok": True, "wizard_db": views.wizard_db_path().exists(),
            "provenance_db": Path("bionexus.db").exists()}


@app.get("/api/system/modalities")
def modalities() -> dict:
    from bionexus.modality import PACKS
    return {"packs": [
        {"name": p.name, "production_action": p.production_action,
         "test_assays": list(p.test_assays),
         "safety_rule_names": list(p.safety_rule_names),
         "notes": p.notes}
        for p in PACKS.values()]}


@app.get("/api/halt")
def halt_state() -> dict:
    from bionexus.governance import HaltSwitch
    hs = HaltSwitch()
    halt = hs.engaged()
    return {"halted": halt is not None, "detail": halt,
            "history": hs.history()}


@app.post("/api/halt")
def halt_set(body: dict) -> dict:
    from bionexus.governance import HaltSwitch
    hs = HaltSwitch()
    if body.get("halted"):
        hs.engage(body.get("reason", "operator halt (web)"))
    else:
        hs.clear()
    return halt_state()


@app.get("/api/approvals")
def approvals() -> dict:
    from bionexus.approvals import ApprovalInbox
    inbox = ApprovalInbox(".data/approvals.jsonl")
    st = inbox.state()
    return {"pending": [{"id": k, **v} for k, v in st.items()
                        if v.get("status") == "pending"],
            "decided": [{"id": k, **v} for k, v in st.items()
                        if v.get("status") != "pending"]}


@app.post("/api/approvals/{aid}/decide")
def approval_decide(aid: str, body: dict) -> dict:
    from bionexus.approvals import ApprovalInbox
    inbox = ApprovalInbox(".data/approvals.jsonl")
    inbox.decide(aid, bool(body.get("approve")),
                 by=body.get("by", "operator-web"))
    return approvals()


# ------------------------------------------------------------- programs
@app.get("/api/programs")
def programs() -> dict:
    ws = get_ws()
    return views.workspace(ws)


class ProgramIn(BaseModel):
    program: str
    objective: str = ""
    modality: str = ""
    metric: str = "ic50"
    unit: str = ""
    direction: str = "min"
    gate_value: float = 20.0
    mode: str = "autonomous"
    autonomy: str = "act"
    k: int = 2
    rounds: int = 2
    candidates: str = ""

    class Config:
        extra = "allow"


@app.post("/api/programs")
def save_program(body: ProgramIn) -> dict:
    from bionexus.core.contracts import Envelope, EventType
    from bionexus.core.interfaces import record_for, system_actor
    doc = body.model_dump()
    doc["custom"] = True          # the web form is the custom-problem form
    slug = program_cfg._slug(doc.get("program"))
    existing = {x["slug"]: x for x in program_cfg.list_programs()}
    prev = existing.get(slug)
    if prev and prev.get("attachments") and prev.get("mode") != doc["mode"]:
        raise HTTPException(
            409, f"Execution mode is locked: '{doc['program']}' has "
            f"{len(prev['attachments'])} attached experiment(s).")
    program_cfg.save(doc)
    program_cfg.save_program_record(doc)
    publish_workspace("program_updated", {"slug": slug})
    return {"slug": slug, "gate_summary": program_cfg.gate_summary(doc)}


@app.delete("/api/programs/{slug}")
def delete_program_route(slug: str) -> dict:
    ok = program_cfg.delete_program(slug)
    if not ok:
        raise HTTPException(404, f"program {slug} not found")
    publish_workspace("program_deleted", {"slug": slug})
    return {"deleted": slug}


@app.post("/api/programs/{slug}/launch")
def launch_program(slug: str) -> dict:
    existing = {p["slug"]: p for p in program_cfg.list_programs()}
    prow = existing.get(slug)
    if not prow:
        raise HTTPException(404, f"program {slug} not found")
    doc = prow.get("program") or {}
    if doc.get("mode") != "autonomous":
        raise HTTPException(400, "guided programs launch via the wizard")
    from bionexus.api.launch import spawn_campaign
    eid = spawn_campaign(doc, prow["name"])
    publish_workspace("experiment_added", {"eid": eid})
    return {"eid": eid}


# ---------------------------------------------------------- experiments
@app.get("/api/experiments")
def experiments() -> dict:
    ws = get_ws()
    return views.workspace(ws)


@app.get("/api/experiments/{eid}")
def experiment_detail_route(eid: str) -> dict:
    detail = views.experiment_detail(eid, get_ws())
    if detail is None:
        raise HTTPException(404, f"experiment {eid} not found")
    return detail


@app.get("/api/experiments/{eid}/pipeline")
def experiment_pipeline(eid: str) -> dict:
    detail = views.experiment_detail(eid, get_ws())
    if detail is None:
        raise HTTPException(404, f"experiment {eid} not found")
    prov = get_prov()
    recs = prov.branch_records(detail["branch"]) \
        if detail["branch"] and prov else []
    return {"cards": views.pipeline_cards(recs) if recs else [],
            "counts": detail["counts"],
            "rounds": detail["rounds"]}


@app.get("/api/experiments/{eid}/record")
def experiment_record(eid: str) -> dict:
    detail = views.experiment_detail(eid, get_ws())
    if detail is None:
        raise HTTPException(404, f"experiment {eid} not found")
    prov = get_prov()
    recs = prov.branch_records(detail["branch"]) \
        if detail["branch"] and prov else []
    logf = Path(detail["agent"]["log_path"]) \
        if detail["agent"].get("log_path") else None
    log_lines = (logf.read_text(errors="replace").splitlines()[-200:]
                 if logf and logf.is_file() else [])
    return views.narrative_data(recs, log_lines)


@app.post("/api/trees/{root_id}/archive")
def archive_tree(root_id: str) -> dict:
    """Retire a problem tree from the workspace: every live leaf
    experiment is archived (kept, provenance intact)."""
    ws = get_ws()
    trees, _ = views.problem_trees()
    tree = next((t for t in trees if t["root_id"] == root_id), None)
    if tree is None:
        raise HTTPException(404, f"tree {root_id} not found")
    leaf_pids = {pid for stats in tree["leaf_stats"].values()
                 for pid in stats.get("pids", [])}
    n = 0
    for row in ws.ongoing() + ws.finished(500):
        pid = (row["payload"].get("agent") or {}).get("problem_id")
        if pid in leaf_pids and not (row["payload"].get("archived")):
            ws.set_archived(row["id"], True)
            n += 1
    publish_workspace("workspace", {"kind": "tree_archived",
                                    "root": root_id, "archived": n})
    return {"root": root_id, "archived_experiments": n}


@app.post("/api/experiments/{eid}/archive")
def archive_experiment(eid: str) -> dict:
    ws = get_ws()
    if not ws.get(eid):
        raise HTTPException(404, f"experiment {eid} not found")
    ws.set_archived(eid, True)
    publish_workspace("workspace", {"kind": "experiment_archived",
                                    "eid": eid})
    return {"eid": eid, "archived": True}


@app.get("/api/experiments/{eid}/evidence/{run_id}.csv")
def experiment_evidence_csv(eid: str, run_id: str):
    """Serve this run's recorded plate file (raw instrument export)."""
    detail = views.experiment_detail(eid, get_ws())
    if detail is None:
        raise HTTPException(404, f"experiment {eid} not found")
    prov = get_prov()
    recs = prov.branch_records(detail["branch"]) \
        if detail["branch"] and prov else []
    data = views.narrative_data(recs, [], data_dir=str(DATA_DIR))
    for curve in data["evidence"]["curves"]:
        if curve["run_id"] == run_id:
            path = Path(curve["path"])
            if path.is_file():
                return FileResponse(path, media_type="text/csv",
                                    filename=f"{run_id}.csv")
    raise HTTPException(404, f"no recorded plate file for run {run_id}")


@app.post("/api/experiments/{eid}/rereview")
def experiment_rereview(eid: str) -> dict:
    """Re-run the deterministic reviewer on the branch and append a
    fresh review_report (the latest one wins on the page). Honest
    re-audit: findings are re-derived from recorded evidence."""
    detail = views.experiment_detail(eid, get_ws())
    if detail is None:
        raise HTTPException(404, f"experiment {eid} not found")
    if not detail["branch"] or not Path("bionexus.db").exists():
        raise HTTPException(409, "no provenance branch to review")
    from bionexus.adapters.store.sqlite import SqliteProvenanceStore
    from bionexus.core.contracts import Envelope, EventType
    from bionexus.core.interfaces import record_for, system_actor
    from bionexus.reviewer import review_campaign
    prov = SqliteProvenanceStore("bionexus.db")
    recs = prov.branch_records(detail["branch"])
    review = review_campaign(recs)
    prov.append(record_for(
        Envelope(experiment_branch_id=detail["branch"]),
        EventType.stage_transition, system_actor("reviewer"),
        decision={"kind": "review_report", "review": review["review"],
                  "critical": review["critical"],
                  "warnings": review["warnings"],
                  "verdicts_reviewed": review["verdicts_reviewed"],
                  "findings": review["findings"],
                  "rerun": True}))
    return {"critical": review["critical"],
            "warnings": review["warnings"],
            "verdicts_reviewed": review["verdicts_reviewed"],
            "findings": review["findings"]}


@app.get("/api/experiments/{eid}/trace")
def experiment_trace(eid: str, lines: int = 30) -> dict:
    detail = views.experiment_detail(eid, get_ws())
    if detail is None:
        raise HTTPException(404, f"experiment {eid} not found")
    logf = Path(detail["agent"]["log_path"]) \
        if detail["agent"].get("log_path") else None
    if not logf or not logf.is_file():
        return {"lines": [], "truncated": False}
    all_lines = logf.read_text(errors="replace").splitlines()
    tail = all_lines[-lines:]
    return {"lines": tail, "truncated": len(all_lines) > lines}


# ---------------------------------------------------------------- wizard
@app.post("/api/wizard/sessions")
def wizard_create(body: dict) -> dict:
    from bionexus.api import wizard_sessions
    return wizard_sessions.create_session(
        body.get("question", ""), body.get("target", "user-target"),
        body.get("claim", "causal_modification"),
        program=body.get("program"))


@app.get("/api/wizard/sessions/{sid}")
def wizard_get(sid: str) -> dict:
    from bionexus.api import wizard_sessions
    try:
        return wizard_sessions.get_session(sid)
    except KeyError as e:
        raise HTTPException(404, str(e))


@app.post("/api/wizard/sessions/{sid}/design")
def wizard_design(sid: str, body: dict) -> dict:
    from bionexus.api import wizard_sessions
    try:
        return wizard_sessions.design(
            sid, body.get("site"), int(body.get("half_life", 120)),
            bool(body.get("edited_frac")), bool(body.get("mimetic")),
            body.get("controls") or [], body.get("mechanism", ""),
            body.get("refutation", ""), body.get("citation", ""))
    except KeyError as e:
        raise HTTPException(404, str(e))


@app.post("/api/wizard/sessions/{sid}/execute")
def wizard_execute(sid: str) -> dict:
    from bionexus.api import wizard_sessions
    try:
        return wizard_sessions.execute(sid)
    except KeyError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(409, str(e))


@app.post("/api/wizard/sessions/{sid}/upload")
async def wizard_upload(sid: str, file: "UploadFile") -> dict:
    from bionexus.api import wizard_sessions
    try:
        return wizard_sessions.upload(sid, file.filename,
                                      await file.read())
    except KeyError as e:
        raise HTTPException(404, str(e))


@app.post("/api/wizard/sessions/{sid}/analyze")
def wizard_analyze(sid: str, body: dict) -> dict:
    from bionexus.api import wizard_sessions
    try:
        return wizard_sessions.analyze(sid, body.get("selected") or [])
    except KeyError as e:
        raise HTTPException(404, str(e))


# ------------------------------------------------------------------ SSE
@app.get("/api/events")
async def events(
        request: Request,
        topics: str = "workspace") -> StreamingResponse:
    """Server-sent events. topics: comma-separated
    (campaign:<eid>, workspace, approvals). Replays missed events when
    a Last-Event-ID header is present."""
    from bionexus.api.sse import replay_events
    wanted = {t.strip() for t in topics.split(",") if t.strip()}
    last_id = 0
    lid = request.headers.get("Last-Event-ID")
    if lid and lid.isdigit():
        last_id = int(lid)
    q: asyncio.Queue = asyncio.Queue()
    _subscribers.add(q)

    async def gen():
        try:
            for ev in replay_events(last_id, wanted):
                yield (f"id: {ev['id']}\nevent: {ev['kind']}\n"
                       f"data: {json.dumps(ev['payload'])}\n\n")
            while True:
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=15)
                    if ev["topic"] not in wanted:
                        continue
                    yield (f"id: {ev['id']}\nevent: {ev['kind']}\n"
                           f"data: {json.dumps(ev['payload'])}\n\n")
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            _subscribers.discard(q)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


# -------------------------------------------------- static SPA (prod)
_web_dist = Path(__file__).resolve().parents[3] / "web" / "dist"
if _web_dist.exists():                                    # pragma: no cover
    from fastapi.staticfiles import StaticFiles
    app.mount("/", StaticFiles(directory=str(_web_dist), html=True),
              name="spa")
