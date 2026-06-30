"""UiPath Maestro Case blueprint webhook handler."""

from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request

from config import get_settings
from core.models.case import CaseContext
from orchestration.pipeline import CasePipeline

router = APIRouter()
pipeline = CasePipeline()


@router.post("/maestro/case")
async def handle_maestro_case(
    request: Request,
    x_uipath_signature: str | None = Header(default=None),
) -> dict[str, Any]:
    """Receive and process a UiPath Maestro Case webhook event."""
    settings = get_settings()
    payload = await request.json()

    if settings.uipath_webhook_secret and not x_uipath_signature:
        raise HTTPException(status_code=401, detail="Missing webhook signature")

    case_id = str(payload.get("caseId") or payload.get("case_id") or "")
    blueprint = str(payload.get("blueprint") or "maestro-case")

    context = CaseContext(
        case_id=case_id,
        blueprint=blueprint,
        raw_payload=payload,
    )

    decision = await pipeline.execute(context)

    return {
        "case_id": decision.case_id,
        "outcome": decision.outcome,
        "rationale": decision.rationale,
        "evidence": decision.evidence,
    }
