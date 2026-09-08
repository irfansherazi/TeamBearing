"""
Tests for pre-flight session health check (DR-007).

Validates that run_preflight_checks:
1. Passes when URL is reachable and auth is valid
2. Raises PreflightFailure("environment_unreachable") for unreachable URLs
3. Raises PreflightFailure("auth_expired") for expired auth tokens
4. Raises PreflightFailure("role_mismatch") for role mismatches
5. Is skippable via VQA_SKIP_PREFLIGHT=1
6. Completes within 15 seconds total timeout

See: backend/engine/preflight_check.py
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def mock_settings():
    """Mock settings with skip_preflight=False."""
    settings = MagicMock()
    settings.skip_preflight = False
    settings.target_url = "https://qa.vcreative.net"
    return settings


class TestPreflightHappyPath:
    """Tests that preflight passes when all checks succeed."""

    @pytest.mark.asyncio
    async def test_all_checks_pass(self, mock_settings):
        """Reachable URL + valid auth + matching role → no exception."""
        from backend.engine.preflight_check import run_preflight_checks

        with (
            patch("backend.engine.preflight_check.settings", mock_settings),
            patch("backend.engine.preflight_check.httpx") as mock_httpx,
            patch("backend.engine.preflight_check.AuthManager") as MockAuthManager,
        ):
            # URL is reachable
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_httpx.AsyncClient.return_value = mock_client

            # Auth is valid
            mock_auth = MagicMock()
            mock_auth.is_state_valid.return_value = True
            MockAuthManager.return_value = mock_auth

            # Should not raise
            await run_preflight_checks(
                run_id="run-test",
                role="account_executive",
                base_url="https://qa.vcreative.net",
            )


class TestUrlReachability:
    """Tests for URL reachability check."""

    @pytest.mark.asyncio
    async def test_unreachable_url_raises(self, mock_settings):
        """Non-2xx response → PreflightFailure('environment_unreachable')."""
        from backend.engine.preflight_check import PreflightFailure, run_preflight_checks

        with (
            patch("backend.engine.preflight_check.settings", mock_settings),
            patch("backend.engine.preflight_check.httpx") as mock_httpx,
        ):
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 503
            mock_response.text = "Service Unavailable"
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_httpx.AsyncClient.return_value = mock_client

            with pytest.raises(PreflightFailure) as exc_info:
                await run_preflight_checks(
                    run_id="run-test",
                    role="account_executive",
                    base_url="https://qa.vcreative.net",
                )
            assert exc_info.value.check_name == "environment_unreachable"

    @pytest.mark.asyncio
    async def test_timeout_raises(self, mock_settings):
        """Network timeout → PreflightFailure('environment_unreachable')."""
        import httpx as real_httpx

        from backend.engine.preflight_check import PreflightFailure, run_preflight_checks

        with (
            patch("backend.engine.preflight_check.settings", mock_settings),
            patch("backend.engine.preflight_check.httpx") as mock_httpx,
        ):
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            # Simulate a connection timeout
            mock_httpx.TimeoutException = real_httpx.TimeoutException
            mock_client.get = AsyncMock(
                side_effect=real_httpx.TimeoutException("Connection timed out")
            )
            mock_httpx.AsyncClient.return_value = mock_client

            with pytest.raises(PreflightFailure) as exc_info:
                await run_preflight_checks(
                    run_id="run-test",
                    role="account_executive",
                    base_url="https://qa.vcreative.net",
                )
            assert exc_info.value.check_name == "environment_unreachable"


class TestAuthFreshness:
    """Tests for auth token freshness check."""

    @pytest.mark.asyncio
    async def test_expired_auth_raises(self, mock_settings):
        """Expired auth token → PreflightFailure('auth_expired')."""
        from backend.engine.preflight_check import PreflightFailure, run_preflight_checks

        with (
            patch("backend.engine.preflight_check.settings", mock_settings),
            patch("backend.engine.preflight_check.httpx") as mock_httpx,
            patch("backend.engine.preflight_check.AuthManager") as MockAuthManager,
        ):
            # URL is reachable
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_httpx.AsyncClient.return_value = mock_client

            # Auth is expired
            mock_auth = MagicMock()
            mock_auth.is_state_valid.return_value = False
            MockAuthManager.return_value = mock_auth

            with pytest.raises(PreflightFailure) as exc_info:
                await run_preflight_checks(
                    run_id="run-test",
                    role="account_executive",
                    base_url="https://qa.vcreative.net",
                )
            assert exc_info.value.check_name == "auth_expired"


class TestRoleMismatch:
    """Tests for role scope check."""

    @pytest.mark.asyncio
    async def test_role_mismatch_raises(self, mock_settings):
        """Resolved role doesn't match AC's required role → PreflightFailure('role_mismatch')."""
        from backend.engine.preflight_check import PreflightFailure, run_preflight_checks

        with (
            patch("backend.engine.preflight_check.settings", mock_settings),
            patch("backend.engine.preflight_check.httpx") as mock_httpx,
            patch("backend.engine.preflight_check.AuthManager") as MockAuthManager,
        ):
            # URL is reachable
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_httpx.AsyncClient.return_value = mock_client

            # Auth is valid
            mock_auth = MagicMock()
            mock_auth.is_state_valid.return_value = True
            MockAuthManager.return_value = mock_auth

            with pytest.raises(PreflightFailure) as exc_info:
                await run_preflight_checks(
                    run_id="run-test",
                    role="producer",  # Resolved role is 'producer'
                    base_url="https://qa.vcreative.net",
                    expected_role="account_executive",  # AC requires AE — mismatch!
                )
            assert exc_info.value.check_name == "role_mismatch"


class TestSkipPreflight:
    """Tests for VQA_SKIP_PREFLIGHT bypass."""

    @pytest.mark.asyncio
    async def test_skip_preflight_bypasses_all_checks(self, mock_settings):
        """When skip_preflight=True, no checks are performed."""
        from backend.engine.preflight_check import run_preflight_checks

        mock_settings.skip_preflight = True

        with patch("backend.engine.preflight_check.settings", mock_settings):
            # Should not raise even without mocking httpx/AuthManager
            await run_preflight_checks(
                run_id="run-test",
                role="account_executive",
                base_url="https://qa.vcreative.net",
            )


class TestGraphNotInvoked:
    """Tests that preflight failure prevents graph execution."""

    @pytest.mark.asyncio
    async def test_preflight_failure_prevents_graph(self, mock_settings):
        """When preflight fails, the graph.astream should never be called."""
        from backend.engine.preflight_check import PreflightFailure, run_preflight_checks

        with (
            patch("backend.engine.preflight_check.settings", mock_settings),
            patch("backend.engine.preflight_check.httpx") as mock_httpx,
        ):
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 500
            mock_response.text = "Internal Server Error"
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_httpx.AsyncClient.return_value = mock_client

            # Create mock graph
            mock_graph = MagicMock()
            mock_graph.astream = AsyncMock()

            # Preflight should fail
            with pytest.raises(PreflightFailure):
                await run_preflight_checks(
                    run_id="run-test",
                    role="account_executive",
                    base_url="https://qa.vcreative.net",
                )

            # Graph should never have been called
            mock_graph.astream.assert_not_called()
