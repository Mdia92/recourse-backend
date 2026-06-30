"""Detective agent — fraud signals via mock claim-history cross-reference."""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger("recourse.detective")

# Simulated prior-claims ledger for duplicate photo / receipt detection.
MOCK_CLAIM_HISTORY_DB: list[dict[str, Any]] = [
    {
        "claim_id": "HIST-2024-1182",
        "claimant_hash": "c9f2a1",
        "photo_urls": [
            "https://cdn.microinsure.example/claims/kitchen-ceiling-leak.jpg",
            "https://storage.example.com/evidence/photo-8821.png",
        ],
        "receipt_amount_usd": 2500.00,
        "status": "paid",
    },
    {
        "claim_id": "HIST-2025-0044",
        "claimant_hash": "a11ef0",
        "photo_urls": [
            "https://cdn.microinsure.example/claims/burnt-countertop.jpg",
        ],
        "receipt_amount_usd": 875.50,
        "status": "denied_fraud",
    },
    {
        "claim_id": "HIST-2025-0310",
        "claimant_hash": "77bd3c",
        "photo_urls": [
            "https://storage.example.com/evidence/photo-8821.png",
        ],
        "receipt_amount_usd": 1200.00,
        "status": "under_review",
    },
]

URGENCY_KEYWORDS = ("urgent", "immediately", "asap", "today only", "wire transfer")
DUPLICATE_RECEIPT_TOLERANCE_USD = 0.01

RISK_WEIGHT_DUPLICATE_PHOTO_HISTORY = 0.35
RISK_WEIGHT_DUPLICATE_RECEIPT_HISTORY = 0.30
RISK_WEIGHT_INTRA_CLAIM_DUPLICATE_PHOTO = 0.20
RISK_WEIGHT_URGENCY_LANGUAGE = 0.10
RISK_BASELINE = 0.05


class DetectiveAgent:
    """
    Investigates intake output against a mock claim history database.

    Scans evidence URLs and summary context, flags duplicate photos or receipt
    amounts seen on prior claims, computes a dynamic fraud risk score, and
    returns a structured result for the case context block.
    """

    def __init__(self, history_db: list[dict[str, Any]] | None = None) -> None:
        self._history_db = history_db if history_db is not None else MOCK_CLAIM_HISTORY_DB

    async def run(
        self,
        intake_output: dict[str, Any],
        *,
        photos_urls: list[str] | None = None,
        case_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Cross-reference intake evidence and append detective findings.

        Parameters
        ----------
        intake_output:
            Sanitized output from ``IntakeClerk.process()``.
        photos_urls:
            Raw photo evidence URLs from the inbound claim payload.
        case_context:
            Optional mutable case metadata dict; when provided, sets
            ``detective_output`` on the block before returning.

        Returns
        -------
        dict
            Detective findings including fraud risk score and match details.
        """
        claim_id = str(intake_output.get("claim_id", "unknown"))
        summary = str(intake_output.get("summary", ""))
        loss_amount = intake_output.get("loss_amount_usd")
        evidence_meta = intake_output.get("evidence") or {}

        evidence_urls = self._collect_evidence_urls(
            photos_urls=photos_urls,
            evidence_meta=evidence_meta,
        )

        # Simulate asynchronous database lookup latency.
        await asyncio.sleep(0)

        photo_matches = self._find_duplicate_photos(evidence_urls)
        intra_claim_dupes = self._find_intra_claim_duplicate_photos(evidence_urls)
        receipt_matches = self._find_duplicate_receipts(loss_amount)
        summary_flags = self._scan_summary(summary)

        findings = self._compile_findings(
            photo_matches=photo_matches,
            intra_claim_dupes=intra_claim_dupes,
            receipt_matches=receipt_matches,
            summary_flags=summary_flags,
        )
        fraud_risk_score = self._calculate_fraud_risk_score(
            photo_matches=photo_matches,
            intra_claim_dupes=intra_claim_dupes,
            receipt_matches=receipt_matches,
            summary_flags=summary_flags,
        )

        result = {
            "claim_id": claim_id,
            "findings": findings,
            "duplicate_photo_matches": photo_matches,
            "intra_claim_duplicate_photos": intra_claim_dupes,
            "duplicate_receipt_matches": receipt_matches,
            "summary_flags": summary_flags,
            "fraud_risk_score": round(fraud_risk_score, 3),
            "risk_level": self._risk_level(fraud_risk_score),
            "evidence_urls_reviewed": evidence_urls,
            "sources_consulted": ["mock_claim_history_db"],
        }

        if case_context is not None:
            case_context["detective_output"] = result

        logger.info(
            "Detective run complete — claim_id=%s fraud_risk_score=%.3f findings=%d",
            claim_id,
            fraud_risk_score,
            len(findings),
        )

        return result

    def _collect_evidence_urls(
        self,
        *,
        photos_urls: list[str] | None,
        evidence_meta: dict[str, Any],
    ) -> list[str]:
        """Gather deduplicated evidence URLs from intake and payload."""
        urls: list[str] = []
        if photos_urls:
            urls.extend(str(url).strip() for url in photos_urls if str(url).strip())
        return list(dict.fromkeys(urls))

    def _normalize_photo_key(self, url: str) -> str:
        """Normalize a photo URL for comparison (path + filename)."""
        parsed = urlparse(url.strip().lower())
        path = parsed.path.rstrip("/")
        return path or url.strip().lower()

    def _find_duplicate_photos(self, evidence_urls: list[str]) -> list[dict[str, Any]]:
        """Match current evidence URLs against the mock claim history database."""
        matches: list[dict[str, Any]] = []
        if not evidence_urls:
            return matches

        submitted_keys = {self._normalize_photo_key(url): url for url in evidence_urls}

        for record in self._history_db:
            for historical_url in record.get("photo_urls", []):
                historical_key = self._normalize_photo_key(historical_url)
                if historical_key in submitted_keys:
                    matches.append(
                        {
                            "submitted_url": submitted_keys[historical_key],
                            "matched_history_url": historical_url,
                            "prior_claim_id": record["claim_id"],
                            "prior_claim_status": record.get("status"),
                        }
                    )
        return matches

    def _find_intra_claim_duplicate_photos(self, evidence_urls: list[str]) -> list[str]:
        """Detect duplicate photo URLs within the same claim submission."""
        seen: dict[str, str] = {}
        duplicates: list[str] = []
        for url in evidence_urls:
            key = self._normalize_photo_key(url)
            if key in seen and url not in duplicates:
                duplicates.append(url)
            seen.setdefault(key, url)
        return duplicates

    def _find_duplicate_receipts(self, loss_amount: Any) -> list[dict[str, Any]]:
        """Match declared loss amount against receipt values in claim history."""
        if loss_amount is None:
            return []

        try:
            amount = float(loss_amount)
        except (TypeError, ValueError):
            return []

        matches: list[dict[str, Any]] = []
        for record in self._history_db:
            historical_amount = record.get("receipt_amount_usd")
            if historical_amount is None:
                continue
            if abs(float(historical_amount) - amount) <= DUPLICATE_RECEIPT_TOLERANCE_USD:
                matches.append(
                    {
                        "submitted_amount_usd": amount,
                        "matched_history_amount_usd": float(historical_amount),
                        "prior_claim_id": record["claim_id"],
                        "prior_claim_status": record.get("status"),
                    }
                )
        return matches

    def _scan_summary(self, summary: str) -> list[str]:
        """Flag suspicious language patterns in the intake summary."""
        lowered = summary.lower()
        return [keyword for keyword in URGENCY_KEYWORDS if keyword in lowered]

    def _compile_findings(
        self,
        *,
        photo_matches: list[dict[str, Any]],
        intra_claim_dupes: list[str],
        receipt_matches: list[dict[str, Any]],
        summary_flags: list[str],
    ) -> list[str]:
        """Turn raw signals into human-readable finding strings."""
        findings: list[str] = []

        for match in photo_matches:
            findings.append(
                "Photo URL matches prior claim "
                f"{match['prior_claim_id']} ({match['prior_claim_status']})."
            )

        for url in intra_claim_dupes:
            findings.append(f"Duplicate photo URL submitted within this claim: {url}.")

        for match in receipt_matches:
            findings.append(
                "Receipt amount matches prior claim "
                f"{match['prior_claim_id']} (${match['matched_history_amount_usd']:.2f})."
            )

        if summary_flags:
            findings.append(
                "Summary contains urgency language: " + ", ".join(summary_flags) + "."
            )

        if not findings:
            findings.append("No duplicate evidence or receipt conflicts found in mock history.")

        return findings

    def _calculate_fraud_risk_score(
        self,
        *,
        photo_matches: list[dict[str, Any]],
        intra_claim_dupes: list[str],
        receipt_matches: list[dict[str, Any]],
        summary_flags: list[str],
    ) -> float:
        """Compute a dynamic fraud risk score between 0.0 and 1.0."""
        score = RISK_BASELINE

        if photo_matches:
            score += RISK_WEIGHT_DUPLICATE_PHOTO_HISTORY * min(len(photo_matches), 2)

        if receipt_matches:
            score += RISK_WEIGHT_DUPLICATE_RECEIPT_HISTORY * min(len(receipt_matches), 2)

        if intra_claim_dupes:
            score += RISK_WEIGHT_INTRA_CLAIM_DUPLICATE_PHOTO

        if summary_flags:
            score += RISK_WEIGHT_URGENCY_LANGUAGE

        return max(0.0, min(1.0, score))

    def _risk_level(self, score: float) -> str:
        """Map numeric fraud score to a categorical risk band."""
        if score >= 0.75:
            return "high"
        if score >= 0.45:
            return "medium"
        if score >= 0.20:
            return "low"
        return "minimal"
