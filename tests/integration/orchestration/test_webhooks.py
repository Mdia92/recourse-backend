"""Integration tests for UiPath Maestro webhooks."""

from fastapi.testclient import TestClient


def test_health_endpoint(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_maestro_case_webhook(client: TestClient, sample_case_payload: dict) -> None:
    response = client.post("/webhooks/uipath/maestro/case", json=sample_case_payload)
    assert response.status_code == 200
    body = response.json()
    assert body["case_id"] == "CASE-001"
    assert "outcome" in body
