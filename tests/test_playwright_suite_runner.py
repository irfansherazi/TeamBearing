"""
tests/test_playwright_suite_runner.py
======================================
Unit tests for the Playwright Parallel Headless Suite Runner.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from backend.main import app

@pytest.fixture
def client():
    """Return a TestClient for the FastAPI app."""
    with TestClient(app) as c:
        yield c


MOCK_SUITE_TESTS = [
    {
        "id": "qa-100-test",
        "file": "tests/qa-100-script-library.test.ts",
        "jira_keys": ["QA-100"],
        "description": "QA-100: Script Library",
        "steps_count": 4,
        "step_names": ["Step 1", "Step 2", "Step 3", "Step 4"]
    },
    {
        "id": "qa-101-test",
        "file": "tests/qa-101-client-merging.test.ts",
        "jira_keys": ["QA-101"],
        "description": "QA-101: Client Merging",
        "steps_count": 2,
        "step_names": ["Step 1", "Step 2"]
    }
]


@pytest.mark.asyncio
@patch("backend.api.playwright_routes._get_registry")
@patch("backend.api.playwright_routes._load_users")
@patch("asyncio.create_subprocess_exec")
async def test_run_all_success_and_report(mock_exec, mock_load_users, mock_get_registry, client):
    """Verify standard parallel run flow: start, state update, retrieve report."""
    # Reset active run
    from backend.storage.playwright_suite_runs import playwright_suite_run_store
    playwright_suite_run_store._clear_for_testing()

    mock_registry = MagicMock()
    mock_registry.list_tests.return_value = MOCK_SUITE_TESTS
    mock_get_registry.return_value = mock_registry

    mock_load_users.return_value = ["DemoSalesExec"]

    # Mock subprocess creation
    mock_proc = MagicMock()
    mock_proc.pid = 99999
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"Some stdout", b"Some stderr"))
    mock_exec.return_value = mock_proc

    payload = {
        "env": "test",
        "user": "DemoSalesExec",
        "browser": "chromium"
    }

    # Trigger run-all
    response = client.post("/api/playwright/run-all", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "suite_run_id" in data
    assert data["status"] == "running"
    assert "started_at" in data

    suite_run_id = data["suite_run_id"]

    # Allow background task to execute
    await asyncio.sleep(0.1)

    # Fetch report
    report_response = client.get(f"/api/playwright/run-all/{suite_run_id}/report")
    assert report_response.status_code == 200
    report_data = report_response.json()
    assert report_data["suite_run_id"] == suite_run_id
    assert report_data["status"] == "completed"
    assert report_data["total"] == 2
    assert report_data["passed"] == 2
    assert report_data["failed"] == 0
    assert report_data["outcome"] == "PASS"
    assert report_data["fail_reason"] is None
    assert len(report_data["results"]) == 2
    assert report_data["results"][0]["test_id"] in ["qa-100-test", "qa-101-test"]
    assert report_data["results"][0]["status"] == "PASS"

    # Assert subprocesses were executed with VQA_HEADLESS=1
    assert mock_exec.call_count == 2
    for call in mock_exec.call_args_list:
        args, kwargs = call
        assert kwargs["env"]["VQA_HEADLESS"] == "1"


@pytest.mark.asyncio
@patch("backend.api.playwright_routes._get_registry")
@patch("backend.api.playwright_routes._load_users")
@patch("asyncio.create_subprocess_exec")
async def test_run_all_concurrency_lock_429(mock_exec, mock_load_users, mock_get_registry, client):
    """Verify that a second request to run-all returns HTTP 429 while a run is active."""
    # Reset active run
    from backend.storage.playwright_suite_runs import playwright_suite_run_store
    playwright_suite_run_store._clear_for_testing()

    mock_registry = MagicMock()
    mock_registry.list_tests.return_value = MOCK_SUITE_TESTS
    mock_get_registry.return_value = mock_registry

    mock_load_users.return_value = ["DemoSalesExec"]

    # Block the subprocess wait/communicate to keep background run active
    mock_proc = MagicMock()
    mock_proc.pid = 88888
    # We want process.communicate() to await but never resolve immediately to simulate long-running process
    async def infinite_wait():
        await asyncio.sleep(0.5)
        return (b"stdout", b"stderr")
    mock_proc.communicate = infinite_wait
    mock_exec.return_value = mock_proc

    payload = {
        "env": "test",
        "user": "DemoSalesExec",
        "browser": "chromium"
    }

    # Trigger first run-all
    res1 = client.post("/api/playwright/run-all", json=payload)
    assert res1.status_code == 200
    assert playwright_suite_run_store.get_active_run_id() is not None

    # Trigger second run-all while first is active
    res2 = client.post("/api/playwright/run-all", json=payload)
    assert res2.status_code == 429
    assert res2.json()["detail"] == "Suite run already in progress"

    # Cleanup the pending task
    playwright_suite_run_store._clear_for_testing()


@pytest.mark.asyncio
@patch("backend.api.playwright_routes._get_registry")
@patch("backend.api.playwright_routes._load_users")
@patch("asyncio.create_subprocess_exec")
async def test_run_all_fails_and_parses_stderr(mock_exec, mock_load_users, mock_get_registry, client):
    """Verify that if a process fails, exit code != 0 and stderr is parsed."""
    # Reset active run
    from backend.storage.playwright_suite_runs import playwright_suite_run_store
    playwright_suite_run_store._clear_for_testing()

    mock_registry = MagicMock()
    mock_registry.list_tests.return_value = [MOCK_SUITE_TESTS[0]]
    mock_get_registry.return_value = mock_registry

    mock_load_users.return_value = ["DemoSalesExec"]

    mock_proc = MagicMock()
    mock_proc.pid = 11111
    mock_proc.returncode = 1
    mock_proc.communicate = AsyncMock(return_value=(b"", b"Error Line 1\nError Line 2\nError Line 3\nError Line 4\nError Line 5\nError Line 6"))
    mock_exec.return_value = mock_proc

    payload = {
        "env": "test",
        "user": "DemoSalesExec",
        "browser": "chromium"
    }

    # Trigger run-all
    response = client.post("/api/playwright/run-all", json=payload)
    assert response.status_code == 200
    suite_run_id = response.json()["suite_run_id"]

    await asyncio.sleep(0.1)

    # Fetch report
    report_response = client.get(f"/api/playwright/run-all/{suite_run_id}/report")
    assert report_response.status_code == 200
    report_data = report_response.json()
    assert report_data["status"] == "completed"
    assert report_data["passed"] == 0
    assert report_data["failed"] == 1
    assert report_data["outcome"] == "FAIL"
    assert "Failed tests: qa-100-test" in report_data["fail_reason"]
    assert len(report_data["results"]) == 1
    assert report_data["results"][0]["status"] == "FAIL"
    # Should contain the last 5 lines of stderr
    assert "Error Line 2\nError Line 3\nError Line 4\nError Line 5\nError Line 6" in report_data["results"][0]["error_snippet"]


@pytest.mark.asyncio
@patch("backend.api.playwright_routes._get_registry")
@patch("backend.api.playwright_routes._load_users")
@patch("asyncio.create_subprocess_exec")
async def test_run_all_timeout(mock_exec, mock_load_users, mock_get_registry, client):
    """Verify that if a test exceeds 360 seconds, it's terminated and set as FAIL."""
    # Reset active run
    from backend.storage.playwright_suite_runs import playwright_suite_run_store
    playwright_suite_run_store._clear_for_testing()

    mock_registry = MagicMock()
    mock_registry.list_tests.return_value = [MOCK_SUITE_TESTS[0]]
    mock_get_registry.return_value = mock_registry

    mock_load_users.return_value = ["DemoSalesExec"]

    # Force a timeout by mocking communicate to raise TimeoutError
    mock_proc = MagicMock()
    mock_proc.pid = 22222
    mock_proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError())
    mock_proc.terminate = MagicMock()
    mock_proc.wait = AsyncMock()
    mock_exec.return_value = mock_proc

    # Patch asyncio.wait_for to raise TimeoutError
    with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError()):
        payload = {
            "env": "test",
            "user": "DemoSalesExec",
            "browser": "chromium"
        }

        # Trigger run-all
        response = client.post("/api/playwright/run-all", json=payload)
        assert response.status_code == 200
        suite_run_id = response.json()["suite_run_id"]

        await asyncio.sleep(0.1)

        # Fetch report
        report_response = client.get(f"/api/playwright/run-all/{suite_run_id}/report")
        assert report_response.status_code == 200
        report_data = report_response.json()
        assert report_data["status"] == "completed"
        assert report_data["passed"] == 0
        assert report_data["failed"] == 1
        assert len(report_data["results"]) == 1
        assert report_data["results"][0]["status"] == "FAIL"
        assert report_data["results"][0]["error_snippet"] == "TimeoutError: Execution exceeded 360 seconds"
        assert mock_proc.terminate.called


def test_extract_playwright_error():
    """Verify that _extract_playwright_error robustly prioritises Playwright assertion errors from stdout."""
    from backend.api.playwright_routes import _extract_playwright_error

    # Case 1: Playwright assertion error in stdout, with npm warnings in stderr
    stdout_text = "Executing tests...\nError: expect(locator).toBeVisible()\n  at tests/qa-100.test.ts:15:10\n"
    stderr_text = "npm warn config init.author.email Use --init-author-email instead.\nnpm warn config init.license Use --init-license instead."
    error = _extract_playwright_error(stdout_text, stderr_text)
    assert "Error: expect(locator).toBeVisible()" in error
    assert "at tests/qa-100.test.ts" in error
    assert "npm warn" not in error

    # Case 2: Playwright index error line in stdout
    stdout_text = "1) [chromium] › tests/qa-100.test.ts:15:10 › Step 1\n  Locator timeout exceeded"
    stderr_text = "npm warn config init.author.email Use --init-author-email"
    error = _extract_playwright_error(stdout_text, stderr_text)
    assert "1) [chromium]" in error
    assert "Locator timeout exceeded" in error

    # Case 3: Fallback to last non-npm lines of stdout
    stdout_text = "Some random error line 1\nSome random error line 2\n"
    stderr_text = "npm warn config init.author.email"
    error = _extract_playwright_error(stdout_text, stderr_text)
    assert "Some random error line 2" in error

    # Case 4: Fallback to clean stderr if stdout is empty
    stdout_text = ""
    stderr_text = "npm warn config init.author.email\nActual compile error inside ts config"
    error = _extract_playwright_error(stdout_text, stderr_text)
    assert "Actual compile error inside ts" in error
    assert "npm warn" not in error


@pytest.mark.asyncio
@patch("backend.api.playwright_routes._get_registry")
@patch("backend.api.playwright_routes._load_users")
@patch("asyncio.create_subprocess_exec")
@patch("os.kill")
async def test_run_all_stop_process(mock_kill, mock_exec, mock_load_users, mock_get_registry, client):
    """Verify that stopping a suite run cleanly terminates subprocesses and updates reports."""
    from backend.api import playwright_routes
    from backend.storage.playwright_suite_runs import playwright_suite_run_store
    playwright_suite_run_store._clear_for_testing()
    playwright_routes._playwright_pids.clear()

    mock_registry = MagicMock()
    mock_registry.list_tests.return_value = MOCK_SUITE_TESTS
    mock_get_registry.return_value = mock_registry

    mock_load_users.return_value = ["DemoSalesExec"]

    # Block subprocess communicate to simulate long running tests
    mock_proc = MagicMock()
    mock_proc.pid = 77777
    async def slow_communicate():
        await asyncio.sleep(1.0)
        return (b"done", b"")
    mock_proc.communicate = slow_communicate
    mock_exec.return_value = mock_proc

    payload = {
        "env": "test",
        "user": "DemoSalesExec",
        "browser": "chromium"
    }

    # Trigger run-all
    response = client.post("/api/playwright/run-all", json=payload)
    assert response.status_code == 200
    suite_run_id = response.json()["suite_run_id"]

    assert playwright_suite_run_store.get_active_run_id() == suite_run_id

    # Give it a tiny bit to start the subprocesses
    await asyncio.sleep(0.05)

    # Verify we tracked PIDs
    assert len(playwright_routes._playwright_pids) > 0

    # Stop the suite run
    stop_response = client.post(f"/api/playwright/run-all/{suite_run_id}/stop")
    assert stop_response.status_code == 200
    stop_data = stop_response.json()

    assert stop_data["status"] == "failed"
    assert stop_data["outcome"] == "FAIL"
    assert stop_data["fail_reason"] == "Suite run stopped by user"
    assert len(stop_data["results"]) == 2
    for r in stop_data["results"]:
        assert r["status"] == "FAIL"
        assert r["error_snippet"] == "Suite run stopped by user."

    # Verify os.kill was called
    assert mock_kill.called
    mock_kill.assert_any_call(77777, 15)  # 15 is signal.SIGTERM

    # Lock is released
    assert playwright_suite_run_store.get_active_run_id() is None


def test_abort_stale_runs():
    """Verify that abort_stale_runs correctly finds and aborts runs with status 'running'."""
    from backend.storage.playwright_suite_runs import playwright_suite_run_store
    
    playwright_suite_run_store._clear_for_testing()
    
    # Create one running and one completed run
    playwright_suite_run_store.create_run("suite-running", {
        "suite_run_id": "suite-running",
        "status": "running",
        "total": 2,
        "passed": 0,
        "failed": 0,
        "results": [
            {"test_id": "t1", "status": "PENDING"},
            {"test_id": "t2", "status": "RUNNING"}
        ]
    })
    playwright_suite_run_store.create_run("suite-completed", {
        "suite_run_id": "suite-completed",
        "status": "completed",
        "total": 1,
        "passed": 1,
        "failed": 0,
        "results": [
            {"test_id": "t3", "status": "PASS"}
        ]
    })
    
    # Call abort
    playwright_suite_run_store.abort_stale_runs()
    
    # Assert running is now failed/aborted
    run1 = playwright_suite_run_store.get_run("suite-running")
    assert run1["status"] == "failed"
    assert run1["outcome"] == "FAIL"
    assert run1["fail_reason"] == "Suite run aborted on server restart / startup"
    assert run1["failed"] == 2
    assert run1["results"][0]["status"] == "FAIL"
    assert "aborted" in run1["results"][0]["error_snippet"]
    assert run1["results"][1]["status"] == "FAIL"
    assert "aborted" in run1["results"][1]["error_snippet"]
    
    # Assert completed was unchanged
    run2 = playwright_suite_run_store.get_run("suite-completed")
    assert run2["status"] == "completed"


@pytest.mark.asyncio
async def test_suite_report_failure_digest(client):
    """Verify that failure_digest is constructed at response-time for completed/failed runs and is None for running ones."""
    from backend.storage.playwright_suite_runs import playwright_suite_run_store
    playwright_suite_run_store._clear_for_testing()

    # Create a running suite run
    run_id = "suite-test-digest"
    playwright_suite_run_store.create_run(run_id, {
        "suite_run_id": run_id,
        "status": "running",
        "started_at": "2026-06-11T12:00:00Z",
        "total": 2,
        "passed": 0,
        "failed": 1,
        "results": [
            {
                "test_id": "qa-101-test",
                "name": "Verify Login Flow",
                "status": "FAIL",
                "duration_ms": 1500,
                "error_snippet": "\x1b[31m1) [chromium] › tests/login.spec.ts:10\x1b[0m\nError: expect(received).toBe(expected)\n\nReceived: 1\nExpected: 2\n  at tests/login.spec.ts:12"
            },
            {
                "test_id": "qa-102-test",
                "name": "Verify Dashboard",
                "status": "RUNNING",
                "duration_ms": 500,
            }
        ]
    })

    # 1. Fetch while status is "running" - failure_digest should be None
    response = client.get(f"/api/playwright/run-all/{run_id}/report")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "running"
    assert data["failure_digest"] is None

    # 2. Mark as completed and update in store
    run_data = playwright_suite_run_store.get_run(run_id)
    run_data["status"] = "completed"
    run_data["results"][1]["status"] = "PASS"
    playwright_suite_run_store.update_run(run_id, run_data)

    # Fetch report - failure_digest should now be populated and cleaned
    response = client.get(f"/api/playwright/run-all/{run_id}/report")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "completed"
    assert data["failure_digest"] is not None
    assert len(data["failure_digest"]) == 1
    
    digest_entry = data["failure_digest"][0]
    assert digest_entry["test_id"] == "qa-101-test"
    assert digest_entry["name"] == "Verify Login Flow"
    assert digest_entry["error_summary"] == "Error: expect(received).toBe(expected)"

    # 3. Verify ANSI stripping and long line truncation in helper
    from backend.api.playwright_routes import _clean_error_to_summary
    
    long_snippet = "Error: This is a very long assertion error message that will definitely exceed the limit of one hundred and twenty characters set in the requirements"
    summary = _clean_error_to_summary(long_snippet)
    assert len(summary) <= 120
    assert summary.endswith("...")
    assert "This is a very long" in summary

    # Verify no assertion line fallback
    snippet_no_assert = "1) [chromium] › tests/foo.spec.ts\nSome random custom error line\n  at node_modules/foo"
    summary_no_assert = _clean_error_to_summary(snippet_no_assert)
    assert summary_no_assert == "Some random custom error line"


@pytest.mark.asyncio
@patch("backend.api.playwright_routes._get_registry")
@patch("backend.api.playwright_routes._load_users")
@patch("asyncio.create_subprocess_exec")
async def test_suite_run_queued_tests_cancellation(mock_exec, mock_load_users, mock_get_registry, client):
    """Verify that queued tests waiting on the semaphore are cancelled/skipped if the run is stopped mid-way."""
    from backend.api import playwright_routes
    from backend.storage.playwright_suite_runs import playwright_suite_run_store
    
    playwright_suite_run_store._clear_for_testing()
    playwright_routes._playwright_pids.clear()

    mock_registry = MagicMock()
    mock_registry.list_tests.return_value = MOCK_SUITE_TESTS
    mock_get_registry.return_value = mock_registry

    mock_load_users.return_value = ["DemoSalesExec"]

    # Limit concurrency to 1 worker so the second test is queued
    with patch.dict("os.environ", {"VQA_SUITE_WORKERS": "1"}):
        # First test will slow down to block the single worker
        mock_proc = MagicMock()
        mock_proc.pid = 11111
        async def slow_communicate():
            await asyncio.sleep(0.5)
            return (b"done", b"")
        mock_proc.communicate = slow_communicate
        mock_exec.return_value = mock_proc

        payload = {
            "env": "test",
            "user": "DemoSalesExec",
            "browser": "chromium"
        }

        # Trigger run-all
        response = client.post("/api/playwright/run-all", json=payload)
        assert response.status_code == 200
        suite_run_id = response.json()["suite_run_id"]

        # Wait a small moment to let the first test start
        await asyncio.sleep(0.05)

        # Stop the suite run while the first test is running and second is queued
        stop_response = client.post(f"/api/playwright/run-all/{suite_run_id}/stop")
        assert stop_response.status_code == 200

        # Wait to let the first task finish and release the semaphore
        await asyncio.sleep(0.6)

        # Retrieve the report to verify both tests are failed/stopped, and the second test did NOT run
        report_response = client.get(f"/api/playwright/run-all/{suite_run_id}/report")
        report_data = report_response.json()
        assert report_data["status"] == "failed"
        assert report_data["fail_reason"] == "Suite run stopped by user"
        
        # Verify only 1 subprocess was ever executed (for the first test)
        assert mock_exec.call_count == 1


@pytest.mark.asyncio
@patch("backend.api.playwright_routes._get_registry")
@patch("backend.api.playwright_routes._load_users")
@patch("asyncio.create_subprocess_exec")
async def test_suite_run_heartbeat_inactivity_timeout(mock_exec, mock_load_users, mock_get_registry, client):
    """Verify that if the client stops polling, the heartbeat monitor automatically cancels the run."""
    from backend.api import playwright_routes
    from backend.storage.playwright_suite_runs import playwright_suite_run_store
    
    playwright_suite_run_store._clear_for_testing()
    playwright_routes._playwright_pids.clear()
    playwright_routes._suite_run_last_poll.clear()

    mock_registry = MagicMock()
    mock_registry.list_tests.return_value = MOCK_SUITE_TESTS
    mock_get_registry.return_value = mock_registry

    mock_load_users.return_value = ["DemoSalesExec"]

    # Mock subprocess to wait
    mock_proc = MagicMock()
    mock_proc.pid = 22222
    async def slow_communicate():
        await asyncio.sleep(1.0)
        return (b"done", b"")
    mock_proc.communicate = slow_communicate
    mock_exec.return_value = mock_proc

    mock_time_val = 1000.0
    def mock_time():
        return mock_time_val

    # Create a custom mock sleep that yields immediately but doesn't block infinitely
    orig_sleep = asyncio.sleep
    async def mock_sleep(delay, result=None):
        if delay == 2.0:
            await orig_sleep(0.001)
        else:
            await orig_sleep(delay, result)

    # Patch time.time and shorten the check loop sleep time to test heartbeat
    with patch("time.time", side_effect=mock_time), patch("asyncio.sleep", side_effect=mock_sleep):
        payload = {
            "env": "test",
            "user": "DemoSalesExec",
            "browser": "chromium"
        }

        # Trigger run-all
        response = client.post("/api/playwright/run-all", json=payload)
        assert response.status_code == 200
        suite_run_id = response.json()["suite_run_id"]

        # Simulating active polling (polled right after start)
        playwright_routes._suite_run_last_poll[suite_run_id] = 1000.0

        # Trigger heartbeat checks by ticking the time forward by 20 seconds (>15s timeout)
        mock_time_val = 1020.0

        # Run the event loop for a cycle to allow monitor_heartbeat to run
        await asyncio.sleep(0.05)

        # Retrieve the report - it should have been aborted due to inactivity
        report_data = playwright_suite_run_store.get_run(suite_run_id)
        assert report_data["status"] == "failed"
        assert report_data["fail_reason"] == "Suite run stopped by user"  # stop_suite_run marks it as this


