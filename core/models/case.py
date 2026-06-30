"""Domain models shared across agents and orchestration."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CaseContext:
    """Normalized case payload passed between agents."""

    case_id: str
    blueprint: str
    raw_payload: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentResult:
    """Structured output from a single agent execution."""

    agent_name: str
    success: bool
    output: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


@dataclass
class CaseDecision:
    """Final adjudication produced by the Judge agent."""

    case_id: str
    outcome: str
    rationale: str
    evidence: dict[str, Any] = field(default_factory=dict)
