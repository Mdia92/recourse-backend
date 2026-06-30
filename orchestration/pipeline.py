"""Agent execution pipeline for Maestro Case processing."""

from core.agents import DetectiveAgent, IntakeAgent, JudgeAgent
from core.models.case import AgentResult, CaseContext, CaseDecision


class CasePipeline:
    """Coordinates the Intake → Detective → Judge agent workflow."""

    def __init__(self) -> None:
        self._intake = IntakeAgent()
        self._detective = DetectiveAgent()
        self._judge = JudgeAgent()

    async def execute(self, context: CaseContext) -> CaseDecision:
        intake_result = await self._run_agent(self._intake, context)
        if not intake_result.success:
            return self._failed_decision(context.case_id, intake_result)

        context.metadata["intake_output"] = intake_result.output

        detective_result = await self._run_agent(self._detective, context)
        if not detective_result.success:
            return self._failed_decision(context.case_id, detective_result)

        context.metadata["detective_output"] = detective_result.output

        judge_result = await self._run_agent(self._judge, context)
        if not judge_result.success:
            return self._failed_decision(context.case_id, judge_result)

        return CaseDecision(
            case_id=judge_result.output["case_id"],
            outcome=judge_result.output["outcome"],
            rationale=judge_result.output["rationale"],
            evidence=judge_result.output.get("evidence", {}),
        )

    async def _run_agent(self, agent, context: CaseContext) -> AgentResult:
        return await agent.run(context)

    def _failed_decision(self, case_id: str, result: AgentResult) -> CaseDecision:
        return CaseDecision(
            case_id=case_id,
            outcome="error",
            rationale=f"{result.agent_name} agent failed: {', '.join(result.errors)}",
        )
