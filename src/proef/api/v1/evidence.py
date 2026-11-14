"""/api/v1/evidence — can I defend this record?

The ledger (every record re-hashed on demand), the external anchor (a Merkle
root of the whole ledger — meaningful only once it is published somewhere you
do not control), and per-campaign exports (report, lab notebook, ELN CSV).
"""
from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse

from proef import anchor as anchor_mod
from proef.api.v1 import schemas as S
from proef.api.v1 import system as system_mod
from proef.api.v1.campaigns import _load, campaign_for_problem
from proef.views import ids as _ids

router = APIRouter(prefix="/evidence", tags=["evidence"])


def _db() -> str:
    return str(_ids.PROVENANCE_DB)


def _ledger() -> S.LedgerView:
    t0 = time.time()
    if not Path(_db()).exists():
        return S.LedgerView(chain=S.ChainStatus(verified=True, records=0),
                            branches=[], verified_in_ms=0, checked_at=t0)
    from proef.adapters.store.sqlite import get_store
    store = get_store(_db())
    problems = store.verify_chain()
    bad = {p["branch"] for p in problems}
    rows = store._conn.execute(
        "SELECT branch_id, COUNT(*) FROM provenance GROUP BY branch_id").fetchall()
    branches = []
    for bid, n in rows:
        if bid.startswith("problem/"):
            camp = campaign_for_problem(bid.split("/", 1)[1])
            branches.append(S.BranchInfo(
                id=bid, kind="campaign", records=n, verified=bid not in bad,
                campaign_id=camp[0] if camp else None,
                campaign_title=camp[1] if camp else None))
        else:
            branches.append(S.BranchInfo(
                id=bid, kind="program" if bid.startswith("programs/") else "other",
                records=n, verified=bid not in bad))
    total = sum(n for _, n in rows)
    value = S.ChainStatus(verified=not problems, records=total,
                          problems=problems[:10])
    system_mod._chain_cache.update(at=time.time(), db=_db(), value=value)
    return S.LedgerView(
        chain=value, branches=sorted(branches, key=lambda b: -b.records),
        verified_in_ms=int((time.time() - t0) * 1000), checked_at=time.time())


@router.get("/ledger", response_model=S.LedgerView)
def ledger() -> S.LedgerView:
    return _ledger()


@router.post("/verify", response_model=S.LedgerView)
def verify() -> S.LedgerView:
    """Re-hash every record from its stored payload, right now."""
    return _ledger()


def _anchors() -> list[dict]:
    path = Path(anchor_mod.ANCHORS)
    try:
        return json.loads(path.read_text()) if path.exists() else []
    except ValueError:
        return []


def _anchor_view() -> S.AnchorView:
    entries = [S.AnchorEntry(ts=a["ts"], records=a["records"],
                             merkle_root=a["merkle_root"],
                             published=a.get("published"))
               for a in _anchors()]
    check = None
    if entries and Path(_db()).exists():
        v = anchor_mod.verify(_db())
        check = S.AnchorCheck(
            match=bool(v["match"]),
            appended_since_anchor=v.get("appended_since_anchor", 0),
            content_tampered=bool(v["content_tampered"]),
            current_root=v["current_root"], anchored_root=v.get("anchored_root"))
    note = ("An anchor is only protection once it is PUBLISHED somewhere you do "
            "not control: anyone who can edit this database can edit a local "
            "anchor file too." if not entries or not any(
                e.published for e in entries) else "")
    return S.AnchorView(anchors=list(reversed(entries)), check=check, note=note)


@router.get("/anchor", response_model=S.AnchorView)
def get_anchor() -> S.AnchorView:
    return _anchor_view()


@router.post("/anchor", response_model=S.AnchorView, status_code=201)
def create_anchor() -> S.AnchorView:
    """Commit the ledger's Merkle root (appended to the local anchor log)."""
    if not Path(_db()).exists():
        raise HTTPException(409, S.Problem(
            type="no-ledger", title="There is no ledger to anchor yet").model_dump())
    anchor_mod.anchor(_db())
    return _anchor_view()


@router.get("/export/{eid}")
def export(eid: str, kind: str = Query("report", pattern="^(report|notebook|eln)$")):
    """A campaign's record as a shareable file."""
    _, _, _, branch, recs = _load(eid)
    if not recs or not branch:
        raise HTTPException(404, S.Problem(
            type="no-records", title="This campaign has no records").model_dump())
    if kind == "report":
        from proef.report import build_report
        return HTMLResponse(build_report(recs))
    if kind == "notebook":
        from proef.diary import build_diary_html
        return HTMLResponse(build_diary_html(recs, branch))
    from proef.eln import export_eln
    out = Path(tempfile.mkdtemp()) / f"{eid}-eln.csv"
    export_eln(recs, str(out), None)
    return FileResponse(out, media_type="text/csv", filename=out.name)
