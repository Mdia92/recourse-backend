"""Maestro Case claim webhook routes and agent execution hooks."""

from __future__ import annotations

import logging
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, HttpUrl

from config.uipath_config import (
    UiPathAuthenticationError,
    UiPathConfig,
    authenticate,
    load_uipath_config,
)
from configuration.uipath_api import UiPathOrchestratorClient, UiPathOrchestratorError
from core.detective import DetectiveAgent
from core.judge import FRAUD_RISK_THRESHOLD, ClaimOutcome, JudgeAgent
from core.intake import IntakeClerk
from core.models.case import CaseContext

logger = logging.getLogger("recourse.routes")

router = APIRouter(tags=["claims"])

_intake_clerk = IntakeClerk()
_detective_agent = DetectiveAgent()
_judge_agent = JudgeAgent()


def _get_uipath_client() -> UiPathOrchestratorClient:
    """Build Orchestrator client using the latest loaded tenant configuration."""
    config = load_uipath_config()
    folder_id = config.organization_unit_id.strip() or None
    return UiPathOrchestratorClient(config, organization_unit_id=folder_id)

ORCHESTRATOR_STATUS_PATH = "/orchestrator_/api/Status"
UIPATH_VERIFY_TIMEOUT_SECONDS = 30.0


class ClaimPayload(BaseModel):
    """Inbound claim payload from the UiPath Maestro Case dashboard."""

    claim_id: str = Field(..., description="Unique claim identifier from Maestro Case.")
    raw_text: str = Field(..., description="Free-text claim description supplied by the claimant.")
    photos_urls: list[HttpUrl] = Field(
        default_factory=list,
        description="URLs of photo evidence attached to the claim.",
    )
    voice_note_url: HttpUrl | None = Field(
        default=None,
        description="Optional URL of a voice-note recording for the claim.",
    )


async def verify_bearer_token_against_uipath(
    config: UiPathConfig,
    access_token: str,
) -> None:
    """
    Confirm the bearer token is accepted by UiPath Cloud Orchestrator.

    Performs a lightweight authenticated GET against the tenant Orchestrator
    status endpoint. Raises on network or authorization failures.
    """
    status_url = f"{config.cloud_base_url.rstrip('/')}{ORCHESTRATOR_STATUS_PATH}"
    headers = {"Authorization": f"Bearer {access_token}"}

    try:
        async with httpx.AsyncClient(timeout=UIPATH_VERIFY_TIMEOUT_SECONDS) as client:
            response = await client.get(status_url, headers=headers)
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"UiPath bearer token verification failed (HTTP {exc.response.status_code}).",
        ) from exc
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="UiPath bearer token verification failed due to a network error.",
        ) from exc


def _build_case_context(claim: ClaimPayload) -> CaseContext:
    """Map an inbound claim payload to the shared agent CaseContext."""
    return CaseContext(
        case_id=claim.claim_id,
        blueprint="maestro-case",
        raw_payload=claim.model_dump(mode="json"),
        metadata={
            "raw_text": claim.raw_text,
            "photos_urls": [str(url) for url in claim.photos_urls],
            "voice_note_url": str(claim.voice_note_url) if claim.voice_note_url else None,
        },
    )


async def run_intake_hook(context: CaseContext) -> dict[str, Any]:
    """
    Execution hook for the Intake clerk.

    Runs ``IntakeClerk`` to classify damage type and extract metadata, then
    stores the sanitized context on the case for downstream agents.
    """
    sanitized = await _intake_clerk.process(
        claim_id=context.case_id,
        raw_text=str(context.metadata.get("raw_text", "")),
        photos_urls=context.metadata.get("photos_urls"),
        voice_note_url=context.metadata.get("voice_note_url"),
    )
    context.metadata["intake_output"] = sanitized

    return {
        "agent": "intake",
        "status": "completed",
        "case_id": context.case_id,
        "context": sanitized,
    }


async def run_detective_hook(context: CaseContext) -> dict[str, Any]:
    """
    Execution hook for the Detective agent.

    Cross-references intake output against mock claim history and appends
    ``detective_output`` to the case context block.
    """
    intake_output = context.metadata.get("intake_output")
    if not intake_output:
        return {
            "agent": "detective",
            "status": "skipped",
            "case_id": context.case_id,
            "error": "intake_output missing — run intake hook first",
        }

    detective_result = await _detective_agent.run(
        intake_output,
        photos_urls=context.metadata.get("photos_urls"),
        case_context=context.metadata,
    )

    return {
        "agent": "detective",
        "status": "completed",
        "case_id": context.case_id,
        "context": detective_result,
    }


async def run_judge_hook(context: CaseContext) -> dict[str, Any]:
    """
    Execution hook for the Judge agent.

    Evaluates intake and detective outputs against microinsurance policy
    thresholds and appends ``judge_output`` to the case context block.
    """
    intake_output = context.metadata.get("intake_output")
    detective_output = context.metadata.get("detective_output")

    if not intake_output or not detective_output:
        return {
            "agent": "judge",
            "status": "skipped",
            "case_id": context.case_id,
            "error": "intake_output and detective_output required — run prior hooks first",
        }

    judge_result = await _judge_agent.run(
        intake_output,
        detective_output,
        case_context=context.metadata,
    )

    return {
        "agent": "judge",
        "status": "completed",
        "case_id": context.case_id,
        "context": judge_result,
    }


async def execute_claim_pipeline(context: CaseContext) -> dict[str, Any]:
    """
    Run the full Intake → Detective → Judge pipeline sequentially.

    Each step must complete before the next begins. Outputs are accumulated on
    ``context.metadata`` and returned as a composite pipeline dictionary.
    """
    pipeline: dict[str, Any] = {}

    # Step 1 — Intake: categorize damage and extract metadata.
    pipeline["intake"] = await run_intake_hook(context)

    # Step 2 — Detective: fraud analysis (requires intake_output).
    pipeline["detective"] = await run_detective_hook(context)

    # Step 3 — Judge: policy decision (requires intake + detective outputs).
    pipeline["judge"] = await run_judge_hook(context)

    judge_step = pipeline["judge"]
    judge_context = judge_step.get("context") if judge_step.get("status") == "completed" else {}

    intake_output = context.metadata.get("intake_output") or {}
    detective_output = context.metadata.get("detective_output") or {}
    outcome = judge_context.get("outcome")
    fraud_risk_score = detective_output.get("fraud_risk_score")

    requires_human_review = _requires_human_validation(
        outcome=outcome,
        fraud_risk_score=fraud_risk_score,
    )

    uipath_task_created = False
    if requires_human_review:
        try:
            validation_result = await _get_uipath_client().create_human_validation_task(
                claim_id=context.case_id,
                fraud_findings=list(detective_output.get("findings", [])),
                loss_summary=str(intake_output.get("summary", "")),
            )
            context.metadata["uipath_human_validation_task"] = validation_result
            uipath_task_created = True
            logger.info(
                "UiPath human validation task created — claim_id=%s",
                context.case_id,
            )
        except UiPathOrchestratorError as exc:
            logger.warning(
                "UiPath human validation integration error — claim_id=%s error=%s "
                "(pipeline continuing for demo; task not created in Action Center)",
                context.case_id,
                exc,
            )
            context.metadata["uipath_integration_error"] = str(exc)

    pipeline_status = (
        "paused_for_human_review"
        if requires_human_review
        else _pipeline_status(pipeline)
    )

    return {
        "pipeline": pipeline,
        "case_context": {
            "intake_output": context.metadata.get("intake_output"),
            "detective_output": context.metadata.get("detective_output"),
            "judge_output": context.metadata.get("judge_output"),
        },
        "outcome": outcome,
        "reason": judge_context.get("reason"),
        "pipeline_status": pipeline_status,
        "uipath_task_created": uipath_task_created,
    }


def _requires_human_validation(
    *,
    outcome: str | None,
    fraud_risk_score: Any,
) -> bool:
    """Return True when the claim must be escalated to a human adjuster."""
    if outcome == ClaimOutcome.DENIED.value:
        return True

    if fraud_risk_score is None:
        return False

    try:
        return float(fraud_risk_score) >= FRAUD_RISK_THRESHOLD
    except (TypeError, ValueError):
        return False


def _pipeline_status(pipeline: dict[str, Any]) -> str:
    """Derive an overall pipeline status from individual agent step results."""
    statuses = [step.get("status") for step in pipeline.values()]
    if all(status == "completed" for status in statuses):
        return "completed"
    if any(status == "skipped" for status in statuses):
        return "partial"
    return "failed"


@router.post("/webhook/claims", status_code=status.HTTP_202_ACCEPTED)
async def receive_claim_webhook(claim: ClaimPayload) -> dict[str, Any]:
    """
    Accept a claim payload from the Maestro Case dashboard.

    Authenticates against UiPath Cloud, verifies the bearer token, then runs the
    Intake → Detective → Judge pipeline sequentially and returns the full
    composite pipeline output to the caller.
    """
    uipath_config = load_uipath_config()

    try:
        access_token = await authenticate(uipath_config)
    except UiPathAuthenticationError as exc:
        logger.error("UiPath authentication failed for claim_id=%s", claim.claim_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    await verify_bearer_token_against_uipath(uipath_config, access_token)

    logger.info(
        "Claim webhook received — claim_id=%s photos=%d voice_note=%s",
        claim.claim_id,
        len(claim.photos_urls),
        "present" if claim.voice_note_url else "none",
    )
    logger.debug(
        "Claim raw_text length=%d claim_id=%s",
        len(claim.raw_text),
        claim.claim_id,
    )

    context = _build_case_context(claim)

    composite = await execute_claim_pipeline(context)

    logger.info(
        "Claim pipeline finished — claim_id=%s status=%s outcome=%s",
        claim.claim_id,
        composite["pipeline_status"],
        composite.get("outcome"),
    )

    return {
        "claim_id": claim.claim_id,
        "authenticated": True,
        "uipath_organization": uipath_config.organization_name,
        "uipath_tenant": uipath_config.tenant_name,
        **composite,
    }
