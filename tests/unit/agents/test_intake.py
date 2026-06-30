"""Unit tests for the Intake agent."""

import pytest

from core.agents.intake import IntakeAgent
from core.models.case import CaseContext


@pytest.mark.asyncio
async def test_intake_normalizes_valid_case() -> None:
    agent = IntakeAgent()
    context = CaseContext(
        case_id="CASE-001",
        blueprint="maestro-case",
        raw_payload={"caseId": "CASE-001"},
    )

    result = await agent.run(context)

    assert result.success is True
    assert result.output["case_id"] == "CASE-001"


@pytest.mark.asyncio
async def test_intake_rejects_missing_case_id() -> None:
    agent = IntakeAgent()
    context = CaseContext(case_id="", blueprint="maestro-case", raw_payload={})

    result = await agent.run(context)

    assert result.success is False
    assert "case_id is required" in result.errors
