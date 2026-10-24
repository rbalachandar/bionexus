"""Analysis lifecycle API (generic scientist workflow).

Thin FastAPI wiring over experiment_analysis (computation) and
analysis_store (persistence/artifacts). Route functions stay thin; every
scientific decision is made inside the profile, every state transition is
persisted, and every lifecycle step lands on the analysis branch of the
provenance chain.
"""
from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from bionexus import analysis_store as store
from bionexus import experiment_analysis as EA
from bionexus.adapters.store.sqlite import SqliteProvenanceStore
from bionexus.core.contracts import Envelope, EventType
from bionexus.core.contracts.analysis import (AnalysisState,
                                              DispositionAction,
                                              HumanDisposition)
from bionexus.core.interfaces import record_for, system_actor

router = APIRouter(prefix="/api/analyses", tags=["analyses"])

log = logging.getLogger("bionexus.analysis")

ACTOR = system_actor("scientist")

# states from which each transition is legal (invalid transitions are
# clear 409s, never a silent state rewrite)
RUNNABLE_FROM = {AnalysisState.configured, AnalysisState.analyzed,
                 AnalysisState.reviewed, AnalysisState.qc_hold,
                 # running a regime-held session produces the full refusal
                 # payload (shape-only admits, note) — honest terminus
                 AnalysisState.unsupported_regime}
REVIEWABLE_FROM = {AnalysisState.analyzed, AnalysisState.qc_hold,
                   AnalysisState.reviewed}


def _branch(aid: str) -> str:
    return f"analysis/{aid}"


def _record(aid: str, event: EventType, decision: dict) -> None:
    """Provenance MUST land; a failure never blocks the scientist but is
    never silent either (a gap in the chain is an honesty event)."""
    try:
        s = SqliteProvenanceStore("bionexus.db")
        s.append(record_for(Envelope(experiment_branch_id=_branch(aid)),
                            event, ACTOR, decision=decision))
    except Exception as exc:  # noqa: BLE001
        log.error("provenance write FAILED for %s (%s): %s — the chain "
                  "has a gap", aid, event, exc)


def _err(exc: EA.AnalysisError, status: int = 422) -> HTTPException:
    return HTTPException(status, {"code": exc.code, "detail": exc.message})


def _safe(d: dict) -> dict:
    """Strip local storage paths from anything the browser sees."""
    out = dict(d)
    arts = out.get("artifacts") or {}
    for k, v in arts.items():
        if isinstance(v, dict):
            v.pop("storage_path", None)
    return out


@router.post("")
async def create_analysis(
        file: UploadFile = File(...),
        layout: UploadFile | None = File(None),
        profile: str = Form("plate_assay"),
        config: str = Form("{}")) -> dict:
    """Upload a source artifact (+ optional layout), run the profile's
    preview, persist the session. No fits, no verdicts at this point."""
    try:
        cfg = json.loads(config or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(422, {"code": "invalid_config",
                                  "detail": f"config is not JSON: {exc}"})
    # ONE id for the session and its artifacts — generated once, used
    # everywhere (no pending-dir dance to desync)
    aid = f"an-{uuid.uuid4().hex[:8]}"
    try:
        src = store.store_artifact(aid, "source", file.filename or
                                   "upload", await file.read())
    except ValueError as exc:
        raise HTTPException(422, {"code": "rejected_upload", "detail": str(exc)})
    lay = None
    if layout is not None and layout.filename:
        try:
            lay = store.store_artifact(aid, "layout",
                                       layout.filename, await layout.read())
        except ValueError as exc:
            raise HTTPException(422, {"code": "rejected_upload",
                                      "detail": str(exc)})
    try:
        preview = EA.preview(profile, Path(src.storage_path), cfg,
                             layout_path=lay.storage_path if lay else None)
    except EA.AnalysisError as exc:
        raise _err(exc)
    preview["evidence_origin"] = cfg.get("evidence_origin",
                                         preview.get("evidence_origin"))
    store.create(aid, profile, cfg, src, lay, preview)
    _record(aid, EventType.experiment_defined, {
        "kind": "analysis_created", "profile": profile,
        "source_sha256": src.sha256, "original_name": src.original_name,
        "layout_sha256": lay.sha256 if lay else None,
        "config": cfg, "preview_state": preview.get("state")})
    return _safe(store.get(aid))


@router.get("")
def list_analyses() -> dict:
    return {"analyses": store.list_recent()}


@router.get("/{aid}")
def get_analysis(aid: str) -> dict:
    try:
        return _safe(store.get(aid))
    except KeyError as e:
        raise HTTPException(404, str(e))


def _source_of(doc: dict) -> dict:
    src = (doc.get("artifacts") or {}).get("source") or {}
    path = src.get("storage_path")
    if not path or not Path(path).exists():
        raise HTTPException(409, "source artifact missing")
    # integrity: stored bytes must still match the digest the chain holds
    if src.get("sha256") and store.sha256_of(Path(path)) != src["sha256"]:
        raise HTTPException(409, "source artifact changed on disk — "
                                 "re-upload to open a new analysis")
    return src


def _layout_of(doc: dict) -> str | None:
    lay = (doc.get("artifacts") or {}).get("layout") or {}
    p = lay.get("storage_path")
    return p if p and Path(p).exists() else None


@router.post("/{aid}/configure")
def configure_analysis(aid: str, body: dict) -> dict:
    """Confirm/correct the interpretation. A changed config opens a NEW
    immutable revision; any stored result stays with its revision."""
    try:
        doc = store.get(aid)
    except KeyError as e:
        raise HTTPException(404, str(e))
    src = _source_of(doc)
    cfg = body.get("config") or {}
    try:
        preview = EA.preview(doc["profile"], Path(src["storage_path"]), cfg,
                             layout_path=_layout_of(doc))
    except EA.AnalysisError as exc:
        raise _err(exc)
    out = store.reconfigure(aid, cfg, preview)
    _record(aid, EventType.gate_decision, {
        "kind": "analysis_configured", "revision": out["revision"],
        "config": cfg, "preview_state": preview.get("state")})
    return _safe(out)


@router.post("/{aid}/run")
def run_analysis(aid: str) -> dict:
    """Deterministic analysis of the CURRENT revision. Regime refusals and
    QC holds are returned states — honest terminus, not errors. Only a
    confirmed (or already-analyzed) session may run."""
    try:
        doc = store.get(aid)
    except KeyError as e:
        raise HTTPException(404, str(e))
    try:
        state = AnalysisState(doc["state"])
    except ValueError:
        state = None
    if state not in RUNNABLE_FROM:
        raise HTTPException(409, f"cannot run from state {doc['state']!r} — "
                                 "confirm the interpretation first")
    src = _source_of(doc)
    try:
        result = EA.analyze(doc["profile"], Path(src["storage_path"]),
                            doc["config"], source_sha256=src.get("sha256"),
                            layout_path=_layout_of(doc))
    except EA.AnalysisError as exc:
        raise _err(exc, status=409 if exc.code == "unreadable_source" else 422)
    out = store.store_result(aid, result)
    _record(aid, EventType.evaluation, {
        "kind": "analysis_complete", "revision": out["revision"],
        "state": result.get("state"),
        "source_sha256": src.get("sha256"),
        "config": doc["config"],
        "n_calls": len(result.get("calls") or []),
        "z_prime": result.get("z_prime"),
        "z_prime_kind": result.get("z_prime_kind"),
        "regime_refused": result.get("regime_refused")})
    return _safe(out)


class ReviewBody(BaseModel):
    action: DispositionAction
    reason: str = ""
    target: str = ""
    actor: str = "scientist"


def _chain_status(aid: str) -> str:
    """Verify the analysis branch before any report claims 'intact'. A
    tampered chain REFUSES the report (the honest limit stands: a
    consistent rewrite needs an externally published anchor)."""
    try:
        if not Path("bionexus.db").exists():
            return "no provenance records for this analysis"
        s = SqliteProvenanceStore("bionexus.db")
        branch = _branch(aid)
        if not s.branch_records(branch):
            return "no provenance records for this analysis"
        problems = s.verify_chain(branch_id=branch)
        if problems:
            raise HTTPException(409, "provenance chain TAMPERED for this "
                                     f"analysis ({len(problems)} bad "
                                     "records) — report refused")
        return "intact (recomputed)"
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001
        return "verification unavailable"


def _require_result(aid: str) -> dict:
    doc = store.get(aid)
    if doc.get("result") is None:
        raise HTTPException(409, "no analysis result — run the analysis first")
    return doc


@router.get("/{aid}/report")
def analysis_report(aid: str):
    from bionexus.analysis_report import render_report
    try:
        doc = _require_result(aid)
    except KeyError as e:
        raise HTTPException(404, str(e))
    html = render_report(doc, _chain_status(aid))
    from fastapi.responses import HTMLResponse
    return HTMLResponse(html)


@router.get("/{aid}/export.csv")
def analysis_export(aid: str):
    """Plate-profile standardized CSV, regenerated deterministically from
    the stored source bytes + confirmed config + confirmed control classes
    (raw and normalized values in separate columns, calls and reasons
    beside each row)."""
    from bionexus.analysis_report import export_csv
    from bionexus.analysis_profiles import plate_assay
    try:
        doc = _require_result(aid)
    except KeyError as e:
        raise HTTPException(404, str(e))
    if doc["profile"] != "plate_assay":
        raise HTTPException(409, "CSV export is defined for the plate_assay "
                                 "profile; this analysis uses "
                                 f"{doc['profile']}")
    src = _source_of(doc)
    try:
        cfg = plate_assay.CONFIG_TYPE(**(doc.get("config") or {}))
        records = plate_assay.records_for(
            Path(src["storage_path"]), cfg,
            layout_path=Path(_layout_of(doc)) if _layout_of(doc) else None)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(409, f"source no longer parses: {exc}")
    csv = export_csv(doc, records, doc["result"])
    from fastapi.responses import Response
    return Response(csv, media_type="text/csv",
                    headers={"Content-Disposition":
                             f'attachment; filename="{aid}-export.csv"'})


@router.post("/{aid}/review")
def review_analysis(aid: str, body: ReviewBody) -> dict:
    """Record a human disposition. It never overwrites the computed call —
    machine call and human disposition live side by side on the record."""
    try:
        doc = store.get(aid)
    except KeyError as e:
        raise HTTPException(404, str(e))
    if doc.get("result") is None:
        raise HTTPException(409, "nothing to review — run the analysis first")
    if doc["state"] not in {s.value for s in REVIEWABLE_FROM}:
        raise HTTPException(409, f"cannot review from state {doc['state']!r}")
    disp = HumanDisposition(action=body.action, reason=body.reason,
                            target=body.target, actor=body.actor)
    out = store.add_disposition(aid, disp)
    _record(aid, EventType.stage_transition, {
        "kind": "analysis_reviewed", "action": body.action,
        "reason": body.reason, "target": body.target, "by": body.actor,
        "note": "human disposition — the computed call is unchanged"})
    return _safe(out)
