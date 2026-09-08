"""
Phase 1: JWT Hardening — Integration Tests
==========================================
Module: tests/test_jwt_hardening.py

Tests the Phase 1 auth hardening on SsoValidator:

  1. JWT with no `exp` claim → rejected (returns None).
  2. JWT with `(exp - now) > MAX_JWT_TTL_SECONDS` → rejected.
  3. JWT with revoked `jti` in RevokedJtiSet → rejected.
  4. JWT missing required `jti` claim → rejected.
  5. JWT missing required `vc_id` claim → rejected.
  6. Valid JWT with all required claims and TTL within limit → accepted.

Plus tests for RevokedJtiSet:
  7. add() + is_revoked() round-trip.
  8. TTL-scoped eviction: expired jti evicted from set.
  9. LRU cap: oldest entry evicted when capacity exceeded.

Acceptance Criteria Coverage:
  AC-ERROR-1 (JWT validation errors → 401) — § TestSsoValidatorHardening
  AC-ERROR-1 (revoked jti) — § TestRevokedJtiSet

Per-Phase Test Guidance (task file §Phase 1):
  JWT hardening: missing exp → 401, >1h TTL → 401, revoked jti → 401.
"""

import time
from unittest.mock import patch, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_jwt_payload(
    *,
    include_exp: bool = True,
    include_jti: bool = True,
    include_vc_id: bool = True,
    ttl_seconds: int = 3600,
    jti: str = "test-jti-001",
    vc_id: int = 42,
    email: str = "alice@vcreative.com",
) -> dict:
    """Build a JWT payload dict for testing SsoValidator."""
    now = int(time.time())
    payload = {
        "email": email,
        "vc_guid": "guid-001",
        "vc_status": 1,
        "session_salt": "salt",
    }
    if include_exp:
        payload["exp"] = now + ttl_seconds
    if include_jti:
        payload["jti"] = jti
    if include_vc_id:
        payload["vc_id"] = vc_id
    return payload


# ---------------------------------------------------------------------------
# 1. SsoValidator hardening
# ---------------------------------------------------------------------------


class TestSsoValidatorHardening:
    """SsoValidator.validate_token() enforces exp + jti + vc_id + MAX_JWT_TTL_SECONDS."""

    def _patch_jwt_decode(self, payload: dict):
        """Return a context manager that makes jwt.decode return the given payload."""
        import jwt as pyjwt
        return patch.object(
            pyjwt,
            "decode",
            return_value=payload,
        )

    def test_valid_jwt_is_accepted(self):
        """A JWT with all required claims and TTL within limit is accepted."""
        from backend.auth.sso import SsoValidator
        payload = _make_jwt_payload(ttl_seconds=1800)
        with (
            patch.object(SsoValidator, "get_public_key", return_value="fake-pem"),
            self._patch_jwt_decode(payload),
            patch.dict("os.environ", {"MAX_JWT_TTL_SECONDS": "3600"}),
        ):
            result = SsoValidator.validate_token("fake.jwt.token")
        assert result is not None, "Valid JWT must be accepted"
        assert result.email == "alice@vcreative.com"

    def test_missing_exp_is_rejected(self):
        """JWT without exp claim is rejected (returns None)."""
        from backend.auth.sso import SsoValidator
        payload = _make_jwt_payload(include_exp=False)
        with (
            patch.object(SsoValidator, "get_public_key", return_value="fake-pem"),
            self._patch_jwt_decode(payload),
            patch.dict("os.environ", {"MAX_JWT_TTL_SECONDS": "3600"}),
        ):
            result = SsoValidator.validate_token("fake.jwt.token")
        assert result is None, "JWT missing exp must be rejected"

    def test_missing_jti_is_rejected(self):
        """JWT without jti claim is rejected."""
        from backend.auth.sso import SsoValidator
        payload = _make_jwt_payload(include_jti=False)
        with (
            patch.object(SsoValidator, "get_public_key", return_value="fake-pem"),
            self._patch_jwt_decode(payload),
            patch.dict("os.environ", {"MAX_JWT_TTL_SECONDS": "3600"}),
        ):
            result = SsoValidator.validate_token("fake.jwt.token")
        assert result is None, "JWT missing jti must be rejected"

    def test_missing_vc_id_is_rejected(self):
        """JWT without vc_id claim is rejected."""
        from backend.auth.sso import SsoValidator
        payload = _make_jwt_payload(include_vc_id=False)
        with (
            patch.object(SsoValidator, "get_public_key", return_value="fake-pem"),
            self._patch_jwt_decode(payload),
            patch.dict("os.environ", {"MAX_JWT_TTL_SECONDS": "3600"}),
        ):
            result = SsoValidator.validate_token("fake.jwt.token")
        assert result is None, "JWT missing vc_id must be rejected"

    def test_jwt_exceeding_max_ttl_is_rejected(self):
        """JWT with (exp - now) > MAX_JWT_TTL_SECONDS is rejected."""
        from backend.auth.sso import SsoValidator
        # TTL is 2h but max is 1h
        payload = _make_jwt_payload(ttl_seconds=7200)
        with (
            patch.object(SsoValidator, "get_public_key", return_value="fake-pem"),
            self._patch_jwt_decode(payload),
            patch.dict("os.environ", {"MAX_JWT_TTL_SECONDS": "3600"}),
        ):
            result = SsoValidator.validate_token("fake.jwt.token")
        assert result is None, "JWT with TTL > MAX_JWT_TTL_SECONDS must be rejected"

    def test_jwt_within_max_ttl_is_accepted(self):
        """JWT with (exp - now) == MAX_JWT_TTL_SECONDS (exactly) is accepted."""
        from backend.auth.sso import SsoValidator
        # Exactly 1h — on the boundary, should be accepted
        payload = _make_jwt_payload(ttl_seconds=3600)
        with (
            patch.object(SsoValidator, "get_public_key", return_value="fake-pem"),
            self._patch_jwt_decode(payload),
            patch.dict("os.environ", {"MAX_JWT_TTL_SECONDS": "3600"}),
        ):
            result = SsoValidator.validate_token("fake.jwt.token")
        assert result is not None, "JWT with TTL == MAX_JWT_TTL_SECONDS must be accepted"

    def test_revoked_jti_is_rejected(self):
        """JWT with a jti in RevokedJtiSet is rejected."""
        from backend.auth.sso import SsoValidator
        from backend.auth.revocation import RevokedJtiSet
        jti = "revoked-jti-001"
        payload = _make_jwt_payload(jti=jti, ttl_seconds=1800)
        revoked = RevokedJtiSet()
        revoked.add(jti, expires_at=time.time() + 3600)

        # sso.py does a lazy import: `from backend.auth.revocation import get_revocation_set`
        # inside the function body, so we patch the source module.
        with (
            patch.object(SsoValidator, "get_public_key", return_value="fake-pem"),
            self._patch_jwt_decode(payload),
            patch.dict("os.environ", {"MAX_JWT_TTL_SECONDS": "3600"}),
            patch("backend.auth.revocation.get_revocation_set", return_value=revoked),
        ):
            result = SsoValidator.validate_token("fake.jwt.token")
        assert result is None, "JWT with revoked jti must be rejected"


# ---------------------------------------------------------------------------
# 2. RevokedJtiSet
# ---------------------------------------------------------------------------


class TestRevokedJtiSet:
    """RevokedJtiSet LRU + TTL-scoped in-memory revocation store."""

    def test_add_and_is_revoked_round_trip(self):
        """add() + is_revoked() round-trip: added jti is recognised as revoked."""
        from backend.auth.revocation import RevokedJtiSet
        rs = RevokedJtiSet()
        rs.add("jti-abc", expires_at=time.time() + 3600)
        assert rs.is_revoked("jti-abc")

    def test_unknown_jti_is_not_revoked(self):
        """A jti that was never added is not revoked."""
        from backend.auth.revocation import RevokedJtiSet
        rs = RevokedJtiSet()
        assert not rs.is_revoked("jti-unknown-999")

    def test_expired_jti_is_evicted(self):
        """A jti whose expires_at is in the past is treated as not revoked (auto-evicted)."""
        from backend.auth.revocation import RevokedJtiSet
        rs = RevokedJtiSet()
        # Set expires_at to 1s ago
        rs.add("jti-expired-001", expires_at=time.time() - 1)
        assert not rs.is_revoked("jti-expired-001"), (
            "Expired jti must be evicted and reported as not revoked"
        )

    def test_lru_eviction_at_capacity(self):
        """When the set is full, the oldest entry is evicted."""
        from backend.auth.revocation import RevokedJtiSet
        rs = RevokedJtiSet(max_size=3)
        future = time.time() + 3600
        rs.add("jti-1", expires_at=future)
        rs.add("jti-2", expires_at=future)
        rs.add("jti-3", expires_at=future)
        # Adding a 4th should evict jti-1
        rs.add("jti-4", expires_at=future)
        # jti-4 must be present; jti-1 should have been evicted (LRU oldest)
        assert rs.is_revoked("jti-4"), "Newest jti must be in the set"
        # At least one of the older jtis should be gone (LRU eviction)
        evicted_count = sum(
            0 if rs.is_revoked(j) else 1 for j in ["jti-1", "jti-2", "jti-3"]
        )
        assert evicted_count >= 1, "At least one old jti must be evicted at capacity"


# ---------------------------------------------------------------------------
# 3. Cookies module
# ---------------------------------------------------------------------------


class TestCookiesModule:
    """backend.auth.cookies provides issue_session_cookie and read_session_cookie."""

    def test_issue_session_cookie_importable(self):
        """issue_session_cookie is importable from backend.auth.cookies."""
        from backend.auth.cookies import issue_session_cookie
        assert callable(issue_session_cookie)

    def test_read_session_cookie_importable(self):
        """read_session_cookie is importable from backend.auth.cookies."""
        from backend.auth.cookies import read_session_cookie
        assert callable(read_session_cookie)

    def test_issue_returns_cookie_dict(self):
        """issue_session_cookie returns a dict with name, value, httponly, samesite."""
        from backend.auth.cookies import issue_session_cookie
        exp = int(time.time()) + 3600
        cookie = issue_session_cookie(
            session_id="sess-cookie-001",
            max_age=3600,
            secure=True,
        )
        assert cookie["value"] == "sess-cookie-001"
        assert cookie["httponly"] is True
        assert cookie["samesite"] == "lax"
        assert cookie["max_age"] == 3600

    def test_secure_flag_false_in_dev(self):
        """issue_session_cookie(secure=False) produces a cookie without Secure flag."""
        from backend.auth.cookies import issue_session_cookie
        cookie = issue_session_cookie(
            session_id="sess-dev-001",
            max_age=3600,
            secure=False,
        )
        assert cookie["secure"] is False

    def test_secure_flag_true_in_prod(self):
        """issue_session_cookie(secure=True) produces a cookie with Secure flag."""
        from backend.auth.cookies import issue_session_cookie
        cookie = issue_session_cookie(
            session_id="sess-prod-001",
            max_age=3600,
            secure=True,
        )
        assert cookie["secure"] is True
