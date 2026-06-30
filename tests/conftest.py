"""Shared pytest fixtures."""

import pytest
from fastapi.testclient import TestClient

from orchestration.app import app


@pytest.fixture
def client() -> TestClient:
    """HTTP client for integration tests."""
    return TestClient(app)


@pytest.fixture
def sample_case_payload() -> dict:
    """Representative UiPath Maestro Case webhook payload."""
    return {
        "caseId": "CASE-001",
        "blueprint": "maestro-case",
        "status": "open",
    }
