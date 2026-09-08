"""
tests/test_playwright_healing.py
=================================
Unit tests for the Playwright AI test healing prompt generator endpoint.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.api import playwright_routes
from backend.storage.playwright_suite_runs import playwright_suite_run_store


@pytest.fixture
def client():
    """Return a TestClient for the FastAPI app."""
    with TestClient(app) as c:
        yield c


MOCK_HEALING_TESTS = [
    {
        "id": "qa-200-test",
        "file": "tests/qa-200-pass.test.ts",
        "jira_keys": ["QA-200"],
        "description": "QA-200: Passing test",
    },
    {
        "id": "qa-201-test",
        "file": "tests/qa-201-fail.test.ts",
        "jira_keys": ["QA-201"],
        "description": "QA-201: Failing test",
    }
]


def test_heal_prompt_missing_run(client):
    """Verify endpoint returns 404 for unknown run ID."""
    playwright_suite_run_store._clear_for_testing()
    response = client.post("/api/playwright/heal-prompt", json={"run_id": "suite-missing"})
    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


def test_heal_prompt_still_running(client):
    """Verify endpoint returns 400 when suite run is still active."""
    playwright_suite_run_store._clear_for_testing()
    playwright_suite_run_store.create_run("suite-running-1", {
        "status": "running",
        "results": []
    })
    response = client.post("/api/playwright/heal-prompt", json={"run_id": "suite-running-1"})
    assert response.status_code == 400
    assert "still in progress" in response.json()["detail"]


def test_heal_prompt_zero_failures(client):
    """Verify endpoint returns 400 when suite has zero failed tests."""
    playwright_suite_run_store._clear_for_testing()
    playwright_suite_run_store.create_run("suite-success-1", {
        "status": "completed",
        "results": [
            {
                "test_id": "qa-200-test",
                "name": "QA-200: Passing test",
                "status": "PASS",
                "duration_ms": 1200,
                "error_snippet": None
            }
        ]
    })
    response = client.post("/api/playwright/heal-prompt", json={"run_id": "suite-success-1"})
    assert response.status_code == 400
    assert "has no failed tests to heal" in response.json()["detail"]


@patch("backend.api.playwright_routes._get_registry")
@patch("pathlib.Path.is_file")
@patch("pathlib.Path.exists")
@patch("builtins.open")
def test_heal_prompt_success_and_scrubbing(mock_open, mock_exists, mock_is_file, mock_get_registry, client):
    """Verify successful prompt compilation, file reading, and secret scrubbing."""
    # Reset suite_runs
    playwright_suite_run_store._clear_for_testing()
    playwright_suite_run_store.create_run("suite-failed-1", {
        "status": "failed",
        "results": [
            {
                "test_id": "qa-201-test",
                "name": "QA-201: Failing test",
                "status": "FAIL",
                "duration_ms": 1500,
                "error_snippet": "AssertionError: Expected password 'SUPER_SECRET_123' to match"
            }
        ]
    })

    mock_registry = MagicMock()
    mock_registry.get_test.side_effect = lambda test_id: (
        MOCK_HEALING_TESTS[1] if test_id == "qa-201-test" else None
    )
    mock_get_registry.return_value = mock_registry

    # Mock file reading
    mock_exists.return_value = True
    mock_is_file.return_value = True
    mock_file = MagicMock()
    # Source code containing a secret assignment to prove scrubbing
    mock_file.read.return_value = (
        "import { test } from '@playwright/test';\n"
        "test('QA-201 test', async ({ page }) => {\n"
        "  const ADMIN_PASSWORD = 'ADMIN_PASS_SECRET';\n"
        "  await page.fill('#pass', ADMIN_PASSWORD);\n"
        "});"
    )
    mock_open.return_value.__enter__.return_value = mock_file

    response = client.post("/api/playwright/heal-prompt", json={"run_id": "suite-failed-1"})
    assert response.status_code == 200
    data = response.json()
    assert "prompt" in data
    prompt = data["prompt"]

    # Verify context inclusion
    assert "Playwright Test Healing Request" in prompt
    assert "QA-201: Failing test" in prompt
    assert "AssertionError" in prompt

    # Verify secret scrubbing on both file contents and assertion errors
    assert "ADMIN_PASS_SECRET" not in prompt
    assert "SUPER_SECRET_123" not in prompt
    assert "[REDACTED]" in prompt


def test_truncate_test_source_code():
    """Verify Head/Tail truncation logic is applied for files exceeding 300 lines."""
    from backend.api.playwright_routes import _extract_test_source_code

    # Create dummy source code of 350 lines
    lines = [f"// line {i}" for i in range(1, 351)]
    dummy_source = "\n".join(lines)

    with patch("pathlib.Path.is_file") as mock_is_file, \
         patch("pathlib.Path.exists") as mock_exists, \
         patch("builtins.open") as mock_open:
        mock_exists.return_value = True
        mock_is_file.return_value = True
        mock_file = MagicMock()
        mock_file.read.return_value = dummy_source
        mock_open.return_value.__enter__.return_value = mock_file

        result = _extract_test_source_code("tests/dummy.test.ts")
        result_lines = result.splitlines()

        # Check truncation occurred
        assert len(result_lines) < 350
        assert "// ... [TRUNCATED FOR BREVITY - middle section omitted to respect token limits] ..." in result_lines
        # Check first 100 lines are preserved
        assert result_lines[0] == "// line 1"
        assert result_lines[99] == "// line 100"
        # Check last 150 lines are preserved at the end
        assert result_lines[-1] == "// line 350"
        assert result_lines[-150] == "// line 201"
