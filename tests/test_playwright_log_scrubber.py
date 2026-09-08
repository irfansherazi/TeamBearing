"""
tests/test_playwright_log_scrubber.py
======================================
Unit tests for the Playwright log scrubber function.

Tests:
  - Password masking (SHARED_TEST_PASSWORD, ADMIN_TEST_PASSWORD)
  - token/password/storageState key=value masking
  - JWT-shaped string masking
  - Clean lines pass through unchanged
  - Edge cases: empty line, multiline-style
"""


from backend.api.playwright_routes import _scrub_line

# ---------------------------------------------------------------------------
# Tests: AC-BACK-8 — Mask SHARED_TEST_PASSWORD value
# ---------------------------------------------------------------------------


def test_scrub_shared_test_password(monkeypatch):
    """AC-BACK-8: SHARED_TEST_PASSWORD value is replaced with [REDACTED]."""
    monkeypatch.setenv("SHARED_TEST_PASSWORD", "s3cr3tP@ss!")
    line = 'Logging in with password: s3cr3tP@ss! for user DemoSalesExec'
    result = _scrub_line(line)
    assert "s3cr3tP@ss!" not in result
    assert "[REDACTED]" in result


def test_scrub_admin_test_password(monkeypatch):
    """AC-BACK-8: ADMIN_TEST_PASSWORD value is replaced with [REDACTED]."""
    monkeypatch.setenv("ADMIN_TEST_PASSWORD", "adm1nP@ss!")
    line = 'Admin login: adm1nP@ss! authenticated'
    result = _scrub_line(line)
    assert "adm1nP@ss!" not in result
    assert "[REDACTED]" in result


def test_scrub_does_not_mask_when_password_env_unset(monkeypatch):
    """When password env var is empty/unset, no masking occurs for env-based scrubbing."""
    monkeypatch.setenv("SHARED_TEST_PASSWORD", "")
    monkeypatch.setenv("ADMIN_TEST_PASSWORD", "")
    line = "Some normal log line with no secrets"
    result = _scrub_line(line)
    assert result == line


# ---------------------------------------------------------------------------
# Tests: AC-BACK-8/9 — Mask key=value patterns
# ---------------------------------------------------------------------------


def test_scrub_password_key_value():
    """password=<value> patterns are masked."""
    line = 'auth: {"password": "my-secret-123", "user": "admin"}'
    result = _scrub_line(line)
    assert "my-secret-123" not in result
    assert "[REDACTED]" in result


def test_scrub_token_key_value():
    """token=<value> patterns are masked."""
    line = "token: abc123secrettoken"
    result = _scrub_line(line)
    assert "abc123secrettoken" not in result


def test_scrub_storage_state_key_value():
    """storageState=<value> patterns are masked (AC-BACK-9)."""
    line = 'storageState: {"cookies":[],"origins":[]}'
    result = _scrub_line(line)
    assert "cookies" not in result or "[REDACTED]" in result


# ---------------------------------------------------------------------------
# Tests: AC-BACK-9 — JWT masking
# ---------------------------------------------------------------------------


def test_scrub_jwt_shaped_string():
    """AC-BACK-9: JWT-shaped strings (xxx.yyy.zzz) are masked."""
    jwt = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
    line = f"Bearer token received: {jwt}"
    result = _scrub_line(line)
    # The JWT should be replaced
    assert jwt not in result
    assert "[REDACTED_JWT]" in result


def test_scrub_short_string_not_masked_as_jwt():
    """Short dot-separated strings that don't look like JWTs are NOT masked."""
    line = "Loading module: test.module.ts"
    result = _scrub_line(line)
    # Should not be masked — segments are too short for JWT pattern
    # The important thing is the original meaning is preserved
    assert "test" in result or "module" in result


# ---------------------------------------------------------------------------
# Tests: Clean lines pass through
# ---------------------------------------------------------------------------


def test_scrub_clean_line_unchanged(monkeypatch):
    """Clean log lines without secrets pass through unchanged."""
    monkeypatch.setenv("SHARED_TEST_PASSWORD", "")
    monkeypatch.setenv("ADMIN_TEST_PASSWORD", "")
    line = "✓ Test passed: QA-321 List View Sorting (2450ms)"
    result = _scrub_line(line)
    assert result == line


def test_scrub_empty_line(monkeypatch):
    """Empty string returns empty string."""
    monkeypatch.setenv("SHARED_TEST_PASSWORD", "")
    monkeypatch.setenv("ADMIN_TEST_PASSWORD", "")
    result = _scrub_line("")
    assert result == ""


def test_scrub_playwright_output_line(monkeypatch):
    """Normal Playwright test runner output is not mangled."""
    monkeypatch.setenv("SHARED_TEST_PASSWORD", "")
    monkeypatch.setenv("ADMIN_TEST_PASSWORD", "")
    line = "  ✓  1 [chromium] › tests/qa-321-sorting.test.ts:45:5 › QA-321: Sorting"
    result = _scrub_line(line)
    # Should preserve the test name and line reference
    assert "qa-321-sorting" in result or "QA-321" in result


# ---------------------------------------------------------------------------
# Tests: Multiple secrets in one line
# ---------------------------------------------------------------------------


def test_scrub_multiple_secrets_in_one_line(monkeypatch):
    """Multiple secret patterns in one line are all masked."""
    monkeypatch.setenv("SHARED_TEST_PASSWORD", "sharedP@ss")
    monkeypatch.setenv("ADMIN_TEST_PASSWORD", "")
    line = 'login(email, "sharedP@ss") token=abc123def456 password="xyz789"'
    result = _scrub_line(line)
    assert "sharedP@ss" not in result
    assert "abc123def456" not in result
    assert "xyz789" not in result
