"""Judge agent — microinsurance policy threshold adjudication."""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import Any

logger = logging.getLogger("recourse.judge")

# Standard microinsurance auto-approval policy thresholds.
COVERED_DAMAGE_TYPES: frozenset[str] = frozenset({"water", "fire", "theft", "wind"})
FRAUD_RISK_THRESHOLD = 0.3  # Auto-approve only when score is strictly below this value.
MAX_AUTO_APPROVE_LOSS_USD = 5000.0  # Auto-approve only when loss is strictly under $5,000.


class ClaimOutcome(StrEnum):
    """Explicit adjudication outcomes returned to orchestration."""

    APPROVED = "APPROVED"
    DENIED = "DENIED"


class JudgeAgent:
    """
    Renders a final claim decision from intake and detective outputs.

    Compares damage classification, fraud risk, and loss amount against
    standard microinsurance threshold policies to produce an auto-approval or
    denial with a written rationale.
    """

    def __init__(
        self,
        *,
        covered_damage_types: frozenset[str] | None = None,
        fraud_risk_threshold: float = FRAUD_RISK_THRESHOLD,
        max_auto_approve_loss_usd: float = MAX_AUTO_APPROVE_LOSS_USD,
    ) -> None:
        self._covered_damage_types = covered_damage_types or COVERED_DAMAGE_TYPES
        self._fraud_risk_threshold = fraud_risk_threshold
        self._max_auto_approve_loss_usd = max_auto_approve_loss_usd

    async def run(
        self,
        intake_output: dict[str, Any],
        detective_output: dict[str, Any],
        *,
        case_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Evaluate a claim against microinsurance auto-approval policies.

        Parameters
        ----------
        intake_output:
            Sanitized output from ``IntakeClerk.process()``.
        detective_output:
            Fraud analysis output from ``DetectiveAgent.run()``.
        case_context:
            Optional mutable case metadata dict; when provided, sets
            ``judge_output`` on the block before returning.

        Returns
        -------
        dict
            Decision record with explicit ``APPROVED`` or ``DENIED`` outcome
            and a written ``reason`` string.
        """
        claim_id = str(intake_output.get("claim_id", detective_output.get("claim_id", "unknown")))
        damage_type = str(intake_output.get("damage_type", "unknown")).lower()
        loss_amount = intake_output.get("loss_amount_usd")
        fraud_risk_score = detective_output.get("fraud_risk_score")

        policy_checks = {
            "damage_covered": self._is_damage_covered(damage_type),
            "fraud_below_threshold": self._is_fraud_acceptable(fraud_risk_score),
            "loss_under_limit": self._is_loss_under_limit(loss_amount),
        }

        all_passed = all(policy_checks.values())
        outcome = ClaimOutcome.APPROVED if all_passed else ClaimOutcome.DENIED
        reason = self._build_reason(
            outcome=outcome,
            damage_type=damage_type,
            loss_amount=loss_amount,
            fraud_risk_score=fraud_risk_score,
            policy_checks=policy_checks,
        )

        result = {
            "claim_id": claim_id,
            "outcome": outcome.value,
            "reason": reason,
            "policy_checks": policy_checks,
            "policy_thresholds": {
                "covered_damage_types": sorted(self._covered_damage_types),
                "fraud_risk_threshold": self._fraud_risk_threshold,
                "max_auto_approve_loss_usd": self._max_auto_approve_loss_usd,
            },
            "inputs": {
                "damage_type": damage_type,
                "loss_amount_usd": loss_amount,
                "fraud_risk_score": fraud_risk_score,
            },
        }

        if case_context is not None:
            case_context["judge_output"] = result

        logger.info(
            "Judge decision — claim_id=%s outcome=%s",
            claim_id,
            outcome.value,
        )

        return result

    def _is_damage_covered(self, damage_type: str) -> bool:
        """Return True when the classified damage type is within policy coverage."""
        return damage_type in self._covered_damage_types

    def _is_fraud_acceptable(self, fraud_risk_score: Any) -> bool:
        """Return True when the fraud risk score is strictly below the threshold."""
        if fraud_risk_score is None:
            return False
        try:
            score = float(fraud_risk_score)
        except (TypeError, ValueError):
            return False
        return score < self._fraud_risk_threshold

    def _is_loss_under_limit(self, loss_amount: Any) -> bool:
        """Return True when the declared loss is strictly under the auto-approve cap."""
        if loss_amount is None:
            return False
        try:
            amount = float(loss_amount)
        except (TypeError, ValueError):
            return False
        if amount < 0:
            return False
        return amount < self._max_auto_approve_loss_usd

    def _build_reason(
        self,
        *,
        outcome: ClaimOutcome,
        damage_type: str,
        loss_amount: Any,
        fraud_risk_score: Any,
        policy_checks: dict[str, bool],
    ) -> str:
        """Compose a written rationale explaining the adjudication outcome."""
        if outcome == ClaimOutcome.APPROVED:
            return (
                f"Claim auto-approved: damage type '{damage_type}' is covered, "
                f"fraud risk score {fraud_risk_score} is below "
                f"{self._fraud_risk_threshold}, and loss amount ${loss_amount:,.2f} "
                f"is under ${self._max_auto_approve_loss_usd:,.0f}."
            )

        failures: list[str] = []

        if not policy_checks["damage_covered"]:
            covered = ", ".join(sorted(self._covered_damage_types))
            failures.append(
                f"damage type '{damage_type}' is not covered (eligible types: {covered})"
            )

        if not policy_checks["fraud_below_threshold"]:
            if fraud_risk_score is None:
                failures.append("fraud risk score is unavailable")
            else:
                failures.append(
                    f"fraud risk score {fraud_risk_score} is not below "
                    f"{self._fraud_risk_threshold}"
                )

        if not policy_checks["loss_under_limit"]:
            if loss_amount is None:
                failures.append("loss amount was not provided")
            else:
                failures.append(
                    f"loss amount ${float(loss_amount):,.2f} exceeds the "
                    f"${self._max_auto_approve_loss_usd:,.0f} auto-approval limit"
                )

        return "Claim denied: " + "; ".join(failures) + "."
