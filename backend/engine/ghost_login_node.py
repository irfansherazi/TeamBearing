"""
backend/engine/ghost_login_node.py
==================================
LangGraph Node for GHOST_LOGIN step type.

Responsibility: authenticate the browser as an Admin user (via HITL
credentials or SSO-token injection) and land on the target product URL.
The actual ghost-panel DOM interaction — clicking the "Ghost In As"
dropdown, filtering to the target user, and selecting the matching row —
is deliberately delegated to the planner + vision loop so vQA does not
hardcode selectors for the products it tests.

Flow:
  1. Extract target_user from the current structured step.
  2. Obtain Admin credentials (cached pre-flight or HITL gate).
  3. Authenticate as Admin (unless already authenticated by login_node).
  4. Navigate to the product URL so the planner sees the ghost panel.
  5. Set ghost_admin_authenticated=True and return to the planner WITHOUT
     advancing the step index — the planner handles the impersonation UI
     and advances the step when it completes.

The graph route at graph.py:choose_first_planner_or_ghost checks the
ghost_admin_authenticated flag so this node runs at most once per
impersonation. When the planner completes the GHOST_LOGIN step and
advances to a non-GHOST_LOGIN step, the flag becomes irrelevant.
"""

import json
import logging
import time

from backend.browser.context import get_manager
from backend.engine.persona_switch_node import (
    _ghost_creds,
    _login_with_ephemeral_creds,
    _wait_for_ghost_credentials,
    _wait_for_post_login_spa_render,
    broadcast_ws_message,
)

logger = logging.getLogger(__name__)


async def _login_with_sso_token(
    page,
    sso_token: str,
    target_url: str,
    run_id: str,
) -> dict:
    """
    Experimental: inject the operator's SSO/app token directly into the
    Playwright browser's localStorage as the JWT key, then reload so the
    SPA picks it up — skipping the browser login form entirely.

    Falls back gracefully: if the JWT is not present after reload the caller
    should re-prompt with email + password.
    """
    t_start = time.monotonic()

    try:
        _profile = None
        try:
            from backend.profiles.profile import get_active_profile
            _profile = get_active_profile() if callable(get_active_profile) else None
        except Exception:
            pass
        jwt_key = (_profile.jwt_storage_key if _profile else None) or "vc2JWT"

        await page.goto(target_url, wait_until="networkidle", timeout=20000)
        await page.evaluate(
            f"localStorage.setItem({json.dumps(jwt_key)}, {json.dumps(sso_token)})"
        )
        await page.reload(wait_until="networkidle", timeout=20000)
        await _wait_for_post_login_spa_render(page, run_id)

        jwt_value = await page.evaluate(
            f"localStorage.getItem({json.dumps(jwt_key)})"
        )
        jwt_present = bool(jwt_value)
    except Exception as e:
        logger.warning("[%s] SSO token injection failed: %s", run_id, e)
        jwt_present = False

    duration_ms = int((time.monotonic() - t_start) * 1000)
    logger.info(
        "[%s] SSO token ghost login: jwt_present=%s, duration=%dms",
        run_id, jwt_present, duration_ms,
    )
    return {"success": jwt_present, "jwt_present": jwt_present, "duration_ms": duration_ms}


def _resolve_ghost_login_url(target_url: str) -> str:
    """
    Return the URL to use for ghost login authentication.

    For most products this is the same as target_url. For products like vPPO
    and vPromotions that live on separate subdomains, ghost_login_environments
    in the product registry points to the shared vcreative login site. After
    ghosting there, the SSO cookie (.vcreative.net) carries the session when
    the node subsequently navigates to target_url.
    """
    try:
        from backend.config.product_registry import load_product_registry
        registry = load_product_registry()
        for slug in registry.slugs():
            product = registry.get(slug)
            for env_name, env_url in product.environments.items():
                if env_url.rstrip("/") == target_url.rstrip("/"):
                    override = product.resolve_ghost_login_url(env_name)
                    if override:
                        logger.debug(
                            "Ghost login URL override for product '%s' env '%s': %s → %s",
                            product.slug, env_name, target_url, override,
                        )
                        return override
    except Exception as err:
        logger.debug("Ghost login URL resolution failed (non-fatal): %s", err)
    return target_url


async def ghost_login_node(state: dict) -> dict:
    """
    LangGraph node: authenticate as Admin and land on the target product URL,
    then hand off to the planner for the ghost-panel DOM interaction.

    Never advances ac_step_index — the planner completes the step by
    interacting with the ghost dropdown using its normal DOM/vision loop.
    """
    run_id = state.get("run_id", "unknown")
    target_url = state.get("target_url", "")

    # 1. Extract target_user from the current structured step (for logging + WS).
    structured_step_index = state.get("structured_step_index", state.get("ac_step_index", 0))
    test_plan = state.get("test_plan") or {}
    if hasattr(test_plan, "steps"):
        steps = test_plan.steps
    else:
        steps = test_plan.get("steps", [])

    if structured_step_index >= len(steps):
        logger.error(
            "[%s] ghost_login_node: step index %d out of range (total steps: %d)",
            run_id, structured_step_index, len(steps),
        )
        return {"_next_node": "planner"}

    current_step = steps[structured_step_index]
    if hasattr(current_step, "target_user"):
        target_user = current_step.target_user or ""
    else:
        target_user = (current_step.get("target_user") or "").strip()

    logger.info(
        "[%s] 🔄 GHOST LOGIN: preparing admin session (target_user=%s)",
        run_id, target_user or "<unspecified>",
    )

    # 2. Resolve the URL to use for authentication.
    # For vPPO / vPromotions this is the main vcreative site rather than the
    # product-specific URL. The SSO cookie (.vcreative.net) carries the ghosted
    # session when we subsequently navigate to target_url.
    ghost_login_url = _resolve_ghost_login_url(target_url)
    needs_product_nav = ghost_login_url.rstrip("/") != target_url.rstrip("/")
    if needs_product_nav:
        logger.info(
            "[%s] Ghost login via shared auth site: %s → product: %s",
            run_id, ghost_login_url, target_url,
        )

    # 3. Get browser context
    try:
        manager = get_manager(run_id)
        page = manager.page
    except Exception as ctx_err:
        logger.error("[%s] ghost_login_node: browser manager unavailable: %s", run_id, ctx_err)
        return {
            "_next_node": "planner",
            "last_error": f"GHOST_LOGIN: browser manager unavailable: {ctx_err}",
        }

    t_start = time.monotonic()

    # 4. Obtain Admin Credentials via HITL Gate (or use cached pre-flight credentials)
    creds = _ghost_creds.get(run_id)
    if not creds:
        logger.info("[%s] Admin credentials not found in memory — pausing for HITL gate", run_id)
        try:
            creds = await _wait_for_ghost_credentials(run_id)
        except Exception as hitl_err:
            logger.error("[%s] HITL Admin credentials gate failed: %s", run_id, hitl_err)
            return {
                "_next_node": "planner",
                "last_error": f"GHOST_LOGIN: HITL admin gate failed: {hitl_err}",
            }

    # 5. Authenticate as Admin at ghost_login_url — unless login_node already
    # pre-authenticated us. Two independent success signals — either is enough:
    #  - JWT in localStorage under the profile's key (same-origin logins).
    #  - Browser is not on any /login page (SSO cookie carries session
    #    cross-domain; the JWT probe returns null on the gateway domain even
    #    though auth succeeded).
    try:
        _jwt_key_early = "vc2JWT"
        try:
            from backend.profiles.profile import get_active_profile as _gap_early
            _profile_early = _gap_early() if callable(_gap_early) else None
            if _profile_early and _profile_early.jwt_storage_key:
                _jwt_key_early = _profile_early.jwt_storage_key
        except Exception:
            pass
        _existing_jwt = await page.evaluate(f"localStorage.getItem('{_jwt_key_early}')")
    except Exception:
        _existing_jwt = None

    try:
        _url_raw = page.url
        _current_url = _url_raw.lower() if isinstance(_url_raw, str) else ""
    except Exception:
        _current_url = ""
    _off_login_page = bool(_current_url) and "/login" not in _current_url
    _already_authenticated = bool(_existing_jwt) or _off_login_page

    if _already_authenticated:
        # The ghost panel lives on the product page itself, not on the SSO
        # gateway. If we're already on the target product's domain, STAY —
        # navigating to ghost_login_url would send us back to the SSO product
        # picker and lose the vPromotions context.
        from urllib.parse import urlparse as _urlparse_auth
        try:
            _cur_netloc = _urlparse_auth(page.url).netloc if isinstance(page.url, str) else ""
        except Exception:
            _cur_netloc = ""
        try:
            _target_netloc = _urlparse_auth(target_url).netloc
        except Exception:
            _target_netloc = ""

        if _cur_netloc and _target_netloc and _cur_netloc == _target_netloc:
            logger.info(
                "[%s] Ghost login: admin already authenticated and already on target product (%s) — "
                "staying put for planner-driven ghost panel interaction",
                run_id, page.url,
            )
        else:
            logger.info(
                "[%s] Ghost login: admin already authenticated (jwt=%s, off_login_page=%s, url=%s) — "
                "navigating to target product URL",
                run_id, bool(_existing_jwt), _off_login_page, page.url,
            )
            try:
                await page.goto(target_url, wait_until="networkidle", timeout=20000)
                await _wait_for_post_login_spa_render(page, run_id)
            except Exception as _nav_err:
                logger.warning("[%s] Ghost login: navigate to target URL failed (non-fatal): %s", run_id, _nav_err)
    elif creds.get("sso_token"):
        try:
            login_result = await _login_with_sso_token(
                page, creds["sso_token"], ghost_login_url, run_id
            )
            if not login_result.get("success"):
                logger.warning(
                    "[%s] SSO token injection did not produce a JWT — falling back to form login prompt",
                    run_id,
                )
                return {
                    "_next_node": "planner",
                    "last_error": "GHOST_LOGIN: SSO token injection failed — retry with email and password.",
                }
        except Exception as login_err:
            logger.error("[%s] Admin login execution failed: %s", run_id, login_err)
            return {
                "_next_node": "planner",
                "last_error": f"GHOST_LOGIN: login error: {login_err}",
            }
    else:
        try:
            login_result = await _login_with_ephemeral_creds(
                page, creds["email"], creds["password"], ghost_login_url, run_id
            )
            if not login_result.get("success"):
                logger.error("[%s] Admin login failed using provided credentials", run_id)
                return {"_next_node": "planner", "last_error": "GHOST_LOGIN: Admin login failed."}
        except Exception as login_err:
            logger.error("[%s] Admin login execution failed: %s", run_id, login_err)
            return {
                "_next_node": "planner",
                "last_error": f"GHOST_LOGIN: login error: {login_err}",
            }

    # 6. For products with a separate login site, navigate to the product URL now.
    # The SSO cookie set at .vcreative.net carries the admin session cross-subdomain.
    # The planner takes over from here to drive the ghost panel.
    if needs_product_nav:
        try:
            logger.info("[%s] Navigating to product URL for planner handoff: %s", run_id, target_url)
            await page.goto(target_url, wait_until="networkidle", timeout=20000)
            await _wait_for_post_login_spa_render(page, run_id)
        except Exception as nav_err:
            logger.error("[%s] Post-login product navigation failed: %s", run_id, nav_err)
            return {
                "_next_node": "planner",
                "last_error": f"GHOST_LOGIN: product navigation failed: {nav_err}",
            }

    duration_ms = int((time.monotonic() - t_start) * 1000)
    logger.info(
        "[%s] ✓ Ghost admin session ready in %dms — handing off to planner for impersonation UI (target_user=%s)",
        run_id, duration_ms, target_user or "<unspecified>",
    )

    try:
        await broadcast_ws_message(run_id, {
            "type": "GHOST_ADMIN_READY",
            "target_user": target_user,
            "duration_ms": duration_ms,
        })
    except Exception as ws_err:
        logger.debug("[%s] GHOST_ADMIN_READY broadcast failed: %s", run_id, ws_err)

    # 7. Hand off to the planner. Do NOT advance ac_step_index — the planner
    # completes the GHOST_LOGIN step by driving the ghost-panel UI, then
    # advances the index like any other step. Setting
    # ghost_admin_authenticated prevents this node from re-running.
    return {
        "ghost_admin_authenticated": True,
        "_next_node": "planner",
    }
