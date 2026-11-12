"""Workbench API v1 — a resource model over the engine's read-models."""
from fastapi import APIRouter

from bionexus.api.v1.campaigns import router as campaigns_router
from bionexus.api.v1.system import router as system_router

router = APIRouter(prefix="/api/v1")
router.include_router(campaigns_router)
router.include_router(system_router)
