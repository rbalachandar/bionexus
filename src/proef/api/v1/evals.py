"""/api/v1/evals — the last `proef eval` leaderboard, with the honest sub-1.0
deductions surfaced (the harness refusing to overcredit its own agent).
A read-model of the committed artifacts, not a live re-run."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

router = APIRouter(tags=["evals"])


@router.get("/evals")
def evals() -> dict[str, Any]:
    from proef.evals.harness import leaderboard_payload
    return leaderboard_payload()
