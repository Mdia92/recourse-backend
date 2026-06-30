"""UiPath Orchestrator Tasks API connector for Action Center human review."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from config.uipath_config import (
    UiPathAuthenticationError,
    UiPathConfig,
    authenticate,
    load_uipath_config,
)

logger = logging.getLogger("recourse.configuration.uipath_api")

# Official UiPath Orchestrator Generic Tasks endpoint (Action Center).
DEFAULT_TASK_CATALOG_NAME = "ClaimsExceptionReview"
DEFAULT_EXTERNAL_TAG = "RECOURSE"
API_TIMEOUT_SECONDS = 45.0

ORCHESTRATOR_SEGMENT = "orchestrator_"
CREATE_TASK_RELATIVE_PATH = "tasks/GenericTasks/CreateTask"


def _normalize_segment(segment: str) -> str:
    """Strip leading and trailing slashes from a single URL path segment."""
    return segment.strip().strip("/")


def _compose_create_task_url(
    *,
    maestro_base_url: str,
    organization_name: str,
    tenant_name: str,
) -> str:
    """
    Build the Orchestrator CreateTask URL without duplicate or missing slashes.

    Produces:
    ``{base}/{org}/{tenant}/orchestrator_/tasks/GenericTasks/CreateTask``
    """
    base = _normalize_segment(maestro_base_url)
    organization = _normalize_segment(organization_name)
    tenant = _normalize_segment(tenant_name)

    path_prefix = "/".join((base, organization, tenant, ORCHESTRATOR_SEGMENT))
    return f"{path_prefix}/{CREATE_TASK_RELATIVE_PATH}"


class UiPathOrchestratorError(Exception):
    """Raised when an Orchestrator Tasks API request fails."""


class UiPathOrchestratorClient:
    """
    Async connector that posts human-validation tasks to UiPath Orchestrator.

    Credentials are loaded via ``load_uipath_config`` and each request acquires a
    live bearer token through ``authenticate``.
    """

    def __init__(
        self,
        config: UiPathConfig | None = None,
        *,
        task_catalog_name: str = DEFAULT_TASK_CATALOG_NAME,
        organization_unit_id: str | None = None,
    ) -> None:
        self._config = config or load_uipath_config()
        self._task_catalog_name = task_catalog_name
        self._organization_unit_id = organization_unit_id

    def _resolve_organization_unit_id(
        self,
        override: str | None = None,
    ) -> str | None:
        """
        Resolve the Orchestrator folder ID from call override, client default,
        or ``UIPATH_ORGANIZATION_UNIT_ID`` in the loaded config.
        """
        for candidate in (
            override,
            self._organization_unit_id,
            self._config.organization_unit_id,
        ):
            if candidate is None:
                continue
            value = str(candidate).strip()
            if value != "":
                return value
        return None

    def build_create_task_endpoint(self, config: UiPathConfig | None = None) -> str:
        """
        Construct the Orchestrator CreateTask URL from loaded environment config.

        Pattern:
        ``{UIPATH_MAESTRO_BASE_URL}/{UIPATH_ORGANIZATION_NAME}/{UIPATH_TENANT_NAME}/orchestrator_/tasks/GenericTasks/CreateTask``
        """
        cfg = config or self._config
        return _compose_create_task_url(
            maestro_base_url=cfg.maestro_base_url,
            organization_name=cfg.organization_name,
            tenant_name=cfg.tenant_name,
        )

    async def create_human_validation_task(
        self,
        *,
        claim_id: str,
        fraud_findings: list[str],
        loss_summary: str,
        organization_unit_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Create a live Action Center review card for a human adjuster.

        Sends an authenticated POST to the official UiPath Orchestrator Tasks
        endpoint with a structured ``TaskMetadata`` block containing the claim
        identifier, fraud findings, and loss summary.

        Parameters
        ----------
        claim_id:
            Recourse / Maestro claim identifier.
        fraud_findings:
            Detective agent finding strings.
        loss_summary:
            Human-readable loss summary from intake.
        organization_unit_id:
            Optional Orchestrator folder ID (``X-UIPATH-OrganizationUnitId``).

        Returns
        -------
        dict
            API response plus the submitted task envelope.

        Raises
        ------
        UiPathOrchestratorError
            On authentication failure, network errors, or non-2xx Orchestrator responses.
        """
        folder_id = self._resolve_organization_unit_id(organization_unit_id)

        # Resolve the live Orchestrator Tasks endpoint from .env tenant settings.
        create_task_url = _compose_create_task_url(
            maestro_base_url=self._config.maestro_base_url,
            organization_name=self._config.organization_name,
            tenant_name=self._config.tenant_name,
        )

        task_metadata = self._build_task_metadata(
            claim_id=claim_id,
            fraud_findings=fraud_findings,
            loss_summary=loss_summary,
        )
        task_body = self._build_create_task_body(task_metadata)

        try:
            access_token = await authenticate(self._config)
        except UiPathAuthenticationError as exc:
            raise UiPathOrchestratorError("Unable to authenticate with UiPath Cloud.") from exc

        headers = self._build_headers(access_token, folder_id)
        logger.info(
            "UiPath Orchestrator request headers — X-UIPATH-OrganizationUnitId=%s",
            folder_id,
        )
        task_response = await self._post_create_task(create_task_url, headers, task_body)

        logger.info(
            "Action Center human-validation task created — claim_id=%s endpoint=%s",
            claim_id,
            create_task_url,
        )

        return {
            "claim_id": claim_id,
            "endpoint": create_task_url,
            "task_metadata": task_metadata,
            "task_request": task_body,
            "task_response": task_response,
        }

    def _build_task_metadata(
        self,
        *,
        claim_id: str,
        fraud_findings: list[str],
        loss_summary: str,
    ) -> dict[str, Any]:
        """Structured Task Metadata block rendered on the Action Center review card."""
        return {
            "claim_id": claim_id,
            "fraud_findings": fraud_findings,
            "fraud_finding_count": len(fraud_findings),
            "loss_summary": loss_summary,
            "review_type": "human_validation",
            "source": "recourse-judge",
        }

    def _build_create_task_body(self, task_metadata: dict[str, Any]) -> dict[str, Any]:
        """Wrap Task Metadata in the Orchestrator Generic Tasks CreateTask envelope."""
        claim_id = task_metadata["claim_id"]
        return {
            "type": "ExternalTask",
            "externalTag": DEFAULT_EXTERNAL_TAG,
            "title": f"Adjuster review required — claim {claim_id}",
            "priority": "High",
            "taskCatalogName": self._task_catalog_name,
            "data": {
                "TaskMetadata": task_metadata,
            },
        }

    def _build_headers(self, access_token: str, organization_unit_id: str | None) -> dict[str, str]:
        """Build authenticated Orchestrator request headers."""
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if organization_unit_id is not None:
            headers["X-UIPATH-OrganizationUnitId"] = organization_unit_id
            if organization_unit_id in {"0", "Shared"}:
                headers["X-UIPATH-FolderPath"] = "Shared"
        return headers

    async def _post_create_task(
        self,
        url: str,
        headers: dict[str, str],
        body: dict[str, Any],
    ) -> dict[str, Any]:
        """POST the CreateTask payload to UiPath Orchestrator."""
        logger.info("UiPath Orchestrator POST → resolved request URL: %s", url)

        try:
            async with httpx.AsyncClient(timeout=API_TIMEOUT_SECONDS) as client:
                response = await client.post(url, headers=headers, json=body)
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = self._extract_error_detail(exc)
            raise UiPathOrchestratorError(f"UiPath CreateTask failed ({detail}).") from exc
        except httpx.RequestError as exc:
            raise UiPathOrchestratorError(
                "UiPath CreateTask failed due to a network error."
            ) from exc

        if not response.content:
            return {"status": "accepted", "operation": "CreateTask"}

        try:
            parsed = response.json()
        except ValueError as exc:
            raise UiPathOrchestratorError("UiPath CreateTask returned non-JSON response.") from exc

        return parsed if isinstance(parsed, dict) else {"result": parsed}

    def _extract_error_detail(self, exc: httpx.HTTPStatusError) -> str:
        """Build a sanitized error string from an Orchestrator HTTP error."""
        status_code = exc.response.status_code
        try:
            error_body = exc.response.json()
            if isinstance(error_body, dict):
                message = error_body.get("message") or error_body.get("error", {}).get("message")
                if message:
                    return f"HTTP {status_code}: {message}"
        except ValueError:
            pass
        return f"HTTP {status_code}"
