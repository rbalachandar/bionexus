"""/api/v1/analyses — drop a plate file, see what the data says, and say what it is evidence for.

Thin typed wiring over `experiment_analysis` (all scientific decisions) and
`analysis_store` (revisions, artifacts). Every step that changes something is
sealed in the provenance ledger under the acting person.
"""
from __future__ import annotations

import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, Response

from proef import analysis_store as store
from proef import experiment_analysis as EA
from proef.api.v1 import schemas as S
from proef.api.v1.deps import who
from proef.core.contracts import Actor, ActorKind, Envelope, EventType
from proef.core.contracts.analysis import (AnalysisState, DispositionAction,
                                              HumanDisposition)
from proef.core.interfaces import record_for
from proef.views import ids as _ids

router = APIRouter(prefix="/analyses", tags=["analyze"])
log = logging.getLogger("proef.analysis")

# states from which a fit may run; others are honest holds the scientist must resolve
RUNNABLE = {AnalysisState.preview_ready, AnalysisState.configured, AnalysisState.analyzed,
            AnalysisState.reviewed, AnalysisState.qc_hold, AnalysisState.unsupported_regime}
REVIEWABLE = {AnalysisState.analyzed, AnalysisState.qc_hold, AnalysisState.reviewed}


def _problem(status: int, type_: str, title: str, detail: str = "") -> HTTPException:
    return HTTPException(status, S.Problem(type=type_, title=title, detail=detail).model_dump())


def _seal(aid: str, event: EventType, user: str, decision: dict, branch: str | None = None) -> None:
    """Provenance must land; a failure is loud in the log, never silent."""
    try:
        from proef.adapters.store.sqlite import get_store
        get_store(str(_ids.PROVENANCE_DB)).append(record_for(
            Envelope(experiment_branch_id=branch or f"analysis/{aid}"), event,
            Actor(kind=ActorKind.human, id=user), decision=decision))
    except Exception as exc:  # noqa: BLE001
        log.error("provenance write FAILED for %s: %s — the chain has a gap", aid, exc)


def _doc(aid: str) -> dict:
    try:
        return store.get(aid)
    except KeyError:
        raise _problem(404, "analysis-not-found", "Analysis not found", aid) from None


def _src(doc: dict) -> dict:
    return (doc.get("artifacts") or {}).get("source") or {}


def _verified_src(doc: dict) -> dict:
    """The stored bytes must still match the digest the ledger holds."""
    src = _src(doc)
    path = src.get("storage_path")
    if not path or not Path(path).exists():
        raise _problem(409, "source-missing", "Source file is missing", doc["id"])
    if src.get("sha256") and store.sha256_of(Path(path)) != src["sha256"]:
        raise _problem(409, "source-changed", "Source changed on disk",
                       "The stored file no longer matches its recorded digest. Re-upload to open a new analysis.")
    return src


def _layout(doc: dict) -> str | None:
    return ((doc.get("artifacts") or {}).get("layout") or {}).get("storage_path")


def _preview(p: dict) -> S.AnalysisPreview:
    return S.AnalysisPreview(
        format=p.get("format"), n_wells=int(p.get("n_wells") or 0),
        n_controls=int(p.get("controls_detected") or 0),
        z_prime=p.get("z_prime"), z_kind=p.get("z_prime_kind"),
        samples=list(p.get("samples") or []), has_doses=bool(p.get("has_doses")),
        evidence_origin=str(p.get("evidence_origin") or "unknown"),
        needs_confirmation=[str(x) for x in p.get("needs_confirmation") or []],
        diagnostics=[S.AnalysisDiagnostic(**{k: d.get(k, "") for k in ("severity", "code", "message")})
                     for d in p.get("diagnostics") or []])


def _curve(entity: str, comp: dict, wells: list[dict], max_response) -> S.Curve | None:
    from proef.fitting import hill_fit, hill_response
    pts = sorted((float(w["conc_um"]), float(w["value"])) for w in wells
                 if w.get("sample") == entity and not w.get("control")
                 and isinstance(w.get("conc_um"), (int, float)) and w["conc_um"] > 0
                 and isinstance(w.get("value"), (int, float)))
    if not pts:
        return None
    fit = None
    if comp:
        line: list[S.CurvePoint] = []
        hf = hill_fit(pts, max_response)
        if comp.get("ic50_um") and hf:
            lo, hi = pts[0][0] / 1.6, pts[-1][0] * 1.6
            line = [S.CurvePoint(conc_um=c, value=hill_response(c, comp["ic50_um"], hf["top"]))
                    for c in (lo * (hi / lo) ** (i / 59) for i in range(60))]
        ci = comp.get("ic50_ci")
        fit = S.CurveFit(ic50_um=comp.get("ic50_um"), ci=list(ci) if ci else None,
                         top=hf["top"] if hf else None, method=comp.get("fit_method"),
                         model=comp.get("fit_model"), right_censored=bool(comp.get("right_censored")),
                         left_censored=bool(comp.get("left_censored")), line=line)
    return S.Curve(run_id=entity, label=entity,
                   points=[S.CurvePoint(conc_um=c, value=v) for c, v in pts], fit=fit)


def _result(doc: dict) -> S.AnalysisResult | None:
    r = doc.get("result")
    if not r:
        return None
    cfg = doc.get("config") or {}
    calls = {c["entity"]: c for c in r.get("calls") or []}
    comps = r.get("compounds") or {}
    gate = None
    if r.get("threshold_registered") and cfg.get("threshold") is not None:
        t, d = float(cfg["threshold"]), cfg.get("direction", "min")
        gate = S.Gate(metric=cfg.get("metric", "ic50_um"), direction=d, threshold=t, unit="µM",
                      label=f"IC50 (µM) {'≤' if d == 'min' else '≥'} {t:g}")
    out = []
    for entity in sorted(set(comps) | set(calls)):
        c, k = comps.get(entity) or {}, calls.get(entity) or {}
        ci = c.get("ic50_ci")
        out.append(S.AnalysisCompound(
            entity=entity, call=k.get("call"), reason=k.get("reason"), ic50_um=c.get("ic50_um"),
            ci=list(ci) if ci else None, n_points=c.get("n_points"),
            top_known=(c.get("fit_quality") == "known-max") if c.get("fit_quality") in ("known-max", "observed-max") else None,
            curve=_curve(entity, c, r.get("wells") or [], cfg.get("max_response"))))
    refused = bool(r.get("regime_refused") or r.get("normalization_refused"))
    return S.AnalysisResult(
        state=str(r.get("state")), z_prime=r.get("z_prime"), z_kind=r.get("z_prime_kind"),
        z_note=r.get("z_prime_note"), qc_hold=bool(r.get("qc_hold")), refused=refused,
        note=r.get("normalization_note") or (r.get("shape_only") if isinstance(r.get("shape_only"), str) else None),
        gate=gate, compounds=out)


def _view(doc: dict) -> S.AnalysisView:
    return S.AnalysisView(
        id=doc["id"], filename=_src(doc).get("original_name"), sha256=_src(doc).get("sha256"),
        state=doc["state"], revision=doc["revision"], preview=_preview(doc.get("preview") or {}),
        result=_result(doc),
        reviews=[S.AnalysisReviewEntry(action=d["action"], reason=d.get("reason", ""),
                                       target=d.get("target", ""), by=d.get("actor", "?"), ts=d["at"])
                 for d in doc.get("dispositions") or []],
        attachments=[S.AnalysisAttachment(**a) for a in doc.get("attachments") or []])


# ------------------------------------------------------------------ routes
@router.get("", response_model=list[S.AnalysisSummary])
def list_analyses() -> list[S.AnalysisSummary]:
    store.ensure_tables()
    out = []
    for a in store.list_recent():
        try:
            name = _src(store.get(a["id"])).get("original_name")
        except KeyError:
            name = None
        out.append(S.AnalysisSummary(id=a["id"], filename=name, state=a["state"],
                                     updated_at=a["updated_at"]))
    return out


@router.post("", response_model=S.AnalysisView)
async def create_analysis(request: Request, file: UploadFile = File(...),
                          layout: UploadFile | None = File(None)) -> S.AnalysisView:
    """Store the file (bound by digest), detect what it is. No fit, no verdict."""
    store.ensure_tables()
    aid = f"an-{uuid.uuid4().hex[:8]}"
    try:
        src = store.store_artifact(aid, "source", file.filename or "upload", await file.read())
        lay = (store.store_artifact(aid, "layout", layout.filename, await layout.read())
               if layout is not None and layout.filename else None)
    except ValueError as exc:
        raise _problem(422, "rejected-upload", "File rejected", str(exc)) from None
    try:
        preview = EA.preview("plate_assay", Path(src.storage_path), {},
                             layout_path=lay.storage_path if lay else None)
    except EA.AnalysisError as exc:
        raise _problem(422, exc.code, "Could not read this file", exc.message) from None
    store.create(aid, "plate_assay", {}, src, lay, preview)
    _seal(aid, EventType.experiment_defined, who(request), {
        "kind": "analysis_created", "source_sha256": src.sha256, "original_name": src.original_name,
        "layout_sha256": lay.sha256 if lay else None, "preview_state": preview.get("state")})
    return _view(store.get(aid))


@router.get("/{aid}", response_model=S.AnalysisView)
def get_analysis(aid: str) -> S.AnalysisView:
    return _view(_doc(aid))


@router.post("/{aid}/run", response_model=S.AnalysisView)
def run_analysis(aid: str, body: S.AnalysisRun, request: Request) -> S.AnalysisView:
    """Confirm the interpretation and fit. A changed confirmation opens a new
    immutable revision. QC holds and regime refusals come back as states."""
    doc = _doc(aid)
    cfg = {k: v for k, v in (doc.get("config") or {}).items()
           if k not in ("metric", "direction", "threshold", "max_response")}
    if body.threshold is not None:
        cfg.update(metric="ic50_um", direction=body.direction, threshold=body.threshold)
    if body.max_response is not None:
        cfg["max_response"] = body.max_response
    if body.evidence_origin:
        cfg["evidence_origin"] = body.evidence_origin
    src, user = _verified_src(doc), who(request)
    try:
        preview = EA.preview(doc["profile"], Path(src["storage_path"]), cfg, layout_path=_layout(doc))
        doc = store.reconfigure(aid, cfg, preview)
        state = AnalysisState(doc["state"])
        if state not in RUNNABLE:
            raise _problem(409, "needs-input", "Cannot fit yet",
                           "; ".join(d["message"] for d in preview.get("diagnostics") or [])
                           or f"state is {doc['state']}")
        result = EA.analyze(doc["profile"], Path(src["storage_path"]), cfg,
                            source_sha256=src.get("sha256"), layout_path=_layout(doc))
    except EA.AnalysisError as exc:
        raise _problem(409 if exc.code == "unreadable_source" else 422, exc.code,
                       "Analysis failed", exc.message) from None
    out = store.store_result(aid, result)
    _seal(aid, EventType.evaluation, user, {
        "kind": "analysis_complete", "revision": out["revision"], "state": result.get("state"),
        "source_sha256": src.get("sha256"), "config": cfg, "n_calls": len(result.get("calls") or []),
        "z_prime": result.get("z_prime"), "z_prime_kind": result.get("z_prime_kind"),
        "regime_refused": result.get("regime_refused")})
    return _view(out)


@router.post("/{aid}/review", response_model=S.AnalysisView)
def review(aid: str, body: S.AnalysisReviewIn, request: Request) -> S.AnalysisView:
    """A human disposition, beside the computed call — never overwriting it."""
    doc = _doc(aid)
    if doc.get("result") is None:
        raise _problem(409, "nothing-to-review", "Nothing to review", "run the analysis first")
    if AnalysisState(doc["state"]) not in REVIEWABLE:
        raise _problem(409, "not-reviewable", "Cannot review", doc["state"])
    user = who(request)
    out = store.add_disposition(aid, HumanDisposition(
        action=DispositionAction(body.action), reason=body.reason, target=body.target, actor=user))
    _seal(aid, EventType.stage_transition, user, {
        "kind": "analysis_reviewed", "action": body.action, "reason": body.reason,
        "target": body.target, "note": "human disposition — the computed call is unchanged"})
    return _view(out)


@router.post("/{aid}/attach", response_model=S.AnalysisView)
def attach(aid: str, body: S.AnalysisAttachIn, request: Request) -> S.AnalysisView:
    """Cite this analysis in a campaign's ledger as supporting evidence. It is
    context for the people reading the campaign: it does not change any
    verdict, and simulated/predicted data cannot be attached as measured."""
    import time

    from proef.api.v1.campaigns import _load
    doc = _doc(aid)
    r = doc.get("result")
    if r is None:
        raise _problem(409, "nothing-to-attach", "Nothing to attach", "run the analysis first")
    if doc["state"] != AnalysisState.reviewed.value:
        raise _problem(409, "review-first", "Review before attaching",
                       "Record your disposition on the result, then attach it.")
    origin = str(r.get("evidence_origin") or "unknown")
    if origin in ("simulated", "predicted", "unknown"):
        raise _problem(409, "proxy-evidence", "Not measured data",
                       f"This analysis is marked '{origin}'. Only measured or historical data "
                       "can be attached as evidence.")
    _, _, _, branch, _ = _load(body.campaign_id)
    if not branch:
        raise _problem(409, "no-ledger", "Campaign has no ledger branch yet", body.campaign_id)
    user = who(request)
    calls = {c["entity"]: c.get("call") for c in r.get("calls") or []}
    _seal(aid, EventType.gate_decision, user, {
        "kind": "analysis_attached", "analysis_id": aid, "revision": doc["revision"],
        "source_sha256": _src(doc).get("sha256"), "evidence_origin": origin,
        "candidate": body.candidate, "calls": calls, "note": body.note,
        "effect": "context only — no campaign verdict is changed by this record"}, branch=branch)
    att = {"campaign_id": body.campaign_id, "candidate": body.candidate, "by": user, "ts": time.time()}
    out = store.update(aid, doc["state"], lambda d: d.setdefault("attachments", []).append(att))
    return _view(out)


def _chain_status(aid: str) -> str:
    from proef.adapters.store.sqlite import get_store
    if not Path(_ids.PROVENANCE_DB).exists():
        return "no provenance records for this analysis"
    s = get_store(str(_ids.PROVENANCE_DB))
    branch = f"analysis/{aid}"
    if not s.branch_records(branch):
        return "no provenance records for this analysis"
    if s.verify_chain(branch_id=branch):
        raise _problem(409, "chain-tampered", "Provenance chain tampered",
                       "the report is refused while the analysis branch fails verification")
    return "intact (recomputed)"


@router.get("/{aid}/report", response_class=HTMLResponse)
def report(aid: str) -> HTMLResponse:
    from proef.analysis_report import render_report
    doc = _doc(aid)
    if doc.get("result") is None:
        raise _problem(409, "nothing-to-report", "No result yet", "run the analysis first")
    return HTMLResponse(render_report(doc, _chain_status(aid)))


@router.get("/{aid}/export.csv")
def export_csv(aid: str) -> Response:
    """Raw and normalized values side by side, with the call and reason per row."""
    from proef.analysis_profiles import plate_assay
    from proef.analysis_report import export_csv as _csv
    doc = _doc(aid)
    if doc.get("result") is None:
        raise _problem(409, "nothing-to-export", "No result yet", "run the analysis first")
    try:
        cfg = plate_assay.CONFIG_TYPE(**(doc.get("config") or {}))
        lay = _layout(doc)
        records = plate_assay.records_for(Path(_verified_src(doc)["storage_path"]), cfg,
                                          layout_path=Path(lay) if lay else None)
    except Exception as exc:  # noqa: BLE001
        raise _problem(409, "source-unreadable", "Source no longer parses", str(exc)) from None
    return Response(_csv(doc, records, doc["result"]), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{aid}-export.csv"'})
