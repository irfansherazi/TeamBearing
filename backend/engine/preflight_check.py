"""
vQA — Pre-flight Session Health Check
========================================
Module: backend/engine/preflight_check.py

DR-007: Validates environment reachability, auth freshness, and role scope
BEFORE the LangGraph graph is started. Prevents silent auth-expiry trajectory
corruption where a session token expires mid-run and the agent types form
values into the login field.

Three checks run sequentially:
  1. URL reachability  — GET base_url with 10s timeout
  2. Auth freshness    — AuthManager.is_state_valid() for the target role
  3. Role scope        — resolved role matches AC's required role (if specified)

All three must pass or a PreflightFailure is raised with a human-readable
error message. The graph is NEVER started on preflight failure.

Skippable via VQA_SKIP_PREFLIGHT=1 env var for local development.

Usage
-----
    from backend.engine.preflight_check import run_preflight_checks

    # In routes.py, before graph.astream():
    await run_preflight_checks(run_id=run_id, role=role, base_url=settings.base_url)
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

import httpx

from backend.config import settings
from backend.engine.auth_manager import AuthManager

logger = logging.getLogger(__name__)


class PreflightFailure(Exception):
    """Raised when a pre-flight check fails.

    Attributes
    ----------
    check_name : str
        One of: "environment_unreachable", "auth_expired", "role_mismatch".
    details : str
        Human-readable explanation of the failure.
    """

    def __init__(self, check_name: str, details: str) -> None:
        self.check_name = check_name
        self.details = details
        super().__init__(f"Preflight check '{check_name}' failed: {details}")


async def run_preflight_checks(
    *,
    run_id: str,
    role: str,
    base_url: str,
    expected_role: Optional[str] = None,
    skip_auth_check: bool = False,
) -> None:
    """
    Run all pre-flight checks before starting a vQA graph execution.

    Parameters
    ----------
    run_id : str
        The unique run identifier (for structured logging).
    role : str
        The role key to authenticate as (e.g. "account_executive").
    base_url : str
        The target application URL (e.g. "https://qa.vcreative.net").
    expected_role : str | None
        If provided, the preflight will verify the resolved role matches
        this expected role. Used when the AC specifies a required role.
    skip_auth_check : bool
        When True, skip the role auth-state freshness check. Used for ghost
        login scenarios where the ghost_login_node handles all authentication
        using admin credentials directly — the selected role's storage state
        is irrelevant.

    Raises
    ------
    PreflightFailure
        If any check fails. Contains check_name and human-readable details.
    """
    # ── Skip gate ──────────────────────────────────────────────────────
    if settings.skip_preflight:
        logger.info("[%s] Preflight checks SKIPPED (VQA_SKIP_PREFLIGHT=1)", run_id)
        return

    logger.info("[%s] Running pre-flight checks...", run_id)

    # ── Check 1: URL Reachability ──────────────────────────────────────
    await _check_url_reachability(run_id, base_url)

    # ── Check 2: Auth Token Freshness ──────────────────────────────────
    if skip_auth_check:
        logger.info(
            "[%s] Preflight: Auth check SKIPPED — ghost login scenario, admin credentials handle auth",
            run_id,
        )
    else:
        await _check_auth_freshness(run_id, role, login_url=base_url)

    # ── Check 3: Role Scope Match ──────────────────────────────────────
    if expected_role:
        _check_role_scope(run_id, role, expected_role)

    logger.info("[%s] All pre-flight checks PASSED", run_id)


async def _check_url_reachability(run_id: str, base_url: str) -> None:
    """GET the base URL with a 10-second timeout."""
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(10.0),
            follow_redirects=True,
            verify=False,  # QA environments may use self-signed certs
        ) as client:
            response = await client.get(base_url)

            if response.status_code >= 400:
                logger.error(
                    "[%s] Preflight FAILED: URL %s returned HTTP %d",
                    run_id,
                    base_url,
                    response.status_code,
                )
                raise PreflightFailure(
                    check_name="environment_unreachable",
                    details=(
                        f"Target URL {base_url} returned HTTP {response.status_code}. "
                        f"Verify the environment is running and accessible."
                    ),
                )

        logger.info("[%s] Preflight: URL reachable (%s → HTTP %d)", run_id, base_url, response.status_code)

    except PreflightFailure:
        raise
    except Exception as exc:
        logger.error("[%s] Preflight FAILED: URL %s error — %s", run_id, base_url, exc)
        raise PreflightFailure(
            check_name="environment_unreachable",
            details=f"Target URL {base_url} is unreachable: {exc}",
        ) from exc


async def _check_auth_freshness(run_id: str, role: str, login_url: str | None = None) -> None:
    """Verify the auth state file for the given role is valid and not expired.

    If the state is expired or missing, attempts silent re-authentication
    via ``AuthManager.ensure_authenticated()`` before raising a failure.
    This aligns with AuthManager's design: "On TTL expiry the manager
    silently re-authenticates and overwrites the file."

    The Playwright sync login is offloaded to a thread pool so it doesn't
    block the asyncio event loop (Playwright sync API cannot run inside a
    running event loop).
    """
    try:
        auth_mgr = AuthManager(role, login_url=login_url)
        if auth_mgr.is_state_valid():
            logger.info("[%s] Preflight: Auth state for role '%s' is valid", run_id, role)
            return

        # State is expired or missing — attempt auto-re-authentication
        logger.info(
            "[%s] Preflight: Auth state for role '%s' is expired or missing — "
            "attempting automatic re-authentication...",
            run_id,
            role,
        )
        try:
            # Run sync Playwright login in a thread to avoid "sync API inside
            # asyncio loop" error from Playwright.
            await asyncio.to_thread(auth_mgr.ensure_authenticated)
        except Exception as login_exc:
            logger.error(
                "[%s] Preflight FAILED: Auto re-authentication for role '%s' failed — %s",
                run_id,
                role,
                login_exc,
            )
            raise PreflightFailure(
                check_name="auth_expired",
                details=(
                    f"Auth state for role '{role}' is expired and automatic "
                    f"re-authentication failed: {login_exc}. "
                    f"Try regenerating storage states from the Playwright panel."
                ),
            ) from login_exc

        # Verify the freshly-obtained state is actually valid
        if not auth_mgr.is_state_valid():
            logger.error(
                "[%s] Preflight FAILED: Re-authentication for role '%s' completed "
                "but state is still invalid",
                run_id,
                role,
            )
            raise PreflightFailure(
                check_name="auth_expired",
                details=(
                    f"Auth state for role '{role}' is still invalid after "
                    f"re-authentication. Check credentials and target URL."
                ),
            )

        logger.info(
            "[%s] Preflight: Auth state for role '%s' successfully refreshed",
            run_id,
            role,
        )

    except PreflightFailure:
        raise
    except Exception as exc:
        # AuthManager construction can raise KeyError (unknown role) or
        # ValueError (missing credentials). Treat as auth failure.
        logger.error(
            "[%s] Preflight FAILED: Cannot verify auth for role '%s' — %s",
            run_id,
            role,
            exc,
        )
        raise PreflightFailure(
            check_name="auth_expired",
            details=f"Cannot verify auth for role '{role}': {exc}",
        ) from exc


def _check_role_scope(run_id: str, resolved_role: str, expected_role: str) -> None:
    """Confirm the resolved role matches the AC's required role."""
    # Normalize both for comparison
    resolved = resolved_role.strip().lower()
    expected = expected_role.strip().lower()

    if resolved != expected:
        logger.error(
            "[%s] Preflight FAILED: Role mismatch — resolved='%s', expected='%s'",
            run_id,
            resolved,
            expected,
        )
        raise PreflightFailure(
            check_name="role_mismatch",
            details=(
                f"Resolved role '{resolved_role}' does not match the AC's required "
                f"role '{expected_role}'. Check role configuration."
            ),
        )
    logger.info("[%s] Preflight: Role scope matches ('%s')", run_id, resolved)
