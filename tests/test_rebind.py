"""
Phase 2: Session Rebind — Integration Tests
============================================
Module: tests/test_rebind.py

Deep tests for the rebind flow covering cookie Max-Age freshness,
cross-user rejection, past-grace termination, and session state updates.

Acceptance Criteria Coverage:
  AC-HAPPY-3 (rebind extends session without disruption) — § TestRebindCookieMaxAge
  AC-ASYNC-1 (cookie re-issued with fresh Max-Age) — § TestRebindCookieMaxAge
  AC-ERROR-7 (rebind past grace → 404/410) — § TestRebindTerminatedSession
  AC-ERROR-8 (cross-user rebind → 403) — § TestRebindCrossUser

Per-Phase Test Guidance (task file §Phase 2):
  Rebind extends cookie Max-Age (verified via Set-Cookie header inspection),
  rebind past grace fails, rebind cross-user rejected.
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
    jti: str = "jti-rebind-001",
    exp_offset: int = 3600,
) -> MagicMock:
    token = MagicMock()
    token.email = email
    token.vc_id = vc_id
    token.jti = jti
    token.exp = int(time.time()) + exp_offset
    return token


# ---------------------------------------------------------------------------
# Cookie Max-Age freshness
# ---------------------------------------------------------------------------


class TestRebindCookieMaxAge:
    """AC-ASYNC-1: Set-Cookie Max-Age must reflect new_jwt.exp - now."""

    def test_rebind_sets_cookie_with_new_max_age(self):
        """
        Rebind response Set-Cookie Max-Age = new_jwt.exp - now (approx).

        We allow ±5s tolerance for test execution time.
        """
        new_exp_offset = 7200  # 2 hours
        mock_token = _make_sso_token(exp_offset=new_exp_offset)

        with (
            patch("backend.api.session_routes.SsoValidator.validate_token", return_value=mock_token),
            patch("backend.api.session_routes.get_session_manager") as mock_mgr_factory,
        ):
            mock_session = MagicMock()
            mock_session.session_id = "sess-rebind-test"
            mock_session.user_id = "1001"
            mock_session.jwt_valid_until = mock_token.exp
            mock_session.state.value = "ATTACHED"

            mock_mgr = MagicMock()
            mock_mgr.get_session = MagicMock(return_value=mock_session)
            mock_mgr_factory.return_value = mock_mgr

            t_before = int(time.time())
            client = TestClient(app)
            client.cookies.set("vqa_session", "sess-rebind-test")
            response = client.post(
                "/api/session/rebind",
                headers={"Authorization": "Bearer some-jwt"},
            )
            t_after = int(time.time())

        assert response.status_code == 200
        set_cookie = response.headers.get("set-cookie", "")
        assert "vqa_session=" in set_cookie

        # Extract Max-Age value from the Set-Cookie header
        import re
        match = re.search(r"[Mm]ax-[Aa]ge=(\d+)", set_cookie)
        assert match, f"Max-Age not found in Set-Cookie: {set_cookie}"
        max_age = int(match.group(1))

        # Max-Age should be approximately new_exp_offset (minus a few seconds of test time)
        expected_max_age_min = new_exp_offset - (t_after - t_before) - 5
        expected_max_age_max = new_exp_offset + 5
        assert expected_max_age_min <= max_age <= expected_max_age_max, (
            f"Max-Age {max_age} not in expected range "
            f"[{expected_max_age_min}, {expected_max_age_max}]"
        )

    def test_rebind_updates_jwt_valid_until(self):
        """After rebind, jwt_valid_until in response equals new_jwt.exp."""
        mock_token = _make_sso_token(exp_offset=5000)

        with (
            patch("backend.api.session_routes.SsoValidator.validate_token", return_value=mock_token),
            patch("backend.api.session_routes.get_session_manager") as mock_mgr_factory,
        ):
            mock_session = MagicMock()
            mock_session.session_id = "sess-rebind-test"
            mock_session.user_id = "1001"
            mock_session.jwt_valid_until = mock_token.exp
            mock_session.state.value = "ATTACHED"

            mock_mgr = MagicMock()
            mock_mgr.get_session = MagicMock(return_value=mock_session)
            mock_mgr_factory.return_value = mock_mgr

            client = TestClient(app)
            client.cookies.set("vqa_session", "sess-rebind-test")
            response = client.post(
                "/api/session/rebind",
                headers={"Authorization": "Bearer some-jwt"},
            )

        assert response.status_code == 200
        body = response.json()
        assert abs(body["jwt_valid_until"] - mock_token.exp) <= 1

    def test_rebind_cookie_value_unchanged(self):
        """Session ID in Set-Cookie remains the same session_id (session is not recreated)."""
        mock_token = _make_sso_token()

        with (
            patch("backend.api.session_routes.SsoValidator.validate_token", return_value=mock_token),
            patch("backend.api.session_routes.get_session_manager") as mock_mgr_factory,
        ):
            mock_session = MagicMock()
            mock_session.session_id = "sess-same-id-123"
            mock_session.user_id = "1001"
            mock_session.jwt_valid_until = mock_token.exp
            mock_session.state.value = "ATTACHED"

            mock_mgr = MagicMock()
            mock_mgr.get_session = MagicMock(return_value=mock_session)
            mock_mgr_factory.return_value = mock_mgr

            client = TestClient(app)
            client.cookies.set("vqa_session", "sess-same-id-123")
            response = client.post(
                "/api/session/rebind",
                headers={"Authorization": "Bearer some-jwt"},
            )

        assert response.status_code == 200
        set_cookie = response.headers.get("set-cookie", "")
        # The same session_id must appear in the cookie value
        assert "sess-same-id-123" in set_cookie


# ---------------------------------------------------------------------------
# Terminated session
# ---------------------------------------------------------------------------


class TestRebindTerminatedSession:
    """AC-ERROR-7: rebind of a terminated session must not succeed."""

    def test_rebind_not_found_session_returns_404(self):
        """Session already terminated (not in manager) → 404/410."""
        mock_token = _make_sso_token()

        with (
            patch("backend.api.session_routes.SsoValidator.validate_token", return_value=mock_token),
            patch("backend.api.session_routes.get_session_manager") as mock_mgr_factory,
        ):
            mock_mgr = MagicMock()
            mock_mgr.get_session = MagicMock(return_value=None)
            mock_mgr_factory.return_value = mock_mgr

            client = TestClient(app)
            client.cookies.set("vqa_session", "sess-terminated")
            response = client.post(
                "/api/session/rebind",
                headers={"Authorization": "Bearer some-jwt"},
            )

        assert response.status_code in (404, 410)
        body = response.json()
        assert body.get("error") == "session_not_found"

    def test_rebind_does_not_create_new_session(self):
        """Rebind of missing session MUST NOT bootstrap a new session."""
        mock_token = _make_sso_token()

        with (
            patch("backend.api.session_routes.SsoValidator.validate_token", return_value=mock_token),
            patch("backend.api.session_routes.get_session_manager") as mock_mgr_factory,
        ):
            mock_mgr = AsyncMock()
            mock_mgr.get_session = MagicMock(return_value=None)
            mock_mgr.start_session = AsyncMock()  # must NOT be called
            mock_mgr_factory.return_value = mock_mgr

            client = TestClient(app)
            client.cookies.set("vqa_session", "sess-terminated")
            client.post(
                "/api/session/rebind",
                headers={"Authorization": "Bearer some-jwt"},
            )

            # start_session must not have been called
            mock_mgr.start_session.assert_not_called()


# ---------------------------------------------------------------------------
# Cross-user rebind
# ---------------------------------------------------------------------------


class TestRebindCrossUser:
    """AC-ERROR-8: rebind where JWT vc_id != session.user_id → 403."""

    def test_cross_user_rebind_returns_403(self):
        """Bob's JWT + Alice's cookie → 403 session_user_mismatch."""
        bob_token = _make_sso_token(email="bob@vcreative.com", vc_id=9999)

        with (
            patch("backend.api.session_routes.SsoValidator.validate_token", return_value=bob_token),
            patch("backend.api.session_routes.get_session_manager") as mock_mgr_factory,
        ):
            alice_session = MagicMock()
            alice_session.session_id = "sess-alice"
            alice_session.user_id = "1001"  # Alice's ID
            alice_session.state.value = "ATTACHED"

            mock_mgr = MagicMock()
            mock_mgr.get_session = MagicMock(return_value=alice_session)
            mock_mgr_factory.return_value = mock_mgr

            client = TestClient(app)
            client.cookies.set("vqa_session", "sess-alice")
            response = client.post(
                "/api/session/rebind",
                headers={"Authorization": "Bearer bob-jwt"},
            )

        assert response.status_code == 403
        body = response.json()
        assert body.get("error") == "session_user_mismatch"

    def test_cross_user_rebind_does_not_modify_alice_session(self):
        """After a rejected cross-user rebind, Alice's session is unmodified."""
        bob_token = _make_sso_token(email="bob@vcreative.com", vc_id=9999)
        original_exp = int(time.time()) + 3600

        with (
            patch("backend.api.session_routes.SsoValidator.validate_token", return_value=bob_token),
            patch("backend.api.session_routes.get_session_manager") as mock_mgr_factory,
        ):
            alice_session = MagicMock()
            alice_session.session_id = "sess-alice"
            alice_session.user_id = "1001"
            alice_session.jwt_valid_until = original_exp
            alice_session.state.value = "ATTACHED"

            mock_mgr = MagicMock()
            mock_mgr.get_session = MagicMock(return_value=alice_session)
            mock_mgr_factory.return_value = mock_mgr

            client = TestClient(app)
            client.cookies.set("vqa_session", "sess-alice")
            client.post(
                "/api/session/rebind",
                headers={"Authorization": "Bearer bob-jwt"},
            )

            # Alice's jwt_valid_until must not have changed
            assert alice_session.jwt_valid_until == original_exp
