"""
backend/engine/persona_switch_node.py
======================================
LangGraph node for mid-test persona (auth context) switching.

TASK-063 Phase 3 — Executor & Graph.

This node handles the PERSONA_SWITCH step type, which replaces the current
browser auth context with a different user's credentials. It is fully
additive — no changes to the planner, executor, or existing ACCOUNT_SWITCH path.

Architecture Decision (from TASK-063-persona-switching-architecture.md):
  Option A — Dedicated persona_switch_node inserted in LangGraph graph with
  evaluator routing.

Algorithm Decision (from TASK-063-persona-switching-algorithm.md):
  Option A — Two-stage resolution with cached auth state application and
  asyncio.Event HITL gate.

Flow:
  1. Extract target_persona from current structured step
  2. Resolve target_persona → role_key + method (stored / initial_actor / None→HITL)
  3. Execute auth switch:
     a. Known persona: ensure_role_authenticated() + add_cookies + page.goto
     b. Unknown persona: emit HITL WS event, wait for credentials, form login
  4. Update state: current_persona, persona_switch_history, _next_node="planner"

Security:
  - Ephemeral credentials (_persona_creds) are NEVER written to disk
  - NEVER passed to ensure_role_authenticated() or AuthManager
  - Cleared by the unregister_manager teardown callback on run completion
  - Passwords are scrubbed from logs at INFO level via logger pattern
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone

# Module-level imports for patchability in tests.
# These are imported at module level so unit tests can patch them via
# `patch("backend.engine.persona_switch_node.get_manager", ...)` etc.
try:
    from backend.browser.context import get_manager
except ImportError:
    get_manager = None  # type: ignore[assignment]

try:
    from backend.engine.auth_manager import ensure_role_authenticated
except ImportError:
    ensure_role_authenticated = None  # type: ignore[assignment]

try:
    from backend.profiles import get_active_profile
except ImportError:
    get_active_profile = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level HITL state (per-run, in-memory only)
# ---------------------------------------------------------------------------

# run_id → asyncio.Event (set when credentials are submitted)
_persona_events: dict[str, asyncio.Event] = {}

# run_id → {persona_name → {"email": ..., "password": ...}}
_persona_creds: dict[str, dict[str, dict]] = {}

# run_id → asyncio.Event for ghost credentials
_ghost_events: dict[str, asyncio.Event] = {}

# run_id → {"email": ..., "password": ...} for ghost credentials
_ghost_creds: dict[str, dict] = {}

# Sentinel value: AC parser normalizes "as yourself" → "current_user"
SENTINEL_CURRENT_USER = "current_user"

# HITL timeout: operator has 5 minutes to provide credentials
_HITL_TIMEOUT_SECONDS = 300.0


# ---------------------------------------------------------------------------
# Persona resolution
# ---------------------------------------------------------------------------


def resolve_target_persona(
    target_persona: str,
    run_memory: dict,
) -> tuple[str | None, str | None]:
    """
    Map a target_persona string to a canonical role_key and resolution method.

    Returns
    -------
    (role_key, method) where:
      - role_key: canonical role key (e.g. "digital_director") or None if unknown
      - method: "stored" | "initial_actor" | None (None means HITL required)

    Parameters
    ----------
    target_persona : str
        The persona string from the PERSONA_SWITCH step. May be a sentinel
        ("current_user"), a direct role key, or a display name / alias.
    run_memory : dict
        The VQAState run_memory dict. Used to resolve "current_user" sentinel.
    """
    if not target_persona:
        return None, None

    # Normalize: lowercase and strip for comparison
    persona_lower = target_persona.strip().lower()

    # ── Sentinel: "current_user" / "CURRENT_USER" → initial_actor ────────
    if persona_lower == SENTINEL_CURRENT_USER:
        initial_actor = run_memory.get("initial_actor", {})
        role_key = initial_actor.get("role_key")
        if role_key:
            logger.debug("resolve_target_persona: '%s' → initial_actor role_key='%s'", target_persona, role_key)
            return role_key, "initial_actor"
        logger.warning(
            "resolve_target_persona: '%s' sentinel but run_memory.initial_actor missing role_key", target_persona
        )
        return None, None

    # ── Direct ROLE_REGISTRY key lookup ───────────────────────────────────
    try:
        from backend.engine.roles import ROLE_REGISTRY
        if persona_lower in ROLE_REGISTRY:
            logger.debug("resolve_target_persona: '%s' is a direct role_key", target_persona)
            return persona_lower, "stored"
    except (ImportError, AttributeError):
        pass

    # ── Alias resolution (case-insensitive fuzzy name matching) ──────────
    try:
        from backend.engine.roles import resolve_role_by_name
        resolved = resolve_role_by_name(target_persona)
        if resolved:
            role_key = resolved.role_key if hasattr(resolved, "role_key") else resolved.get("role_key")
            if role_key:
                logger.debug(
                    "resolve_target_persona: '%s' resolved via alias → '%s'", target_persona, role_key
                )
                return role_key, "stored"
    except (ImportError, AttributeError, Exception) as err:
        logger.debug("resolve_target_persona: alias lookup failed (non-fatal): %s", err)

    # ── Unknown persona → HITL required ───────────────────────────────────
    logger.info("resolve_target_persona: '%s' not found in registry or aliases → HITL required", target_persona)
    return None, None


# ---------------------------------------------------------------------------
# HITL credential gate
# ---------------------------------------------------------------------------


async def _wait_for_persona_credentials(
    run_id: str,
    persona_name: str,
) -> dict:
    """
    Pause graph execution and wait for operator to provide credentials.

    Broadcasts HITL_PERSONA_CREDENTIALS_REQUIRED via WebSocket.
    Returns credential dict when submitted. Raises RuntimeError on timeout.

    Parameters
    ----------
    run_id : str
        The active run ID (used as the HITL event key and WS channel key).
    persona_name : str
        The raw persona name string (for display in the HITL UI).
    """
    event = asyncio.Event()
    _persona_events[run_id] = event

    try:
        await broadcast_ws_message(run_id, {
            "type": "HITL_PERSONA_CREDENTIALS_REQUIRED",
            "persona_name": persona_name,
            "message": f"Unknown persona '{persona_name}'. Please provide login credentials to continue.",
            "run_id": run_id,
        })
    except Exception as ws_err:
        logger.warning("[%s] HITL WS broadcast failed (non-fatal): %s", run_id, ws_err)

    logger.info("[%s] ⏸️  HITL persona gate: waiting for credentials for '%s'", run_id, persona_name)

    try:
        await asyncio.wait_for(event.wait(), timeout=_HITL_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        _persona_events.pop(run_id, None)
        raise RuntimeError(
            f"HITL persona credential gate timed out after {_HITL_TIMEOUT_SECONDS}s "
            f"for run '{run_id}', persona '{persona_name}'"
        )
    finally:
        _persona_events.pop(run_id, None)

    creds = _persona_creds.get(run_id, {}).get(persona_name)
    if not creds:
        raise RuntimeError(
            f"Credential gate resolved but no credentials found for '{persona_name}' "
            f"in run '{run_id}'"
        )
    logger.info("[%s] ✓ HITL credentials received for persona '%s'", run_id, persona_name)
    return creds


def set_persona_credentials(run_id: str, persona_name: str, email: str, password: str) -> None:
    """
    Called by the API endpoint POST /runs/{run_id}/persona-credentials.

    Stores credentials ephemerally in _persona_creds and unblocks the
    asyncio.Event that the persona_switch_node is waiting on.

    Security:
      - Credentials are ONLY stored in _persona_creds (module-level dict)
      - Never written to disk, never passed to ensure_role_authenticated()
      - Cleared when run_id is unregistered from the browser manager
    """
    if run_id not in _persona_creds:
        _persona_creds[run_id] = {}
    _persona_creds[run_id][persona_name] = {"email": email, "password": password}
    logger.info("[%s] HITL: credentials stored for persona '%s' (email=%s...)", run_id, persona_name, email[:8])

    event = _persona_events.get(run_id)
    if event:
        event.set()
    else:
        logger.warning(
            "[%s] set_persona_credentials: no pending event for run_id (may be stale)", run_id
        )


def clear_run_creds(run_id: str) -> None:
    """
    Discard all ephemeral credentials for a completed/cancelled run.

    Called by the browser manager teardown (unregister_manager) to ensure
    ephemeral credentials are purged even if run terminates unexpectedly.
    """
    _persona_creds.pop(run_id, None)
    _persona_events.pop(run_id, None)
    _ghost_creds.pop(run_id, None)
    _ghost_events.pop(run_id, None)
    logger.debug("[%s] Ephemeral persona & ghost credentials purged", run_id)


# ---------------------------------------------------------------------------
# Ghost Login HITL credential gate (TASK-102)
# ---------------------------------------------------------------------------


async def _wait_for_ghost_credentials(run_id: str) -> dict:
    """
    Pause graph execution and wait for operator to provide Admin credentials.
    """
    event = asyncio.Event()
    _ghost_events[run_id] = event

    try:
        await broadcast_ws_message(run_id, {
            "type": "GHOST_CREDENTIALS_REQUIRED",
            "run_id": run_id,
            "message": "Admin credentials required for Ghost Login impersonation. Please provide Admin email and password.",
        })
    except Exception as ws_err:
        logger.warning("[%s] Ghost Login HITL WS broadcast failed (non-fatal): %s", run_id, ws_err)

    logger.info("[%s] ⏸️  HITL ghost login gate: waiting for Admin credentials", run_id)

    try:
        await asyncio.wait_for(event.wait(), timeout=300.0)
    except asyncio.TimeoutError:
        _ghost_events.pop(run_id, None)
        raise RuntimeError(
            "GHOST_LOGIN step requires admin credentials — none provided."
        )
    finally:
        _ghost_events.pop(run_id, None)

    creds = _ghost_creds.get(run_id)
    if not creds:
        raise RuntimeError(
            "GHOST_LOGIN step requires admin credentials — none provided."
        )
    logger.info("[%s] ✓ HITL Admin credentials received for Ghost Login", run_id)
    return creds


def has_ghost_credentials(run_id: str) -> bool:
    """Return True if ghost credentials have already been pre-populated for this run."""
    return run_id in _ghost_creds


def set_ghost_credentials(
    run_id: str,
    email: str | None,
    password: str | None,
    sso_token: str | None = None,
) -> None:
    """
    Called by the API endpoint POST /runs/{run_id}/ghost-credentials.

    Accepts either an sso_token (experimental fast-path) or email+password.
    """
    if sso_token:
        _ghost_creds[run_id] = {"sso_token": sso_token}
        logger.info("[%s] HITL: SSO token stored for Ghost Login (experimental fast-path)", run_id)
    else:
        _ghost_creds[run_id] = {"email": email, "password": password}
        logger.info("[%s] HITL: Admin credentials stored for Ghost Login", run_id)

    event = _ghost_events.get(run_id)
    if event:
        event.set()
    else:
        logger.warning(
            "[%s] set_ghost_credentials: no pending event for run_id (may be stale)", run_id
        )


# ---------------------------------------------------------------------------
# Auth switch helpers
# ---------------------------------------------------------------------------


async def _wait_for_post_login_spa_render(page, run_id: str) -> None:
    """
    Wait for the SPA to finish rendering after a persona switch.

    Reuses the same barrier pattern as login_node in graph.py:
    waits for Angular's ng-version attribute or a fallback timeout.
    """
    # Import from graph to reuse the exact same logic
    try:
        from backend.engine.graph import _wait_for_post_login_spa_render as _graph_barrier
        await _graph_barrier(page, run_id)
    except (ImportError, Exception) as err:
        # Fallback: simple networkidle wait
        logger.debug("[%s] SPA barrier import failed, using fallback wait: %s", run_id, err)
        try:
            await page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass


async def _perform_auth_switch(
    page,
    context,
    role_key: str,
    target_url: str,
    run_id: str,
) -> dict:
    """
    Replace the current browser auth context with role_key's stored state.

    Algorithm:
    1. Clear localStorage (remove JWT to avoid partial-state bleed)
    2. Load stored auth state via ensure_role_authenticated(role_key)
    3. Apply cookies to existing context via context.add_cookies()
    4. Navigate to app root (triggers SPA init + applies localStorage state)
    5. Inject stored localStorage entries (JWT etc.)
    6. Wait for SPA barrier
    7. Verify JWT present

    Returns
    -------
    dict with keys: success (bool), jwt_present (bool), duration_ms (int)
    """
    t_start = time.monotonic()

    # Step 1: Clear existing auth state
    try:
        _profile = get_active_profile() if callable(get_active_profile) else None
        jwt_key = (_profile.jwt_storage_key if _profile else None) or "vc2JWT"
    except Exception:
        jwt_key = "vc2JWT"

    await page.evaluate(f"""
        localStorage.removeItem('{jwt_key}');
        localStorage.clear();
    """)
    logger.info("[%s] ✓ localStorage cleared for persona switch to '%s'", run_id, role_key)

    # Step 2: Get stored auth state path
    state_path = ensure_role_authenticated(role_key)

    # Step 3: Load and apply auth state
    with open(state_path) as f:
        storage_state = json.load(f)

    if storage_state.get("cookies"):
        await context.add_cookies(storage_state["cookies"])
        logger.debug("[%s] Applied %d cookies for role '%s'", run_id, len(storage_state["cookies"]), role_key)

    # Step 4: Navigate to app root
    await page.goto(target_url, wait_until="networkidle", timeout=20000)

    # Step 5: Inject stored localStorage values (JWT etc.)
    if storage_state.get("origins"):
        for origin in storage_state["origins"]:
            if target_url in origin.get("origin", ""):
                for item in origin.get("localStorage", []):
                    try:
                        await page.evaluate(
                            f"localStorage.setItem({json.dumps(item['name'])}, {json.dumps(item['value'])})"
                        )
                    except Exception as ls_err:
                        logger.debug("[%s] localStorage inject failed (non-fatal): %s", run_id, ls_err)

    # Step 6: SPA barrier
    await _wait_for_post_login_spa_render(page, run_id)

    # Step 7: Verify JWT
    try:
        jwt_value = await page.evaluate(f"localStorage.getItem('{jwt_key}')")
    except Exception:
        jwt_value = None
    jwt_present = bool(jwt_value)

    duration_ms = int((time.monotonic() - t_start) * 1000)
    logger.info(
        "[%s] Persona switch to '%s': jwt_present=%s, duration=%dms",
        run_id, role_key, jwt_present, duration_ms,
    )

    return {"success": jwt_present, "jwt_present": jwt_present, "duration_ms": duration_ms}


async def _login_with_ephemeral_creds(
    page,
    email: str,
    password: str,
    target_url: str,
    run_id: str,
) -> dict:
    """
    Authenticate using operator-provided credentials (HITL path).

    Does NOT use ensure_role_authenticated() — these creds are not in the
    role registry. Does NOT save auth state to disk.

    Returns dict with success (bool), jwt_present (bool).
    """
    t_start = time.monotonic()

    try:
        _profile = get_active_profile() if callable(get_active_profile) else None
        jwt_key = (_profile.jwt_storage_key if _profile else None) or "vc2JWT"
    except Exception:
        jwt_key = "vc2JWT"

    # If the browser is already on a login page (redirect fired from the target
    # URL), trust that redirect and fill the current form. Only navigate to the
    # supplied target_url when we're not already on a login screen, and fall
    # back to the current URL if that navigation fails (e.g. DNS unresolvable
    # for a stale configured ghost_login_url).
    _current_url = page.url or ""
    _on_login_page = "/login" in _current_url.lower()
    if not _on_login_page and target_url:
        # `wait_until="domcontentloaded"` — networkidle never fires on Angular
        # dev-server URLs (localhost:4200) due to HMR WebSocket traffic. The
        # subsequent `email_locator.wait_for(state="visible")` already gates
        # on the login form being interactive.
        try:
            await page.goto(target_url, wait_until="domcontentloaded", timeout=20000)
        except Exception as goto_err:
            logger.warning(
                "[%s] HITL login: goto(%s) failed (%s) — filling current page instead",
                run_id, target_url, goto_err,
            )

    # Wait for the email field to be visible before filling — the redirect to
    # the login page may still be settling, and filling before the form is
    # interactive produces a fake-success in <300ms with no JWT.
    email_locator = page.get_by_role("textbox", name="Email")
    try:
        await email_locator.wait_for(state="visible", timeout=15000)
    except Exception as e:
        logger.error("[%s] HITL login: email input not visible after 15s: %s", run_id, e)
        return {"success": False, "jwt_present": False, "duration_ms": int((time.monotonic() - t_start) * 1000)}

    try:
        await email_locator.fill(email)
        await page.get_by_role("textbox", name="Password").fill(password)
    except Exception as fill_err:
        logger.error("[%s] HITL login form fill failed: %s", run_id, fill_err)
        return {"success": False, "jwt_present": False, "duration_ms": int((time.monotonic() - t_start) * 1000)}

    # Click login button — try both "Login" and "Log In" variants
    _clicked = False
    for _btn_name in ("Login", "Log In", "Sign In"):
        try:
            _btn = page.get_by_role("button", name=_btn_name)
            await _btn.wait_for(state="visible", timeout=3000)
            await _btn.click()
            _clicked = True
            break
        except Exception:
            continue
    if not _clicked:
        try:
            await page.locator("button[type='submit'], input[type='submit']").first.click()
        except Exception as click_err:
            logger.error("[%s] HITL login: submit button not clickable: %s", run_id, click_err)
            return {"success": False, "jwt_present": False, "duration_ms": int((time.monotonic() - t_start) * 1000)}

    # Wait for network activity to settle after the click — this is what the
    # main login_node does at graph.py:1035. Without it, the SPA barrier's
    # Tier 1 (router-outlet siblings) passes immediately because the login
    # page still has siblings, and JWT hasn't been set yet.
    #
    # Timeout is intentionally short (5s) because networkidle never fires on
    # Angular dev-server (localhost:4200) — HMR WebSocket keeps traffic
    # flowing. The JWT poll below is the real gate.
    try:
        await page.wait_for_load_state("networkidle", timeout=5000)
    except Exception:
        pass

    # Poll JWT for up to 5s — the JWT appears asynchronously after networkidle
    # in some setups. Matches the main login_node pattern at graph.py:1042.
    jwt_value = None
    for _ in range(10):
        try:
            jwt_value = await page.evaluate(f"localStorage.getItem('{jwt_key}')")
        except Exception:
            jwt_value = None
        if jwt_value:
            break
        try:
            await page.wait_for_timeout(500)
        except Exception:
            pass
    jwt_present = bool(jwt_value)

    # SPA barrier after JWT — Angular still needs a tick to render the
    # post-login route now that auth cookies are set.
    await _wait_for_post_login_spa_render(page, run_id)

    # SSO cross-domain fallback: on flows that hop from a product URL to a
    # shared login gateway (e.g. vpromotions-rc → two-test.vcreative.net),
    # the JWT is often carried by cookies rather than written to localStorage
    # on the gateway domain — so the JWT probe returns null even though auth
    # succeeded. If we've moved off any /login page, trust that as success.
    try:
        _url_raw_final = page.url
        _final_url = _url_raw_final.lower() if isinstance(_url_raw_final, str) else ""
    except Exception:
        _final_url = ""
    off_login_page = bool(_final_url) and "/login" not in _final_url
    login_success = jwt_present or off_login_page

    duration_ms = int((time.monotonic() - t_start) * 1000)
    logger.info(
        "[%s] HITL ephemeral login: jwt_present=%s, off_login_page=%s, url=%s, duration=%dms",
        run_id, jwt_present, off_login_page, _final_url or "?", duration_ms,
    )
    return {"success": login_success, "jwt_present": jwt_present, "duration_ms": duration_ms}


# ---------------------------------------------------------------------------
# WebSocket broadcast (lazy import to avoid circular dependency)
# ---------------------------------------------------------------------------


async def broadcast_ws_message(run_id: str, msg: dict) -> None:
    """
    Broadcast a JSON message to all WebSocket clients for a run.

    Uses lazy import of _broadcast_step from routes.py to avoid circular
    import (same pattern as other nodes that broadcast mid-execution).

    For PERSONA_SWITCH events we send raw JSON since WSStepMessage doesn't
    accommodate the HITL payload format. We use send_text directly.
    """
    try:
        from backend.api.routes import _ws_connections
        connections = _ws_connections.get(run_id, [])
        if not connections:
            return
        msg_json = json.dumps(msg)
        disconnected = []
        for ws in connections:
            try:
                await ws.send_text(msg_json)
            except Exception:
                disconnected.append(ws)
        for ws in disconnected:
            if ws in connections:
                connections.remove(ws)
    except (ImportError, Exception) as err:
        logger.debug("[%s] broadcast_ws_message failed (non-fatal): %s", run_id, err)


# ---------------------------------------------------------------------------
# Main node function
# ---------------------------------------------------------------------------


async def persona_switch_node(state: dict) -> dict:
    """
    LangGraph node: execute a persona switch when a PERSONA_SWITCH step is reached.

    Called by the graph when evaluator_node sets _next_node = "persona_switch".
    After execution, returns _next_node = "planner" to continue the test plan.

    State mutations:
      - current_persona: updated to the new role_key
      - persona_switch_history: one new entry appended (via operator.add)
      - _next_node: always "planner"

    Args
    ----
    state : dict
        Full VQAState dict.

    Returns
    -------
    dict
        Partial state update with current_persona, persona_switch_history,
        and _next_node.
    """
    run_id = state.get("run_id", "unknown")
    target_url = state.get("target_url", "")
    run_memory = state.get("run_memory", {})
    from_persona = state.get("current_persona", "")

    # ── 1. Extract target_persona from current structured step ────────────
    structured_step_index = state.get("structured_step_index", state.get("ac_step_index", 0))
    test_plan = state.get("test_plan") or {}

    # Handle TestPlan dict vs model
    if hasattr(test_plan, "steps"):
        steps = test_plan.steps
    else:
        steps = test_plan.get("steps", [])

    if structured_step_index >= len(steps):
        logger.error(
            "[%s] persona_switch_node: step index %d is out of range (total steps: %d) — skipping",
            run_id, structured_step_index, len(steps),
        )
        return {"_next_node": "planner"}

    current_step = steps[structured_step_index]

    # Support both dict and pydantic model
    if hasattr(current_step, "target_persona"):
        target_persona = current_step.target_persona or ""
    else:
        target_persona = (current_step.get("target_persona") or "").strip()

    if not target_persona:
        logger.warning(
            "[%s] PERSONA_SWITCH step at index %d has no target_persona — skipping switch",
            run_id, structured_step_index,
        )
        return {"_next_node": "planner"}

    logger.info("[%s] 🔄 PERSONA SWITCH: '%s' → '%s'", run_id, from_persona or "(none)", target_persona)

    # ── 2. Resolve role key ───────────────────────────────────────────────
    role_key, method = resolve_target_persona(target_persona, run_memory)

    # ── 3. Get browser context ────────────────────────────────────────────
    try:
        manager = get_manager(run_id)
        page = manager.page
        context = manager._context
    except Exception as ctx_err:
        logger.error("[%s] persona_switch_node: cannot get browser manager: %s", run_id, ctx_err)
        return {"_next_node": "planner", "last_error": f"PERSONA_SWITCH: browser manager unavailable: {ctx_err}"}

    t_start = time.monotonic()

    # ── 4. Execute auth switch ────────────────────────────────────────────
    if role_key and method in ("stored", "initial_actor"):
        # Happy path: known persona with stored credentials
        try:
            result = await _perform_auth_switch(page, context, role_key, target_url, run_id)
        except Exception as switch_err:
            logger.error("[%s] Auth switch to '%s' failed: %s", run_id, role_key, switch_err)
            result = {"success": False, "jwt_present": False, "duration_ms": 0}
    else:
        # Unknown persona → HITL credential gate
        logger.info("[%s] Persona '%s' not in registry — entering HITL credential gate", run_id, target_persona)
        try:
            creds = await _wait_for_persona_credentials(run_id, target_persona)
            result = await _login_with_ephemeral_creds(
                page, creds["email"], creds["password"], target_url, run_id
            )
        except Exception as hitl_err:
            logger.error("[%s] HITL persona gate failed: %s", run_id, hitl_err)
            result = {"success": False, "jwt_present": False, "duration_ms": 0}

        role_key = target_persona  # Use raw name as role_key for tracking
        method = "hitl"

        # Store ephemerally for potential re-use within this run
        # (already stored by set_persona_credentials — just ensure it's there)
        if run_id not in _persona_creds:
            _persona_creds[run_id] = {}

    # ── 5. Build switch history entry ─────────────────────────────────────
    duration_ms = int((time.monotonic() - t_start) * 1000)
    switch_entry = {
        "from": from_persona,
        "to": role_key or target_persona,
        "persona_name": target_persona,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "method": method or "hitl",
        "duration_ms": duration_ms,
        "jwt_verified": result.get("jwt_present", False),
    }

    logger.info(
        "[%s] ✓ Persona switch complete: '%s' → '%s' (%s, %dms, jwt=%s)",
        run_id,
        from_persona or "(none)",
        role_key or target_persona,
        method or "hitl",
        duration_ms,
        result.get("jwt_present", False),
    )

    # ── 6. Broadcast completion event ─────────────────────────────────────
    try:
        await broadcast_ws_message(run_id, {
            "type": "PERSONA_SWITCH_COMPLETE",
            "from": from_persona,
            "to": role_key or target_persona,
            "method": method or "hitl",
            "duration_ms": duration_ms,
            "jwt_verified": result.get("jwt_present", False),
        })
    except Exception as ws_err:
        logger.debug("[%s] PERSONA_SWITCH_COMPLETE broadcast failed (non-fatal): %s", run_id, ws_err)

    # ── 7. Return state mutations ─────────────────────────────────────────
    # Advance ac_step_index so planner works on the NEXT step after the switch.
    # This mirrors switch_actor_mid_run_node which also advances the index itself.
    new_index = structured_step_index + 1
    return {
        "current_persona": role_key or target_persona,
        "persona_switch_history": [switch_entry],  # Appended via operator.add reducer
        "ac_step_index": new_index,
        "structured_step_index": new_index,  # FEAT-025
        "_next_node": "planner",
    }
