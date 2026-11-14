"""Workbench API v1 — a resource model over the engine's read-models."""
from fastapi import APIRouter

from proef.api.v1.analyses import router as analyses_router
from proef.api.v1.campaigns import router as campaigns_router
from proef.api.v1.evals import router as evals_router
from proef.api.v1.evidence import router as evidence_router
from proef.api.v1.governance import router as governance_router
from proef.api.v1.inbox import router as inbox_router
from proef.api.v1.lab import router as lab_router
from proef.api.v1.programs import router as programs_router
from proef.api.v1.results import router as results_router
from proef.api.v1.system import router as system_router

router = APIRouter(prefix="/api/v1")
router.include_router(analyses_router)
router.include_router(campaigns_router)
router.include_router(evals_router)
router.include_router(evidence_router)
router.include_router(governance_router)
router.include_router(inbox_router)
router.include_router(lab_router)
router.include_router(programs_router)
router.include_router(results_router)
router.include_router(system_router)
