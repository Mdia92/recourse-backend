"""Unit tests for the Detective agent."""

import pytest

from core.agents.detective import DetectiveAgent
from core.models.case import CaseContext


@pytest.mark.asyncio
async def test_detective_returns_evidence_structure() -> None:
    agent = DetectiveAgent()
    context = CaseContext(
        case_id="CASE-001",
        blueprint="maestro-case",
        raw_payload={},
    )

    result = await agent.run(context)

    assert result.success is True
    assert result.output["case_id"] == "CASE-001"
    assert "findings" in result.output
