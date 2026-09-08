import json
from unittest.mock import AsyncMock, patch

import pytest

from backend.api.playwright_routes import (
    _clean_error_message,
    _parse_line_for_step_progress,
    _parse_playwright_json_report,
    _resolve_missing_steps,
)


def test_clean_error_message():
    raw_error = "\x1b[31mError: locator.click: Timeout 30000ms exceeded.\x1b[0m\n  at qa-170-search.test.ts:15:20"
    cleaned = _clean_error_message(raw_error)
    assert cleaned == "Error: locator.click: Timeout 30000ms exceeded.\n  at qa-170-search.test.ts:15:20"

@pytest.mark.asyncio
async def test_parse_line_for_step_progress():
    step_names = [
        "Data Prep: Force archive a spot",
        "Perform Initial Global Search",
        "Verify Retention and Refine Search"
    ]
    current_statuses = [
        {"index": i, "text": name, "status": "pending", "error": "", "human_selector": ""}
        for i, name in enumerate(step_names)
    ]

    with patch("backend.api.routes._broadcast_ac_progress", new_callable=AsyncMock) as mock_broadcast:
        # Step 1 in progress
        await _parse_line_for_step_progress(
            "run-123",
            "  [chromium] › ... › Data Prep: Force archive a spot",
            step_names,
            current_statuses
        )
        assert current_statuses[0]["status"] == "in_progress"
        assert mock_broadcast.called

        # Step 1 passed
        await _parse_line_for_step_progress(
            "run-123",
            "  ✓  Data Prep: Force archive a spot (2.5s)",
            step_names,
            current_statuses
        )
        assert current_statuses[0]["status"] == "passed"

        # Step 2 failed
        await _parse_line_for_step_progress(
            "run-123",
            "  ✕  Perform Initial Global Search (1.2s)",
            step_names,
            current_statuses
        )
        assert current_statuses[1]["status"] == "failed"

@pytest.mark.asyncio
async def test_resolve_missing_steps():
    current_statuses = [
        {"index": 0, "status": "passed"},
        {"index": 1, "status": "failed"},
        {"index": 2, "status": "pending"},
        {"index": 3, "status": "in_progress"}
    ]
    with patch("backend.api.routes._broadcast_ac_progress", new_callable=AsyncMock) as mock_broadcast:
        await _resolve_missing_steps("run-123", current_statuses)
        assert current_statuses[2]["status"] == "skipped"
        assert current_statuses[3]["status"] == "skipped"
        assert mock_broadcast.called

@pytest.mark.asyncio
async def test_parse_playwright_json_report(tmp_path):
    report_file = tmp_path / "results.json"

    # Mock Playwright JSON report structure
    report_data = {
        "suites": [
            {
                "specs": [
                    {
                        "tests": [
                            {
                                "results": [
                                    {
                                        "status": "failed",
                                        "steps": [
                                            {
                                                "title": "Data Prep: Force archive a spot",
                                                "category": "test.step",
                                                "status": "passed",
                                                "steps": []
                                            },
                                            {
                                                "title": "Perform Initial Global Search",
                                                "category": "test.step",
                                                "status": "failed",
                                                "error": {
                                                    "message": "\x1b[31mError: locator.click: Timeout 5000ms exceeded.\x1b[0m"
                                                },
                                                "steps": []
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ]
    }

    with open(report_file, "w") as f:
        json.dump(report_data, f)

    step_names = [
        "Data Prep: Force archive a spot",
        "Perform Initial Global Search",
        "Verify Retention and Refine Search"
    ]
    current_statuses = [
        {"index": i, "text": name, "status": "pending", "error": "", "human_selector": ""}
        for i, name in enumerate(step_names)
    ]

    with patch("backend.api.routes._broadcast_ac_progress", new_callable=AsyncMock) as mock_broadcast:
        await _parse_playwright_json_report(
            "run-123",
            report_file,
            step_names,
            current_statuses
        )

        assert current_statuses[0]["status"] == "passed"
        assert current_statuses[0]["error"] == ""

        assert current_statuses[1]["status"] == "failed"
        assert current_statuses[1]["error"] == "Error: locator.click: Timeout 5000ms exceeded."

        # Third step should be resolved to skipped since a previous one failed
        assert current_statuses[2]["status"] == "skipped"
        assert current_statuses[2]["error"] == ""

        assert mock_broadcast.called
        # Verify JSON report file was cleaned up (unlinked)
        assert not report_file.exists()


def test_get_and_head_run_report():
    from fastapi.testclient import TestClient

    from backend.api.routes import _run_states
    from backend.main import app

    # Seed _run_states with a fake run and report
    run_id = "test-run-head-123"
    _run_states[run_id] = {
        "state": {
            "final_html_report": "<html><body>Audit Report</body></html>"
        }
    }

    try:
        with TestClient(app) as client:
            # 1. Test original GET request
            get_response = client.get(f"/api/runs/{run_id}/report")
            assert get_response.status_code == 200
            assert get_response.headers["content-type"] == "text/html; charset=utf-8"
            assert get_response.text == "<html><body>Audit Report</body></html>"

            # 2. Test original HEAD request
            head_response = client.head(f"/api/runs/{run_id}/report")
            assert head_response.status_code == 200
            assert head_response.headers["content-type"] == "text/html; charset=utf-8"
            # HEAD responses must have empty body
            assert head_response.text == ""

            # 3. Test fallback GET request
            get_fallback = client.get(f"/api/report/{run_id}")
            assert get_fallback.status_code == 200
            assert get_fallback.headers["content-type"] == "text/html; charset=utf-8"
            assert get_fallback.text == "<html><body>Audit Report</body></html>"

            # 4. Test fallback HEAD request
            head_fallback = client.head(f"/api/report/{run_id}")
            assert head_fallback.status_code == 200
            assert head_fallback.headers["content-type"] == "text/html; charset=utf-8"
            # HEAD responses must have empty body
            assert head_fallback.text == ""

            # 5. Test non-existent run (404) for both paths
            get_404 = client.get("/api/runs/nonexistent-run/report")
            assert get_404.status_code == 404

            head_404 = client.head("/api/runs/nonexistent-run/report")
            assert head_404.status_code == 404

            get_fallback_404 = client.get("/api/report/nonexistent-run")
            assert get_fallback_404.status_code == 404

            head_fallback_404 = client.head("/api/report/nonexistent-run")
            assert head_fallback_404.status_code == 404
    finally:
        # Clean up seeded state
        _run_states._store.pop(run_id, None)
