"""End-to-end claim pipeline integration tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest
from httpx import ASGITransport

from orchestration import routes
from orchestration.app import app

FRAUD_TRIGGER_PAYLOAD = {
    "claim_id": "FRAUD-PIPELINE-001",
    "raw_text": (
        "Urgent kitchen water damage immediately. Inflated repair estimate of $8,750 "
        "submitted ASAP for same-day wire transfer."
    ),
    "photos_urls": [
        "https://storage.example.com/evidence/photo-8821.png",
        "https://storage.example.com/evidence/photo-8821.png",
    ],
    "voice_note_url": None,
}


async def _mock_authenticate(*_args, **_kwargs) -> str:
    return "test-bearer-token"


async def _mock_verify_bearer_token(*_args, **_kwargs) -> None:
    return None


async def _mock_create_human_validation_task(**kwargs) -> dict:
    return {
        "claim_id": kwargs["claim_id"],
        "task_response": {"taskId": 1001},
    }


@pytest.mark.asyncio
async def test_claim_pipeline_paused_for_human_review_on_fraud_thresholds() -> None:
    """
    A claim with duplicate photos and an inflated loss must be denied and paused.

    Expects the judge rationale to reference the fraud risk threshold (0.3) and
    returns pipeline_status paused_for_human_review after UiPath escalation.
    """
    transport = ASGITransport(app=app)

    mock_client = AsyncMock()
    mock_client.create_human_validation_task = AsyncMock(side_effect=_mock_create_human_validation_task)

    with (
        patch("orchestration.routes.authenticate", new=AsyncMock(side_effect=_mock_authenticate)),
        patch(
            "orchestration.routes.verify_bearer_token_against_uipath",
            new=AsyncMock(side_effect=_mock_verify_bearer_token),
        ),
        patch(
            "orchestration.routes._get_uipath_client",
            return_value=mock_client,
        ),
    ):
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post("/webhook/claims", json=FRAUD_TRIGGER_PAYLOAD)

    assert response.status_code == 202

    body = response.json()
    assert body["pipeline_status"] == "paused_for_human_review"
    assert body["uipath_task_created"] is True
    assert body["outcome"] == "DENIED"

    judge_reason = body["reason"]
    judge_context_reason = body["pipeline"]["judge"]["context"]["reason"]

    assert judge_reason == judge_context_reason
    assert "fraud risk score" in judge_reason.lower()
    assert "0.3" in judge_reason
    assert "not below" in judge_reason.lower()

    detective_context = body["pipeline"]["detective"]["context"]
    assert detective_context["fraud_risk_score"] >= 0.3
    assert detective_context["duplicate_photo_matches"]
