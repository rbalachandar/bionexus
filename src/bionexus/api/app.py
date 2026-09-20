"""BioNexus web API (P0.5): thin FastAPI layer over the engine.

One uvicorn process serves REST + SSE; the SPA is mounted statically in
production. All state lives in the existing wizard/provenance stores.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

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


def publish(topic: str, kind: str, payload: dict) -> None:
    """Fan out to live subscribers and persist for reconnect replay."""
    event = {"topic": topic, "kind": kind, "payload": payload,
             "id": int(payload.get("_id") or 0)}
    for q in list(_subscribers):
        try:
            q.put_nowait(event)
        except Exception:
            _subscribers.discard(q)


def get_ws() -> WizardStore:
    return WizardStore()


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
    return {"halted": HaltSwitch().is_halted()}


# ------------------------------------------------------------- programs
@app.get("/api/programs")
def programs() -> dict:
    ws = get_ws()
    return views.workspace(ws)


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


# ------------------------------------------------------------------ SSE
@app.get("/api/events")
async def events(topics: str = "workspace") -> StreamingResponse:
    """Server-sent events. topics: comma-separated
    (campaign:<eid>, workspace, approvals)."""
    wanted = {t.strip() for t in topics.split(",") if t.strip()}
    q: asyncio.Queue = asyncio.Queue()
    _subscribers.add(q)

    async def gen():
        try:
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
