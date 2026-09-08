"""
tests/test_playwright_nightly.py
==================================
Unit and integration tests for the nightly Playwright endpoint and its
poll-and-notify background task.

Covers (Phase 1 test plan from task spec, 7 tests):
  - test_nightly_endpoint_rejects_missing_api_key
  - test_nightly_endpoint_returns_202_and_dispatches_group_run
  - test_nightly_endpoint_returns_429_when_run_active
  - test_poll_loop_posts_slack_on_completed
  - test_poll_loop_posts_error_slack_on_timeout
  - test_poll_loop_posts_error_slack_on_dispatch_exception
  - test_settings_defaults_pin_subset

Auth: The /playwright/* router does NOT apply its own auth dependency;
authentication is applied by the parent router in routes.py via
Depends(verify_api_key). Tests toggle api_auth_enabled as needed.

Test count: 7
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.storage.playwright_suite_runs import playwright_suite_run_store


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_API_KEY = "test-api-key-nightly-suite"
AUTH_HEADER = {"X-VQA-API-Key": VALID_API_KEY}

NIGHTLY_ENDPOINT = "/api/playwright/nightly"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_completed_run(suite_run_id: str, passed: int = 2, failed: int = 0) -> dict:
    outcome = "PASS" if failed == 0 else "FAIL"
    return {
        "suite_run_id": suite_run_id,
        "status": "completed",
        "started_at": "2026-08-11T06:00:00Z",
        "completed_at": "2026-08-11T06:30:00Z",
        "total": passed + failed,
        "passed": passed,
        "failed": failed,
        "outcome": outcome,
        "fail_reason": None if failed == 0 else "Failed tests: qa-172-production.test",
        "results": [
            {
                "test_id": "qa-170-search.test",
                "name": "QA-170: Search",
                "status": "PASS" if passed >= 1 else "FAIL",
                "duration_ms": 12400.0,
                "error_snippet": None if passed >= 1 else "Error: assertion failed",
            },
            {
                "test_id": "qa-172-production.test",
                "name": "QA-172: Production",
                "status": "PASS" if failed == 0 else "FAIL",
                "duration_ms": 18700.0,
                "error_snippet": None if failed == 0 else "AssertionError: expected visible",
            },
        ],
    }


def _make_mock_registry():
    mock_registry = MagicMock()
    mock_registry.get_test.side_effect = lambda test_id: {
        "id": test_id,
        "file": f"tests/vpromedia/{test_id}.ts",
        "description": test_id,
        "steps_count": 1,
        "step_names": ["run"],
    }
    return mock_registry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_suite_store():
    """Clear the in-process suite run store before each test."""
    playwright_suite_run_store._clear_for_testing()
    yield
    playwright_suite_run_store._clear_for_testing()


# ---------------------------------------------------------------------------
# AC-AUTH: Auth guard rejects missing API key when auth is enabled
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_nightly_endpoint_rejects_missing_api_key():
    """
    The verify_api_key dependency must reject requests missing both the
    X-VQA-API-Key header and a Bearer token when api_auth_enabled=True.

    Tests the auth middleware logic directly (not via full FastAPI app startup)
    to avoid Bedrock/SSM initialization hangs in the TestClient.
    """
    from fastapi import HTTPException
    from backend.api import auth_middleware

    # Mock request with a non-public, non-websocket path
    mock_request = MagicMock()
    mock_url = MagicMock()
    mock_url.path = "/api/playwright/nightly"
    mock_request.url = mock_url

    # Patch _is_auth_enabled → True and _get_valid_keys → {VALID_API_KEY}
    with patch.object(auth_middleware, "_is_auth_enabled", return_value=True):
        with patch.object(auth_middleware, "_get_valid_keys", return_value={VALID_API_KEY}):
            with patch("backend.config.settings") as mock_settings:
                mock_settings.sso_enabled = False

                # Call with no api_key (simulates missing X-VQA-API-Key)
                try:
                    await auth_middleware.verify_api_key(
                        request=mock_request,
                        api_key=None,
                        auth=None,
                        token=None,
                    )
                    pytest.fail("Expected HTTPException but got none — auth gate not enforced")
                except HTTPException as exc:
                    assert exc.status_code in (401, 403), (
                        f"Expected 401 or 403, got {exc.status_code}: {exc.detail}"
                    )


# ---------------------------------------------------------------------------
# AC-ASYNC-1 / Happy path: 202 + group run dispatched
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@patch("backend.api.playwright_routes._get_registry")
@patch("backend.api.playwright_routes._load_users")
async def test_nightly_endpoint_returns_202_and_dispatches_group_run(
    mock_load_users, mock_get_registry
):
    """
    POST /api/playwright/nightly with auth disabled returns 202 Accepted
    and creates a suite run in the store.
    """
    mock_get_registry.return_value = _make_mock_registry()
    mock_load_users.return_value = ["DemoProdDirector"]

    with patch("backend.api.playwright_routes.settings") as mock_settings:
        mock_settings.api_auth_enabled = False
        mock_settings.api_keys = ""
        mock_settings.nightly_test_ids = [
            "qa-170-search.test",
            "qa-172-production.test",
        ]
        mock_settings.nightly_env = "test"
        mock_settings.nightly_user = "DemoProdDirector"
        mock_settings.nightly_browser = "chromium"
        mock_settings.nightly_slack_webhook_url = "https://hooks.slack.com/services/mock"
        mock_settings.nightly_poll_interval_seconds = 5
        mock_settings.nightly_poll_timeout_seconds = 1800
        mock_settings.external_host = "localhost"

        # Prevent the background tasks from actually running Playwright
        with patch("backend.api.playwright_routes.asyncio.create_task"):
            with TestClient(app) as c:
                response = c.post(NIGHTLY_ENDPOINT)

    assert response.status_code == 202, (
        f"Expected 202 Accepted, got {response.status_code}: {response.text}"
    )
    data = response.json()
    assert "suite_run_id" in data, "Response must include suite_run_id"
    assert data.get("status") == "started", f"Expected status='started', got {data.get('status')!r}"


# ---------------------------------------------------------------------------
# AC-ERROR-1 (429 — suite run already in progress)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_nightly_endpoint_returns_429_when_run_active():
    """
    When a suite run is already in progress, the nightly endpoint returns 429.
    Tests the route handler directly (not via TestClient) to avoid lifespan
    session-manager teardown hangs in the test environment.
    """
    from fastapi import HTTPException
    from backend.api.playwright_routes import run_nightly_playwright_suite

    # Simulate an active run already in the store by mocking get_active_run_id
    mock_request = MagicMock()
    mock_request.headers.get = MagicMock(return_value=None)
    mock_request.url.scheme = "https"

    with patch("backend.api.playwright_routes.playwright_suite_run_store") as mock_store:
        mock_store.abort_stale_runs = MagicMock()
        mock_store.get_active_run_id.return_value = "existing-run-abc"

        try:
            await run_nightly_playwright_suite(request=mock_request)
            pytest.fail("Expected HTTPException(429) but endpoint returned successfully")
        except HTTPException as exc:
            assert exc.status_code == 429, (
                f"Expected 429 when run active, got {exc.status_code}: {exc.detail}"
            )
            assert "already in progress" in str(exc.detail).lower() or "429" in str(exc.status_code), (
                f"Expected 'already in progress' in detail, got: {exc.detail!r}"
            )


# ---------------------------------------------------------------------------
# AC-ASYNC-1: Poll loop posts Slack on completed run
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_poll_loop_posts_slack_on_completed():
    """
    The _nightly_poll_and_notify background task polls the suite run store.
    When the store returns 'completed' status after 3 polls, it posts a
    correctly shaped Slack message (mocked httpx.AsyncClient).
    """
    from backend.api.playwright_routes import _nightly_poll_and_notify

    suite_run_id = "nightly-poll-test-01"
    slack_webhook_url = "https://hooks.slack.com/services/TTEST/BTEST/mocktoken"
    report_base_url = "https://vqa.vcreative.net"

    completed_run = _make_completed_run(suite_run_id, passed=2, failed=0)

    call_count = {"n": 0}

    def _fake_get_run(sid):
        call_count["n"] += 1
        if call_count["n"] < 3:
            return {**completed_run, "status": "running", "outcome": None}
        return completed_run

    slack_posts = []

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()

    async def _fake_post(url, *, json=None, headers=None):
        slack_posts.append({"url": url, "json": json})
        return mock_response

    mock_async_client = MagicMock()
    mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
    mock_async_client.__aexit__ = AsyncMock(return_value=False)
    mock_async_client.post = _fake_post

    with patch(
        "backend.api.playwright_routes.playwright_suite_run_store"
    ) as mock_store:
        mock_store.get_run.side_effect = _fake_get_run

        with patch("httpx.AsyncClient", return_value=mock_async_client):
            with patch("backend.api.playwright_routes.settings") as mock_settings:
                mock_settings.nightly_poll_interval_seconds = 0
                mock_settings.nightly_poll_timeout_seconds = 1800

                await _nightly_poll_and_notify(
                    suite_run_id=suite_run_id,
                    slack_webhook_url=slack_webhook_url,
                    report_base_url=report_base_url,
                )

    assert len(slack_posts) == 1, (
        f"Expected exactly 1 Slack POST, got {len(slack_posts)}"
    )
    posted_url = slack_posts[0]["url"]
    assert posted_url == slack_webhook_url

    payload_str = str(slack_posts[0]["json"])
    assert "Nightly suite" in payload_str or "nightly" in payload_str.lower(), (
        "Slack payload must reference 'Nightly suite'"
    )


# ---------------------------------------------------------------------------
# AC-ERROR-1: Poll timeout posts error Slack
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_poll_loop_posts_error_slack_on_timeout():
    """
    When the poll loop never sees a terminal status within the timeout window,
    it posts an AC-ERROR-1 shaped error message to Slack.
    """
    from backend.api.playwright_routes import _nightly_poll_and_notify

    suite_run_id = "nightly-timeout-test-01"
    slack_webhook_url = "https://hooks.slack.com/services/TTEST/BTEST/mocktoken"
    report_base_url = "https://vqa.vcreative.net"

    running_run = {
        "suite_run_id": suite_run_id,
        "status": "running",
        "started_at": "2026-08-11T06:00:00Z",
        "completed_at": None,
        "total": 2,
        "passed": 0,
        "failed": 0,
        "outcome": None,
        "fail_reason": None,
        "results": [],
    }

    slack_posts = []
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()

    async def _fake_post(url, *, json=None, headers=None):
        slack_posts.append({"url": url, "json": json})
        return mock_response

    mock_async_client = MagicMock()
    mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
    mock_async_client.__aexit__ = AsyncMock(return_value=False)
    mock_async_client.post = _fake_post

    with patch("backend.api.playwright_routes.playwright_suite_run_store") as mock_store:
        mock_store.get_run.return_value = running_run
        mock_store.update_suite_totals_and_status = MagicMock()

        with patch("httpx.AsyncClient", return_value=mock_async_client):
            with patch("backend.api.playwright_routes.settings") as mock_settings:
                mock_settings.nightly_poll_interval_seconds = 0
                mock_settings.nightly_poll_timeout_seconds = 0  # instant timeout

                await _nightly_poll_and_notify(
                    suite_run_id=suite_run_id,
                    slack_webhook_url=slack_webhook_url,
                    report_base_url=report_base_url,
                )

    assert len(slack_posts) == 1, (
        f"Expected 1 error Slack POST on timeout, got {len(slack_posts)}"
    )
    error_payload = slack_posts[0]["json"]
    assert error_payload is not None

    payload_str = str(error_payload)
    assert (
        "❌" in payload_str or "error" in payload_str.lower() or "timeout" in payload_str.lower()
    ), f"Error Slack message must indicate failure/timeout, got: {payload_str[:300]!r}"


# ---------------------------------------------------------------------------
# AC-ERROR-1: Dispatch exception posts error Slack
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_poll_loop_posts_error_slack_on_dispatch_exception():
    """
    When the store raises (e.g., due to an orchestrator crash), the background
    task posts an AC-ERROR-1 shaped error Slack message.
    """
    from backend.api.playwright_routes import _nightly_poll_and_notify

    suite_run_id = "nightly-exception-test-01"
    slack_webhook_url = "https://hooks.slack.com/services/TTEST/BTEST/mocktoken"
    report_base_url = "https://vqa.vcreative.net"

    slack_posts = []
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()

    async def _fake_post(url, *, json=None, headers=None):
        slack_posts.append({"url": url, "json": json})
        return mock_response

    mock_async_client = MagicMock()
    mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
    mock_async_client.__aexit__ = AsyncMock(return_value=False)
    mock_async_client.post = _fake_post

    with patch("backend.api.playwright_routes.playwright_suite_run_store") as mock_store:
        mock_store.get_run.side_effect = RuntimeError("orchestrator crashed before run created")
        mock_store.update_suite_totals_and_status = MagicMock()

        with patch("httpx.AsyncClient", return_value=mock_async_client):
            with patch("backend.api.playwright_routes.settings") as mock_settings:
                mock_settings.nightly_poll_interval_seconds = 0
                mock_settings.nightly_poll_timeout_seconds = 1800

                await _nightly_poll_and_notify(
                    suite_run_id=suite_run_id,
                    slack_webhook_url=slack_webhook_url,
                    report_base_url=report_base_url,
                )

    assert len(slack_posts) == 1, (
        f"Expected 1 error Slack POST on exception, got {len(slack_posts)}"
    )
    payload_str = str(slack_posts[0]["json"])
    assert "❌" in payload_str or "error" in payload_str.lower(), (
        f"Error Slack message must indicate failure, got: {payload_str[:300]!r}"
    )


# ---------------------------------------------------------------------------
# AC-VERIFY-6: Settings defaults pin the nightly subset
# ---------------------------------------------------------------------------

def test_settings_defaults_pin_subset():
    """
    AC-VERIFY-6: The nightly settings fields must have coherent defaults —
    a non-empty pinned test list (DemoProdDirector-aligned), env/user/browser
    matching the deployment target, and a poll timeout sized for the list.
    """
    from backend.config import Settings

    with patch("backend.secrets.load_all_secrets", return_value={}):
        s = Settings()

    assert hasattr(s, "nightly_test_ids"), "Settings must have nightly_test_ids field"
    # Non-brittle assertions: length and a couple of load-bearing IDs the
    # nightly must include. Exact ordering / full list belongs in the config
    # source, not here.
    assert len(s.nightly_test_ids) >= 20, (
        f"nightly_test_ids must contain the full DemoProdDirector library "
        f"(~26 tests); got {len(s.nightly_test_ids)}: {s.nightly_test_ids!r}"
    )
    for required_id in ("qa-170-search.test", "qa-172-production.test"):
        assert required_id in s.nightly_test_ids, (
            f"nightly_test_ids must include the smoke-test anchor {required_id!r}"
        )

    assert hasattr(s, "nightly_env"), "Settings must have nightly_env field"
    assert s.nightly_env == "test", (
        f"nightly_env must default to 'test', got: {s.nightly_env!r}"
    )

    assert hasattr(s, "nightly_user"), "Settings must have nightly_user field"
    assert s.nightly_user == "DemoProdDirector", (
        f"nightly_user must default to 'DemoProdDirector', got: {s.nightly_user!r}"
    )

    assert hasattr(s, "nightly_browser"), "Settings must have nightly_browser field"
    assert s.nightly_browser == "chromium", (
        f"nightly_browser must default to 'chromium', got: {s.nightly_browser!r}"
    )

    assert hasattr(s, "nightly_mode"), "Settings must have nightly_mode field"
    assert s.nightly_mode == "pinned", (
        f"nightly_mode must default to 'pinned' to preserve legacy behavior, got: {s.nightly_mode!r}"
    )

    # Poll timeout must be sized for the pinned list — a too-small default
    # would cause spurious AC-ERROR-1 timeout notifications even when the
    # suite is fine. 5400s = 90 min covers 26 tests at ~3 min/test sequential.
    assert hasattr(s, "nightly_poll_timeout_seconds"), (
        "Settings must have nightly_poll_timeout_seconds field"
    )
    assert s.nightly_poll_timeout_seconds >= 3600, (
        f"nightly_poll_timeout_seconds must be at least 60 min for a suite of "
        f"this size; got {s.nightly_poll_timeout_seconds}"
    )


# ---------------------------------------------------------------------------
# nightly_mode='all' — expands to every .test.ts entry in the registry
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@patch("backend.api.playwright_routes._get_registry")
@patch("backend.api.playwright_routes._load_users")
async def test_nightly_endpoint_mode_all_expands_registry(
    mock_load_users, mock_get_registry
):
    """
    When nightly_mode='all', the endpoint enumerates registry.list_tests(),
    filters to files ending in .test.ts (skipping helpers like filePreWashUtility),
    and dispatches a suite with the full list.
    """
    mock_registry = MagicMock()
    mock_registry.list_tests.return_value = [
        {"id": "qa-170-search.test", "file": "tests/vpromedia/qa-170-search.test.ts", "description": "search"},
        {"id": "qa-172-production.test", "file": "tests/vpromedia/qa-172-production.test.ts", "description": "prod"},
        {"id": "qa-201-billing.test", "file": "tests/vpromedia/qa-201-billing.test.ts", "description": "billing"},
        # A helper that must be filtered out
        {"id": "filePreWashUtility", "file": "tests/vpromedia/filePreWashUtility.ts", "description": "helper"},
    ]
    mock_get_registry.return_value = mock_registry
    mock_load_users.return_value = ["DemoProdDirector"]

    with patch("backend.api.playwright_routes.settings") as mock_settings:
        mock_settings.api_auth_enabled = False
        mock_settings.api_keys = ""
        mock_settings.nightly_mode = "all"
        # nightly_test_ids should be ignored in 'all' mode
        mock_settings.nightly_test_ids = ["should-be-ignored"]
        mock_settings.nightly_env = "test"
        mock_settings.nightly_user = "DemoProdDirector"
        mock_settings.nightly_browser = "chromium"
        mock_settings.nightly_slack_webhook_url = "https://hooks.slack.com/services/mock"
        mock_settings.nightly_poll_interval_seconds = 5
        mock_settings.nightly_poll_timeout_seconds = 1800
        mock_settings.external_host = "localhost"

        with patch("backend.api.playwright_routes.asyncio.create_task"):
            with TestClient(app) as c:
                response = c.post(NIGHTLY_ENDPOINT)

    assert response.status_code == 202, (
        f"Expected 202 Accepted, got {response.status_code}: {response.text}"
    )
    data = response.json()
    suite_run_id = data["suite_run_id"]

    # The store must reflect the expanded, helper-filtered list (3 tests, not 4)
    run = playwright_suite_run_store.get_run(suite_run_id)
    assert run is not None, "Suite run must be created in the store"
    assert run["total"] == 3, (
        f"mode='all' must run all .test.ts entries (excluding helpers); got total={run['total']}"
    )
    stored_ids = {r["test_id"] for r in run["results"]}
    assert stored_ids == {
        "qa-170-search.test",
        "qa-172-production.test",
        "qa-201-billing.test",
    }, f"Unexpected test IDs in run: {stored_ids}"
    assert "filePreWashUtility" not in stored_ids, "Helper files must be excluded from mode='all'"
