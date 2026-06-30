"""Abstract base contract for Recourse agents."""

from abc import ABC, abstractmethod

from core.models.case import AgentResult, CaseContext


class BaseAgent(ABC):
    """Base class for intake, detective, and judge agents."""

    name: str

    @abstractmethod
    async def run(self, context: CaseContext) -> AgentResult:
        """Execute the agent against the given case context."""
