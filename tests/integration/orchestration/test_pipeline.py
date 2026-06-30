"""Integration tests for the agent pipeline."""

import pytest

from core.models.case import CaseContext
from orchestration.pipeline import CasePipeline


@pytest.mark.asyncio
async def test_pipeline_executes_all_agents() -> None:
    pipeline = CasePipeline()
    context = CaseContext(
        case_id="CASE-001",
        blueprint="maestro-case",
        raw_payload={"caseId": "CASE-001"},
    )

    decision = await pipeline.execute(context)

    assert decision.case_id == "CASE-001"
    assert decision.outcome == "pending_review"
