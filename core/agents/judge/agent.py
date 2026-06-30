"""Judge agent — evaluates evidence and renders a case decision."""

from core.agents.base import BaseAgent
from core.models.case import AgentResult, CaseContext, CaseDecision


class JudgeAgent(BaseAgent):
    """Produces a structured decision from detective findings."""

    name = "judge"

    async def run(self, context: CaseContext) -> AgentResult:
        decision = CaseDecision(
            case_id=context.case_id,
            outcome="pending_review",
            rationale="Awaiting detective evidence.",
            evidence=context.metadata.get("detective_output", {}),
        )

        return AgentResult(
            agent_name=self.name,
            success=True,
            output={
                "case_id": decision.case_id,
                "outcome": decision.outcome,
                "rationale": decision.rationale,
                "evidence": decision.evidence,
            },
        )
