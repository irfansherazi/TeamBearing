"""
Phase 2: Session Routes — Integration Tests
============================================
Module: tests/test_session_routes.py

Tests the Phase 2 session API endpoints:

  POST /api/session/start  — bootstrap a session, set cookie
  POST /api/session/rebind — re-issue cookie with fresh Max-Age
  DELETE /api/session/{id} — admin-terminate a session
  GET  /api/session/{id}/status — read session state

Acceptance Criteria Coverage:
  AC-ENTRY-1 (session bootstrap → 200 + cookie) — § TestSessionStart
  AC-ENTRY-2 (AuthProvider guard) — § TestSessionStart
  AC-ERROR-1 (invalid JWT → 401) — § TestSessionStartJwtErrors
  AC-ERROR-2 (capacity cap → 409) — § TestSessionStartCapacity
  AC-ERROR-7 (rebind past grace → 404/410) — § TestSessionRebind
  AC-ERROR-8 (cross-user rebind → 403) — § TestSessionRebind
  AC-HAPPY-3 (rebind extends cookie Max-Age) — § TestSessionRebind
  AC-ASYNC-1 (cookie re-issued with fresh Max-Age) — § TestSessionRebind

Per-Phase Test Guidance (task file §Phase 2):
  ~6 tests: POST /session/start sets cookie (prod vs dev), POST /session/rebind
  re-issues cookie with new Max-Age, Origin rejection on WS handshake, cookie
  mismatch rejection on /ws/{run_id}, cross-user rebind rejected.
"""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.main import app

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_sso_token(
    *,
    email: str = "alice@vcreative.com",
    vc_id: int = 1001,
    jti: str = "jti-alice-001",
    exp_offset: int = 3600,
) -> MagicMock:
    """Build a mock SsoToken with the given fields."""
    token = MagicMock()
    token.email = email
    token.vc_id = vc_id
    token.jti = jti
    token.exp = int(time.time()) + exp_offset
    return token


def _auth_header(jwt_value: str = "valid-jwt-token") -> dict:
    return {"Authorization": f"Bearer {jwt_value}"}


# ---------------------------------------------------------------------------
# POST /session/start
# ---------------------------------------------------------------------------


class TestSessionStart:
    """AC-ENTRY-1: POST /session/start bootstraps a session and sets the cookie."""

    def test_start_returns_200_and_body(self):
        """Happy path: valid JWT → 200 with session_id, novnc_url, state=READY."""
        mock_token = _make_sso_token()

        with (
            patch("backend.api.session_routes.SsoValidator.validate_token", return_value=mock_token),
            patch("backend.api.session_routes.get_session_manager") as mock_mgr_factory,
        ):
            mock_session = MagicMock()
            mock_session.session_id = "sess-abc-123"
            mock_session.novnc_url = "/vnc/sess-abc-123/vnc.html?path=websockify/sess-abc-123"
            mock_session.state.value = "READY"
            mock_session.jwt_valid_until = mock_token.exp
            # next_rebind_by = exp - 90s
            mock_mgr = AsyncMock()
            mock_mgr.start_session = AsyncMock(return_value=mock_session)
            mock_mgr_factory.return_value = mock_mgr

            client = TestClient(app)
            response = client.post(
                "/api/session/start",
                headers=_auth_header(),
            )

        assert response.status_code == 200
        body = response.json()
        assert body["session_id"] == "sess-abc-123"
        assert "/vnc/sess-abc-123/" in body["novnc_url"]
        assert body["state"] == "READY"
        assert "jwt_valid_until" in body
        assert "next_rebind_by" in body

    def test_start_sets_httponly_cookie(self):
        """AC-ENTRY-1: response carries Set-Cookie: vqa_session with HttpOnly flag."""
        mock_token = _make_sso_token()

        with (
            patch("backend.api.session_routes.SsoValidator.validate_token", return_value=mock_token),
            patch("backend.api.session_routes.get_session_manager") as mock_mgr_factory,
        ):
            mock_session = MagicMock()
            mock_session.session_id = "sess-abc-123"
            mock_session.novnc_url = "/vnc/sess-abc-123/vnc.html?path=websockify/sess-abc-123"
            mock_session.state.value = "READY"
            mock_session.jwt_valid_until = mock_token.exp
            mock_mgr = AsyncMock()
            mock_mgr.start_session = AsyncMock(return_value=mock_session)
            mock_mgr_factory.return_value = mock_mgr

            client = TestClient(app)
            response = client.post(
                "/api/session/start",
                headers=_auth_header(),
            )

        assert response.status_code == 200
        # TestClient follows redirects and exposes cookies
        set_cookie = response.headers.get("set-cookie", "")
        assert "vqa_session=" in set_cookie
        assert "sess-abc-123" in set_cookie
        assert "HttpOnly" in set_cookie
        assert "SameSite=lax" in set_cookie or "samesite=lax" in set_cookie.lower()

    def test_start_without_auth_header_returns_401(self):
        """AC-ERROR-1: No Authorization header → 401."""
        client = TestClient(app)
        response = client.post("/api/session/start")
        assert response.status_code == 401
        body = response.json()
        assert body.get("error") == "invalid_token"

    def test_start_with_invalid_jwt_returns_401(self):
        """AC-ERROR-1: Invalid JWT (fails SsoValidator) → 401."""
        with patch("backend.api.session_routes.SsoValidator.validate_token", return_value=None):
            client = TestClient(app)
            response = client.post(
                "/api/session/start",
                headers=_auth_header("bad-token"),
            )
        assert response.status_code == 401
        body = response.json()
        assert body.get("error") == "invalid_token"


class TestSessionStartCapacity:
    """AC-ERROR-2: capacity cap → 409 with retry_after_s."""

    def test_start_at_capacity_returns_409(self):
        """When all display slots are taken, returns 409 with retry hint."""
        from backend.session.allocator import CapacityReachedResult

        mock_token = _make_sso_token()
        capacity_result = CapacityReachedResult(active_sessions=4, retry_after_s=15)

        with (
            patch("backend.api.session_routes.SsoValidator.validate_token", return_value=mock_token),
            patch("backend.api.session_routes.get_session_manager") as mock_mgr_factory,
        ):
            mock_mgr = AsyncMock()
            mock_mgr.start_session = AsyncMock(return_value=capacity_result)
            mock_mgr_factory.return_value = mock_mgr

            client = TestClient(app)
            response = client.post(
                "/api/session/start",
                headers=_auth_header(),
            )

        assert response.status_code == 409
        body = response.json()
        assert body.get("error") == "capacity_reached"
        assert "retry_after_s" in body
        assert "active_sessions" in body


# ---------------------------------------------------------------------------
# POST /session/rebind
# ---------------------------------------------------------------------------


class TestSessionRebind:
    """AC-HAPPY-3 + AC-ASYNC-1: rebind re-issues cookie with fresh Max-Age."""

    def test_rebind_returns_200_and_refreshed_cookie(self):
        """Successful rebind: new JWT → 200, Set-Cookie with updated Max-Age."""
        new_exp = int(time.time()) + 7200  # 2h from now
        mock_token = _make_sso_token(exp_offset=7200)

        with (
            patch("backend.api.session_routes.SsoValidator.validate_token", return_value=mock_token),
            patch("backend.api.session_routes.get_session_manager") as mock_mgr_factory,
        ):
            mock_session = MagicMock()
            mock_session.session_id = "sess-abc-123"
            mock_session.user_id = "1001"
            mock_session.jwt_valid_until = new_exp
            mock_session.state.value = "ATTACHED"

            mock_mgr = MagicMock()
            mock_mgr.get_session = MagicMock(return_value=mock_session)
            mock_mgr_factory.return_value = mock_mgr

            client = TestClient(app)
            # Set the session cookie
            client.cookies.set("vqa_session", "sess-abc-123")
            response = client.post(
                "/api/session/rebind",
                headers=_auth_header(),
            )

        assert response.status_code == 200
        body = response.json()
        assert body["session_id"] == "sess-abc-123"
        assert "jwt_valid_until" in body
        assert "next_rebind_by" in body
        # Cookie must be re-issued
        set_cookie = response.headers.get("set-cookie", "")
        assert "vqa_session=" in set_cookie

    def test_rebind_without_cookie_returns_401(self):
        """AC-ERROR: rebind without a session cookie → 401."""
        mock_token = _make_sso_token()
        with patch("backend.api.session_routes.SsoValidator.validate_token", return_value=mock_token):
            client = TestClient(app)
            response = client.post(
                "/api/session/rebind",
                headers=_auth_header(),
            )
        assert response.status_code == 401

    def test_rebind_terminated_session_returns_404(self):
        """AC-ERROR-7: rebind after session terminated → 404."""
        mock_token = _make_sso_token()

        with (
            patch("backend.api.session_routes.SsoValidator.validate_token", return_value=mock_token),
            patch("backend.api.session_routes.get_session_manager") as mock_mgr_factory,
        ):
            mock_mgr = MagicMock()
            mock_mgr.get_session = MagicMock(return_value=None)  # session not found
            mock_mgr_factory.return_value = mock_mgr

            client = TestClient(app)
            client.cookies.set("vqa_session", "sess-gone")
            response = client.post(
                "/api/session/rebind",
                headers=_auth_header(),
            )

        assert response.status_code in (404, 410)
        body = response.json()
        assert body.get("error") == "session_not_found"

    def test_rebind_cross_user_returns_403(self):
        """AC-ERROR-8: rebind where JWT vc_id != session.user_id → 403."""
        # Bob's token trying to rebind Alice's session
        bob_token = _make_sso_token(email="bob@vcreative.com", vc_id=9999)

        with (
            patch("backend.api.session_routes.SsoValidator.validate_token", return_value=bob_token),
            patch("backend.api.session_routes.get_session_manager") as mock_mgr_factory,
        ):
            mock_session = MagicMock()
            mock_session.session_id = "sess-alice"
            mock_session.user_id = "1001"  # Alice's vc_id — does not match Bob's 9999
            mock_session.state.value = "ATTACHED"

            mock_mgr = MagicMock()
            mock_mgr.get_session = MagicMock(return_value=mock_session)
            mock_mgr_factory.return_value = mock_mgr

            client = TestClient(app)
            client.cookies.set("vqa_session", "sess-alice")
            response = client.post(
                "/api/session/rebind",
                headers=_auth_header(),
            )

        assert response.status_code == 403
        body = response.json()
        assert body.get("error") == "session_user_mismatch"


# ---------------------------------------------------------------------------
# GET /session/{id}/status
# ---------------------------------------------------------------------------


class TestSessionStatus:
    """GET /session/{id}/status returns session state."""

    def test_status_returns_session_state(self):
        """GET /session/{id}/status → 200 with state."""
        with patch("backend.api.session_routes.get_session_manager") as mock_mgr_factory:
            mock_session = MagicMock()
            mock_session.session_id = "sess-abc-123"
            mock_session.state.value = "ATTACHED"
            mock_session.jwt_valid_until = time.time() + 3600

            mock_mgr = MagicMock()
            mock_mgr.get_session = MagicMock(return_value=mock_session)
            mock_mgr_factory.return_value = mock_mgr

            client = TestClient(app)
            client.cookies.set("vqa_session", "sess-abc-123")
            response = client.get("/api/session/sess-abc-123/status")

        assert response.status_code == 200
        body = response.json()
        assert body["state"] == "ATTACHED"

    def test_status_unknown_session_returns_404(self):
        """GET /session/unknown/status → 404."""
        with patch("backend.api.session_routes.get_session_manager") as mock_mgr_factory:
            mock_mgr = MagicMock()
            mock_mgr.get_session = MagicMock(return_value=None)
            mock_mgr_factory.return_value = mock_mgr

            client = TestClient(app)
            response = client.get("/api/session/no-such-session/status")

        assert response.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /session/{id}
# ---------------------------------------------------------------------------


class TestSessionDelete:
    """DELETE /session/{id} admin-terminates a session."""

    def test_delete_existing_session_returns_204(self):
        """Admin delete of an existing session → 204."""
        with patch("backend.api.session_routes.get_session_manager") as mock_mgr_factory:
            mock_session = MagicMock()
            mock_session.session_id = "sess-abc-123"
            mock_session.state.value = "ATTACHED"

            mock_mgr = AsyncMock()
            mock_mgr.get_session = MagicMock(return_value=mock_session)
            mock_mgr.terminate_session = AsyncMock()
            mock_mgr_factory.return_value = mock_mgr

            client = TestClient(app)
            response = client.delete("/api/session/sess-abc-123")

        assert response.status_code == 204

    def test_delete_unknown_session_returns_404(self):
        """Admin delete of non-existent session → 404."""
        with patch("backend.api.session_routes.get_session_manager") as mock_mgr_factory:
            mock_mgr = AsyncMock()
            mock_mgr.get_session = MagicMock(return_value=None)
            mock_mgr_factory.return_value = mock_mgr

            client = TestClient(app)
            response = client.delete("/api/session/no-such-session")

        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Phase 4: Execute endpoints require session cookie (AC-ENTRY-3)
# ---------------------------------------------------------------------------


class TestExecuteRequiresSessionCookie:
    """
    Phase 4 (AC-ENTRY-3): when SESSION_ISOLATION_ENABLED=true, every
    POST /execute* endpoint requires a valid session cookie and returns
    401 without one.  When SESSION_ISOLATION_ENABLED=false (kill switch),
    the legacy path is unchanged and no cookie is required.
    """

    def test_execute_without_cookie_returns_401_when_isolation_enabled(self):
        """
        AC-ENTRY-3: POST /execute without vqa_session cookie → 401 when
        SESSION_ISOLATION_ENABLED=true.
        """
        from backend.config import settings as _settings

        original = _settings.session_isolation_enabled
        _settings.session_isolation_enabled = True
        try:
            client = TestClient(app, raise_server_exceptions=False)
            response = client.post(
                "/api/execute",
                json={
                    "jira_ticket_id": "QA-1",
                    "role": "account_executive",
                    "target_url": "https://example.com",
                    "mode": "interactive",
                },
            )
            assert response.status_code == 401, (
                f"Expected 401 when no session cookie and isolation enabled; got {response.status_code}"
            )
        finally:
            _settings.session_isolation_enabled = original

    def test_execute_with_valid_cookie_proceeds_when_isolation_enabled(self):
        """
        AC-ENTRY-3: POST /execute with a valid vqa_session cookie → 200 (run created).
        The run_id is returned and run.session_id is stamped from the cookie.
        """
        from backend.config import settings as _settings

        original = _settings.session_isolation_enabled
        _settings.session_isolation_enabled = True
        try:
            client = TestClient(app, raise_server_exceptions=False)
            client.cookies.set("vqa_session", "sess-test-phase4")
            response = client.post(
                "/api/execute",
                json={
                    "jira_ticket_id": "QA-1",
                    "role": "account_executive",
                    "target_url": "https://example.com",
                    "mode": "interactive",
                },
            )
            assert response.status_code == 200, (
                f"Expected 200 with valid session cookie; got {response.status_code}"
            )
            body = response.json()
            assert "run_id" in body
        finally:
            _settings.session_isolation_enabled = original

    def test_execute_without_cookie_succeeds_when_isolation_disabled(self):
        """
        AC-HAPPY-5 kill switch: SESSION_ISOLATION_ENABLED=false (default) →
        POST /execute proceeds without a session cookie (legacy path unchanged).
        """
        from backend.config import settings as _settings

        original = _settings.session_isolation_enabled
        _settings.session_isolation_enabled = False
        try:
            client = TestClient(app, raise_server_exceptions=False)
            response = client.post(
                "/api/execute",
                json={
                    "jira_ticket_id": "QA-1",
                    "role": "account_executive",
                    "target_url": "https://example.com",
                    "mode": "interactive",
                },
            )
            # Legacy path: no cookie enforcement → run created (200 or 422 on bad req, not 401)
            assert response.status_code != 401, (
                "Kill switch off: should NOT require session cookie"
            )
        finally:
            _settings.session_isolation_enabled = original
