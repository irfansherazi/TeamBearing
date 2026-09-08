"""
tests/test_playwright_match_api.py
=======================================
Unit tests for the GET /playwright/match/{ticket_id} API endpoint.
"""

from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Return a TestClient for the FastAPI app."""
    from backend.main import app
    with TestClient(app) as c:
        yield c


MOCK_TESTS = [
    {
        "id": "qa-170-test",
        "file": "playwright/tests/qa-170-search.test.ts",
        "jira_keys": ["QA-170"],
        "description": "QA-170 Search Test",
        "steps_count": 3,
        "step_names": ["Login", "Search", "Assert"],
    },
    {
        "id": "qa-196-test-1",
        "file": "playwright/tests/qa-196-order-1.test.ts",
        "jira_keys": ["QA-196"],
        "description": "QA-196 Order Test 1",
        "steps_count": 2,
        "step_names": ["Step 1", "Step 2"],
    },
    {
        "id": "qa-196-test-2",
        "file": "playwright/tests/qa-196-order-2.test.ts",
        "jira_keys": ["QA-196"],
        "description": "QA-196 Order Test 2",
        "steps_count": 4,
        "step_names": ["Step 1", "Step 2", "Step 3", "Step 4"],
    }
]


@patch("backend.api.playwright_routes._get_registry")
def test_match_endpoint_found(mock_get_registry, client):
    """Verify that a matching ticket returns matched=True with correct test details."""
    mock_registry = MagicMock()
    mock_registry.get_tests_by_jira_key.return_value = [MOCK_TESTS[0]]
    mock_get_registry.return_value = mock_registry

    response = client.get("/api/playwright/match/QA-170")
    assert response.status_code == 200
    data = response.json()
    assert data["matched"] is True
    assert len(data["tests"]) == 1
    assert data["tests"][0]["id"] == "qa-170-test"
    assert data["tests"][0]["steps_count"] == 3
    assert data["tests"][0]["step_names"] == ["Login", "Search", "Assert"]

    mock_registry.get_tests_by_jira_key.assert_called_once_with("QA-170")


@patch("backend.api.playwright_routes._get_registry")
def test_match_endpoint_not_found(mock_get_registry, client):
    """Verify that a non-matching ticket returns matched=False and empty tests."""
    mock_registry = MagicMock()
    mock_registry.get_tests_by_jira_key.return_value = []
    mock_get_registry.return_value = mock_registry

    response = client.get("/api/playwright/match/FAKE-999")
    assert response.status_code == 200
    data = response.json()
    assert data["matched"] is False
    assert data["tests"] == []

    mock_registry.get_tests_by_jira_key.assert_called_once_with("FAKE-999")


@patch("backend.api.playwright_routes._get_registry")
def test_match_endpoint_case_insensitive(mock_get_registry, client):
    """Verify that lowercase ticket queries work correctly on the API layer."""
    mock_registry = MagicMock()
    mock_registry.get_tests_by_jira_key.return_value = [MOCK_TESTS[0]]
    mock_get_registry.return_value = mock_registry

    response = client.get("/api/playwright/match/qa-170")
    assert response.status_code == 200
    data = response.json()
    assert data["matched"] is True
    assert len(data["tests"]) == 1
    assert data["tests"][0]["id"] == "qa-170-test"

    mock_registry.get_tests_by_jira_key.assert_called_once_with("qa-170")


@patch("backend.api.playwright_routes._get_registry")
def test_match_endpoint_multi_match(mock_get_registry, client):
    """Verify that a ticket with multiple matched tests returns matched=True and all test details."""
    mock_registry = MagicMock()
    mock_registry.get_tests_by_jira_key.return_value = MOCK_TESTS[1:]
    mock_get_registry.return_value = mock_registry

    response = client.get("/api/playwright/match/QA-196")
    assert response.status_code == 200
    data = response.json()
    assert data["matched"] is True
    assert len(data["tests"]) == 2
    assert {t["id"] for t in data["tests"]} == {"qa-196-test-1", "qa-196-test-2"}

    mock_registry.get_tests_by_jira_key.assert_called_once_with("QA-196")
