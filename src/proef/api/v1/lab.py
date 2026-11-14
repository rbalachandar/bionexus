"""/api/v1/lab — what hardware exists (real vs simulated) and what the agents may do."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from proef.api.v1 import schemas as S
from proef.api.v1.deps import who
from proef.api.v1.governance import _state as halt_state

router = APIRouter(prefix="/lab", tags=["lab"])


@router.get("/instruments", response_model=list[S.Instrument])
def instruments() -> list[S.Instrument]:
    from proef.labselect import available_instruments
    out = []
    for i in available_instruments():
        out.append(S.Instrument(
            id=i["id"], name=i.get("name") or i["id"], kind=i.get("kind", "?"),
            vendor=i.get("vendor"), simulated=bool(i.get("simulated")),
            hardware_validated=bool(i.get("hardware_validated")),
            installed=bool(i.get("installed", True)),
            requires_network=i.get("requires_network"),
            assay_types=list(i.get("assay_types") or []),
            readouts=list(i.get("readouts") or []), note=i.get("note")))
    # honest ordering: validated hardware first, then real-but-unvalidated, then simulated
    return sorted(out, key=lambda x: (not x.hardware_validated, x.simulated, x.name))


@router.get("/authority", response_model=S.Authority)
def authority() -> S.Authority:
    from proef.adapters.bio.tox_alerts import RULES_VERSION
    from proef.governance import AuthorizationMatrix, SopRegistry
    return S.Authority(
        rules=[S.AuthorityRule(**r) for r in AuthorizationMatrix().describe()],
        sops_pending=[S.Sop(id=p["id"], objective=p.get("objective", ""),
                            assay=p.get("assay")) for p in SopRegistry().pending()],
        halt=halt_state(), safety_rules=str(RULES_VERSION))


@router.post("/sops/{sop_id}/approve", response_model=S.Authority)
def approve_sop(sop_id: str, request: Request) -> S.Authority:
    """Sign off a recurring procedure: from now on it may run unattended.
    Attributed to the authenticated person."""
    from proef.governance import SopRegistry
    if not SopRegistry().approve(sop_id, by=who(request)):
        raise HTTPException(404, S.Problem(
            type="sop-not-found", title="SOP not found", detail=sop_id).model_dump())
    return authority()
