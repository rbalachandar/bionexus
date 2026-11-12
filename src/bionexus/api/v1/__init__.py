"""Workbench API v1 — a resource model over the engine's read-models."""
from fastapi import APIRouter

from bionexus.api.v1.campaigns import router as campaigns_router

router = APIRouter(prefix="/api/v1")
router.include_router(campaigns_router)
