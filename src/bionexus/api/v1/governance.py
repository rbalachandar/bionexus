"""/api/v1/halt — the operator stop-condition, outside the agent's reach."""
from __future__ import annotations

from fastapi import APIRouter, Request

from bionexus.api.v1 import schemas as S
from bionexus.api.v1.deps import who

router = APIRouter(tags=["governance"])


def _state() -> S.HaltState:
    from bionexus.governance import HaltSwitch
    hs = HaltSwitch()
    halt = hs.engaged()
    reason = (halt.get("reason") if isinstance(halt, dict) else str(halt)) if halt else None
    return S.HaltState(halted=halt is not None, reason=reason, history=hs.history())


@router.get("/halt", response_model=S.HaltState)
def get_halt() -> S.HaltState:
    return _state()


@router.post("/halt", response_model=S.HaltState)
def set_halt(body: S.HaltIn, request: Request) -> S.HaltState:
    """Engage or clear the halt. Clearing is a deliberate human act and is
    attributed to the authenticated person, like every other decision."""
    from bionexus.governance import HaltSwitch
    hs = HaltSwitch()
    if body.halted:
        hs.engage(f"{body.reason or 'operator halt (workbench)'} [by {who(request)}]")
    else:
        hs.clear()
    return _state()
