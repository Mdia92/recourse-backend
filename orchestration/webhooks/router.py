"""Webhook routing for external integrations."""

from fastapi import APIRouter

from orchestration.webhooks.uipath_maestro import router as maestro_router

router = APIRouter()
router.include_router(maestro_router, prefix="/uipath", tags=["uipath"])
