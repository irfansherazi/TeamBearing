"""
vQA — AuthWorker (Phase 4)
============================
Module: backend/engine/workers/auth_worker.py

Specialised Worker for **login, logout, and role switching** intents.

Problem
-------
Auth-related AC steps are uniquely different from all other workers:
they interact with Playwright storage state and cookies rather than
DOM elements visible in screenshots.  The standard planner→executor
loop is inefficient and fragile for auth operations.

Solution (Phase 4C)
-------------------
The AuthWorker now delegates directly to ``auth_manager`` for:

  - **login** — calls ``ensure_role_authenticated()`` to create/refresh
    the Playwright storage state file, then navigates the active browser
    to the target URL with the authenticated session.
  - **logout** — invalidates the cached storage state and navigates to
    the login page.
  - **switch_role** — logout + login as the target role.
  - **verify** — checks that the current URL is NOT the login page
    and that the role context matches expectations.

For steps that require DOM interaction (e.g., "click the Login button"),
it falls back to the planner with ``<AUTH_RULES>`` guidance.

Dependencies
------------
  - ``backend.engine.auth_manager``  — role authentication
  - ``backend.engine.state.VQAState`` — state schema

See Also
--------
  - ``backend/engine/auth_manager.py``            — role management
  - ``backend/engine/workers/generic_worker.py``   — the generic fallback
  - ``backend/engine/supervisor.py``               — emits Intent with worker_type="auth"
"""

from __future__ import annotations

import logging

from backend.engine.state import VQAState

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# AUTH_RULES — injected into the planner's user_guidance for auth steps
# ---------------------------------------------------------------------------

_AUTH_RULES: str = """\
<AUTH_RULES>
You are an **Authentication Specialist** for vSuite.

## Login Steps

For login steps:
1. Navigate to the login page if not already there
2. Fill the email field with the provided credentials
3. Fill the password field
4. Click the "Sign In" / "Login" button
5. Wait for the dashboard to load (URL should change to /dashboard)
6. Verify the user's name appears in the top-right corner

## Logout Steps

For logout steps:
1. Click the user avatar/menu in the top-right corner
2. Click "Sign Out" / "Logout"
3. Wait for redirect to the login page
4. Verify the login form is visible

## Role Switching

For role-switching steps:
1. Logout from the current role
2. Login with the new role's credentials
3. Verify the role-specific dashboard or permissions

## Verification

For auth verification steps:
- Check that the current user name matches expected
- Check URL is not the login page (unless testing failed login)
- Check that role-specific elements are visible/hidden
</AUTH_RULES>
"""


# ---------------------------------------------------------------------------
# Direct auth delegation helpers (Phase 4C)
# ---------------------------------------------------------------------------


async def _direct_login(state: VQAState, role_key: str, run_id: str) -> dict:
    """
    Directly authenticate as ``role_key`` using auth_manager, bypassing
    the planner→executor loop.

    Calls ``ensure_role_authenticated()`` synchronously (Playwright sync_api
    under the hood) and then navigates the active browser session to the
    target URL using the refreshed storage state.

    Parameters
    ----------
    state : VQAState
        Current LangGraph state.
    role_key : str
        Role to authenticate as (e.g., ``"account_executive"``).
    run_id : str
        Run identifier for logging.

    Returns
    -------
    dict
        Partial state update with login result metadata.
    """
    import asyncio

    from backend.engine.auth_manager import ensure_role_authenticated

    logger.info(
        "[%s] AuthWorker: DIRECT LOGIN — delegating to auth_manager for role '%s'",
        run_id,
        role_key,
    )

    try:
        # Run synchronous auth_manager in a thread pool
        state_path = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: ensure_role_authenticated(role_key, headless=True),
        )

        logger.info(
            "[%s] AuthWorker: direct login succeeded — state saved to %s",
            run_id,
            state_path,
        )

        # Navigate the active browser to the target URL with the new session
        nav_result = ""
        try:
            from backend.engine.browser_session import get_manager

            manager = get_manager(run_id)
            page = manager.page
            if page:
                from backend.config import settings

                await page.goto(
                    settings.target_url,
                    wait_until="domcontentloaded",
                    timeout=30_000,
                )
                nav_result = f" → navigated to {settings.target_url}"
                logger.info(
                    "[%s] AuthWorker: post-login navigation complete",
                    run_id,
                )
        except Exception as e:
            logger.warning(
                "[%s] AuthWorker: post-login navigation failed (non-fatal): %s",
                run_id,
                e,
            )
            nav_result = f" (navigation skipped: {e})"

        return {
            "user_guidance": (
                f"[AUTH WORKER — LOGIN COMPLETE]\n"
                f"Successfully authenticated as '{role_key}'{nav_result}.\n"
                f"Auth state saved to: {state_path}\n"
                f"You may now proceed to the next AC step."
            ),
            "last_error": "",
        }

    except Exception as e:
        logger.error(
            "[%s] AuthWorker: direct login FAILED for role '%s': %s",
            run_id,
            role_key,
            e,
        )
        # Fall through to planner-based login
        return {}


async def _direct_logout(state: VQAState, role_key: str, run_id: str) -> dict:
    """
    Invalidate the cached auth state for ``role_key`` and navigate to the
    login page, bypassing the planner.

    Parameters
    ----------
    state : VQAState
        Current LangGraph state.
    role_key : str
        Role to invalidate.
    run_id : str
        Run identifier for logging.

    Returns
    -------
    dict
        Partial state update with logout result metadata.
    """
    from backend.engine.auth_manager import AuthManager

    logger.info(
        "[%s] AuthWorker: DIRECT LOGOUT — invalidating auth state for '%s'",
        run_id,
        role_key,
    )

    try:
        manager = AuthManager(role_key)
        manager.invalidate()

        # Navigate to the login page
        try:
            from backend.engine.browser_session import get_manager as get_bm

            bm = get_bm(run_id)
            page = bm.page
            if page:
                from backend.config import settings

                await page.goto(
                    settings.target_url,
                    wait_until="domcontentloaded",
                    timeout=15_000,
                )
                # Clear localStorage to ensure full logout
                await page.evaluate("localStorage.clear()")
                logger.info(
                    "[%s] AuthWorker: logout — cleared localStorage + navigated to login",
                    run_id,
                )
        except Exception as e:
            logger.warning(
                "[%s] AuthWorker: post-logout navigation failed (non-fatal): %s",
                run_id,
                e,
            )

        return {
            "user_guidance": (
                f"[AUTH WORKER — LOGOUT COMPLETE]\n"
                f"Successfully logged out from role '{role_key}'.\n"
                f"Auth state invalidated. Browser navigated to login page.\n"
                f"You may now proceed to the next AC step."
            ),
            "last_error": "",
        }

    except Exception as e:
        logger.error(
            "[%s] AuthWorker: direct logout FAILED for role '%s': %s",
            run_id,
            role_key,
            e,
        )
        return {}


async def _direct_verify(state: VQAState, run_id: str) -> dict:
    """
    Verify that the user is currently authenticated by checking the
    browser's URL and localStorage JWT.

    Returns
    -------
    dict
        Partial state update with verification guidance.
    """
    try:
        from backend.engine.browser_session import get_manager

        manager = get_manager(run_id)
        page = manager.page
        if page:
            current_url = page.url or ""
            jwt = await page.evaluate("localStorage.getItem('vc2JWT')")

            is_login_page = any(kw in current_url.lower() for kw in ["/login", "/signin", "/auth"])

            if jwt and not is_login_page:
                return {
                    "user_guidance": (
                        f"[AUTH WORKER — VERIFY]\n"
                        f"✅ User IS authenticated.\n"
                        f"  URL: {current_url}\n"
                        f"  JWT: present ({len(jwt)} chars)\n"
                        f"Proceed to the next AC step."
                    ),
                }
            elif is_login_page:
                return {
                    "user_guidance": (
                        f"[AUTH WORKER — VERIFY]\n"
                        f"❌ User is NOT authenticated — currently on login page.\n"
                        f"  URL: {current_url}\n"
                        f"A login is required before proceeding."
                    ),
                }
            else:
                return {
                    "user_guidance": (
                        f"[AUTH WORKER — VERIFY]\n"
                        f"⚠ Authentication status unclear.\n"
                        f"  URL: {current_url}\n"
                        f"  JWT: {'present' if jwt else 'missing'}\n"
                        f"Check the page visually to confirm authentication state."
                    ),
                }
    except Exception as e:
        logger.warning(
            "[%s] AuthWorker: direct verify failed: %s",
            run_id,
            e,
        )

    return {}


# ---------------------------------------------------------------------------
# Main worker node
# ---------------------------------------------------------------------------


async def auth_worker_node(state: VQAState) -> dict:
    """
    LangGraph node: AuthWorker — handle authentication-related intents.

    Processing (Phase 4C):
    1. Reads the latest Intent from ``supervisor_intents``
    2. For ``login`` / ``switch_role`` actions → direct auth_manager delegation
    3. For ``logout`` actions → invalidate state + navigate to login page
    4. For ``verify`` actions → check JWT/URL without DOM interaction
    5. Fallback → planner with AUTH_RULES guidance

    Args
    ----
    state : VQAState
        The current LangGraph state.

    Returns
    -------
    dict
        Partial state update.
    """
    from backend.engine.planner import planner_node

    run_id: str = state["run_id"]
    intents: list[dict] = state.get("supervisor_intents", [])

    if not intents:
        logger.warning(
            "[%s] AuthWorker: no supervisor intents — falling back to planner with auth rules",
            run_id,
        )
        modified_state = {**state, "user_guidance": _AUTH_RULES}
        return await planner_node(modified_state)

    latest_intent = intents[-1]
    intent_id = latest_intent.get("intent_id", "unknown")
    action = latest_intent.get("action", "interact").lower()
    target = latest_intent.get("target", "")

    logger.info(
        "[%s] AuthWorker: executing intent '%s' (target=%s, action=%s)",
        run_id,
        intent_id,
        target,
        action,
    )

    # ── Resolve the role key for direct operations ─────────────────────
    role_key = state.get("role_context", {}).get("role_key", "") or state.get("role_queue", [""])[0]

    # ── Direct delegation based on action type ─────────────────────────

    if action in ("login", "switch_role"):
        # Determine target role for switch_role
        target_role = role_key
        if action == "switch_role" and target:
            # Target field may contain the new role name/alias
            target_role = target.strip().lower().replace(" ", "_")

        if action == "switch_role" and target_role != role_key:
            # Logout from current role first
            logout_result = await _direct_logout(state, role_key, run_id)
            if logout_result:
                logger.info(
                    "[%s] AuthWorker: switch_role — logged out from '%s'",
                    run_id,
                    role_key,
                )

        direct_result = await _direct_login(state, target_role, run_id)
        if direct_result:
            return direct_result

        # Direct login failed → fall through to planner
        logger.warning(
            "[%s] AuthWorker: direct login failed — falling back to planner",
            run_id,
        )

    elif action == "logout":
        direct_result = await _direct_logout(state, role_key, run_id)
        if direct_result:
            return direct_result

        logger.warning(
            "[%s] AuthWorker: direct logout failed — falling back to planner",
            run_id,
        )

    elif action == "verify":
        direct_result = await _direct_verify(state, run_id)
        if direct_result:
            return direct_result

        logger.warning(
            "[%s] AuthWorker: direct verify failed — falling back to planner",
            run_id,
        )

    # ── Fallback: planner with AUTH_RULES ──────────────────────────────

    intent_context = f"[SUPERVISOR INTENT — AUTH WORKER]\nTarget: {target or 'Auth'}\nAction: {action}\n"

    combined_guidance = f"{intent_context}\n\n{_AUTH_RULES}"
    existing_guidance = state.get("user_guidance", "")
    if existing_guidance:
        combined_guidance = f"{combined_guidance}\n\n{existing_guidance}"

    modified_state = {**state, "user_guidance": combined_guidance}

    result = await planner_node(modified_state)

    logger.info(
        "[%s] AuthWorker: planner_node returned action=%s",
        run_id,
        result.get("planned_action", {}).get("action", "unknown"),
    )

    return result
