"""Intake clerk — LLM-assisted claim categorization and metadata extraction."""

from __future__ import annotations

import json
import logging
import re
from enum import StrEnum
from typing import Any

import httpx
from pydantic import BaseModel, Field, field_validator

from config.settings import get_settings

logger = logging.getLogger("recourse.intake")

OPENAI_CHAT_COMPLETIONS_URL = "https://api.openai.com/v1/chat/completions"
DEFAULT_LLM_MODEL = "gpt-4o-mini"
LLM_TIMEOUT_SECONDS = 45.0

# Patterns stripped from outbound summaries (basic PII hygiene).
_SSN_PATTERN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_CARD_PATTERN = re.compile(r"\b(?:\d[ -]*?){13,19}\b")
_EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")
_PHONE_PATTERN = re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")
_CURRENCY_PATTERN = re.compile(
    r"(?:\$|USD\s?)(?P<amount>\d{1,3}(?:,\d{3})*(?:\.\d{2})?|\d+(?:\.\d{2})?)",
    re.IGNORECASE,
)


class MicroinsuranceDamageType(StrEnum):
    """Supported microinsurance damage categories."""

    WATER = "water"
    FIRE = "fire"
    THEFT = "theft"
    WIND = "wind"
    LIABILITY = "liability"
    OTHER = "other"
    UNKNOWN = "unknown"


class IntakeExtraction(BaseModel):
    """Structured fields produced by the intake language model."""

    damage_type: MicroinsuranceDamageType = MicroinsuranceDamageType.UNKNOWN
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    loss_amount_usd: float | None = Field(default=None, ge=0.0)
    location: str | None = None
    summary: str = Field(default="", max_length=500)

    @field_validator("summary")
    @classmethod
    def _trim_summary(cls, value: str) -> str:
        return value.strip()[:500]


_INTAKE_SYSTEM_PROMPT = """You are an insurance intake clerk for microinsurance claims.
Analyze the claimant's description and return ONLY valid JSON with these keys:
- damage_type: one of "water", "fire", "theft", "wind", "liability", "other", "unknown"
- confidence: float 0.0-1.0 for the damage_type classification
- loss_amount_usd: numeric USD estimate or null if not mentioned
- location: city/state, address fragment, or room description; null if not mentioned
- summary: one neutral sentence describing the loss (no names, emails, phone numbers, or SSNs)

Focus on property microinsurance: burst pipes, kitchen fires, stolen items, wind damage, etc."""


class IntakeClerk:
    """
    Asynchronous intake processor for Maestro Case claim payloads.

    Extracts free-text claim descriptions, classifies microinsurance damage type via a
    lightweight LLM (``gpt-4o-mini``), pulls structured metadata, and returns a
    sanitized context dictionary safe for downstream detective and judge agents.
    """

    def __init__(self, *, model: str = DEFAULT_LLM_MODEL) -> None:
        self._model = model

    async def process(
        self,
        *,
        claim_id: str,
        raw_text: str,
        photos_urls: list[str] | None = None,
        voice_note_url: str | None = None,
    ) -> dict[str, Any]:
        """
        Run intake on a claim payload and return a sanitized context dictionary.

        Parameters
        ----------
        claim_id:
            Unique claim identifier from Maestro Case.
        raw_text:
            Claimant free-text description.
        photos_urls:
            Optional list of photo evidence URLs (count only in sanitized output).
        voice_note_url:
            Optional voice-note URL (presence flag only in sanitized output).

        Returns
        -------
        dict
            Sanitized intake context for the orchestration pipeline.
        """
        text = self._extract_claim_text(raw_text)
        extraction, source = await self._categorize_and_extract(text)

        return self._build_sanitized_context(
            claim_id=claim_id,
            extraction=extraction,
            source=source,
            photo_count=len(photos_urls or []),
            has_voice_note=bool(voice_note_url),
        )

    def _extract_claim_text(self, raw_text: str) -> str:
        """Normalize inbound claim narrative text."""
        normalized = raw_text.strip()
        if not normalized:
            raise ValueError("claim raw_text is empty")
        return normalized

    async def _categorize_and_extract(self, text: str) -> tuple[IntakeExtraction, str]:
        """Classify damage type and extract metadata via LLM or heuristic fallback."""
        settings = get_settings()
        if settings.openai_api_key:
            try:
                return await self._invoke_llm(text, api_key=settings.openai_api_key), "llm"
            except Exception:
                logger.exception("LLM intake failed; falling back to heuristic extraction")
        return self._heuristic_extract(text), "heuristic"

    async def _invoke_llm(self, text: str, *, api_key: str) -> IntakeExtraction:
        """Call a lightweight chat model with a structured JSON response."""
        payload = {
            "model": self._model,
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": _INTAKE_SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=LLM_TIMEOUT_SECONDS) as client:
            response = await client.post(
                OPENAI_CHAT_COMPLETIONS_URL,
                headers=headers,
                json=payload,
            )
            response.raise_for_status()

        body = response.json()
        content = body["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        return IntakeExtraction.model_validate(parsed)

    def _heuristic_extract(self, text: str) -> IntakeExtraction:
        """Rule-based fallback when no LLM API key is configured or LLM call fails."""
        lowered = text.lower()
        damage_type = MicroinsuranceDamageType.UNKNOWN

        keyword_map = {
            MicroinsuranceDamageType.WATER: ("water", "flood", "leak", "pipe", "mold"),
            MicroinsuranceDamageType.FIRE: ("fire", "smoke", "burn"),
            MicroinsuranceDamageType.THEFT: ("stolen", "theft", "burglary", "break-in"),
            MicroinsuranceDamageType.WIND: ("wind", "hail", "storm", "hurricane", "tornado"),
            MicroinsuranceDamageType.LIABILITY: ("liability", "injury", "slip", "fall"),
        }
        for category, keywords in keyword_map.items():
            if any(keyword in lowered for keyword in keywords):
                damage_type = category
                break

        loss_amount = None
        currency_match = _CURRENCY_PATTERN.search(text)
        if currency_match:
            amount_raw = currency_match.group("amount").replace(",", "")
            loss_amount = float(amount_raw)

        location = None
        location_match = re.search(
            r"\b(?:in|at|near)\s+(?P<location>[A-Za-z0-9 ,.'-]{3,60})",
            text,
            re.IGNORECASE,
        )
        if location_match:
            location = location_match.group("location").strip(" .,")

        summary = self._redact_sensitive_text(text)
        if len(summary) > 200:
            summary = f"{summary[:197]}..."

        return IntakeExtraction(
            damage_type=damage_type,
            confidence=0.55 if damage_type != MicroinsuranceDamageType.UNKNOWN else 0.25,
            loss_amount_usd=loss_amount,
            location=location,
            summary=summary,
        )

    def _build_sanitized_context(
        self,
        *,
        claim_id: str,
        extraction: IntakeExtraction,
        source: str,
        photo_count: int,
        has_voice_note: bool,
    ) -> dict[str, Any]:
        """Assemble the sanitized context dictionary returned to orchestration."""
        return {
            "claim_id": claim_id,
            "damage_type": extraction.damage_type.value,
            "damage_category_confidence": round(extraction.confidence, 2),
            "loss_amount_usd": extraction.loss_amount_usd,
            "location": self._redact_sensitive_text(extraction.location or ""),
            "summary": self._redact_sensitive_text(extraction.summary),
            "evidence": {
                "photo_count": photo_count,
                "has_voice_note": has_voice_note,
            },
            "intake_source": source,
        }

    def _redact_sensitive_text(self, value: str) -> str:
        """Remove common PII patterns from text fields in outbound context."""
        if not value:
            return ""
        redacted = _EMAIL_PATTERN.sub("[REDACTED_EMAIL]", value)
        redacted = _PHONE_PATTERN.sub("[REDACTED_PHONE]", redacted)
        redacted = _SSN_PATTERN.sub("[REDACTED_SSN]", redacted)
        redacted = _CARD_PATTERN.sub("[REDACTED_CARD]", redacted)
        return redacted.strip()
