"""Intake agent — validates and normalizes incoming Maestro Case events."""

from core.agents.base import BaseAgent
from core.models.case import AgentResult, CaseContext


class IntakeAgent(BaseAgent):
    """Receives raw webhook payloads and produces a normalized CaseContext."""

    name = "intake"

    async def run(self, context: CaseContext) -> AgentResult:
        if not context.case_id:
            return AgentResult(
                agent_name=self.name,
                success=False,
                errors=["case_id is required"],
            )

        return AgentResult(
            agent_name=self.name,
            success=True,
            output={
                "case_id": context.case_id,
                "blueprint": context.blueprint,
                "status": "normalized",
            },
        )
