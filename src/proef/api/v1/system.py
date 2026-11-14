"""/api/v1/system — global status for the top bar and trust strip."""
from __future__ import annotations

import time
from pathlib import Path

from fastapi import APIRouter

from proef.api.v1 import schemas as S
from proef.views import ids as _ids

router = APIRouter(prefix="/system", tags=["system"])

_chain_cache: dict = {"at": 0.0, "db": None, "value": None}


def _chain() -> S.ChainStatus:
    """Whole-ledger verification, cached for 30 s (it re-hashes every record)."""
    db = str(_ids.PROVENANCE_DB)
    now = time.time()
    if (_chain_cache["db"] == db and _chain_cache["value"] is not None
            and now - _chain_cache["at"] < 30):
        return _chain_cache["value"]
    if not Path(db).exists():
        value = S.ChainStatus(verified=True, records=0)
    else:
        from proef.adapters.store.sqlite import get_store
        store = get_store(db)
        problems = store.verify_chain()
        n = store._conn.execute("SELECT COUNT(*) FROM provenance").fetchone()[0]
        value = S.ChainStatus(verified=not problems, records=n,
                              problems=problems[:10])
    _chain_cache.update(at=now, db=db, value=value)
    return value


def _anchor() -> S.AnchorStatus | None:
    import json

    from proef import anchor
    path = Path(anchor.ANCHORS)
    if not path.exists():
        return None
    try:
        last = json.loads(path.read_text())[-1]
    except (ValueError, IndexError):
        return None
    return S.AnchorStatus(records=last.get("records", 0),
                          age_s=time.time() - last["ts"] if last.get("ts") else None,
                          published=last.get("published"))


def _eval() -> S.EvalSummary | None:
    try:
        from proef.evals.harness import leaderboard_payload
        p = leaderboard_payload()
    except Exception:
        return None
    if not p.get("available"):
        return None
    return S.EvalSummary(mean=p["mean"], tasks=p["n_tasks"],
                         all_pass=bool(p.get("all_pass")))


@router.get("/status", response_model=S.SystemStatus)
def status() -> S.SystemStatus:
    from proef.approvals import ApprovalInbox
    from proef.governance import HaltSwitch
    from proef.paths import APPROVALS_FILE
    halt = HaltSwitch().engaged()
    reason = None
    if halt:
        reason = halt.get("reason") if isinstance(halt, dict) else str(halt)
    return S.SystemStatus(
        halted=halt is not None, halt_reason=reason,
        pending_approvals=len(ApprovalInbox(str(APPROVALS_FILE)).pending()),
        chain=_chain(), anchor=_anchor(), eval=_eval())
