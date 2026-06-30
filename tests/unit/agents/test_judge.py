"""Unit tests for the Judge agent."""

import pytest

from core.agents.judge import JudgeAgent
from core.models.case import CaseContext


@pytest.mark.asyncio
async def test_judge_produces_decision() -> None:
    agent = JudgeAgent()
    context = CaseContext(
        case_id="CASE-001",
        blueprint="maestro-case",
        raw_payload={},
        metadata={"detective_output": {"findings": ["sample"]}},
    )

    result = await agent.run(context)

    assert result.success is True
    assert result.output["case_id"] == "CASE-001"
    assert "outcome" in result.output
    assert "rationale" in result.output
