"""Detective agent — gathers evidence and builds an investigation record."""

from core.agents.base import BaseAgent
from core.models.case import AgentResult, CaseContext


class DetectiveAgent(BaseAgent):
    """Investigates a normalized case and compiles supporting evidence."""

    name = "detective"

    async def run(self, context: CaseContext) -> AgentResult:
        evidence = {
            "case_id": context.case_id,
            "findings": [],
            "sources_consulted": [],
        }

        return AgentResult(
            agent_name=self.name,
            success=True,
            output=evidence,
        )
