"""
vQA — LangGraph StateGraph Wiring
====================================
Module: backend/engine/graph.py

This module assembles the complete LangGraph StateGraph by registering
all nodes and wiring the edges (including conditional routing from the
evaluator).

Graph Topology
--------------
::

    START
      │
      ▼
    jira_fetch ──► ac_parser ──► setup_role ──► login
                                      ▲              │
                                      │              ▼
                                      │        ┌─ planner ◄─┐
                                      │        │             │
                                      │        ▼             │
                                      │    executor          │
                                      │        │             │
                                      │        ▼             │
                          [more roles]│    evaluator ────────┘
                                      │        │    (retry / next AC)
                                      │        │
                                      └────────┤ [all AC done, more roles]
                                               │
                                               ▼ [fully done or fatal]
                                           reporter ──► END

Node Registry
-------------
    ┌──────────────┬─────────────────────┬──────────────────────────────────┐
    │ Node Name    │ Module              │ Purpose                          │
    ├──────────────┼─────────────────────┼──────────────────────────────────┤
    │ jira_fetch   │ (inline)            │ Fetch Jira ticket fields         │
    │ ac_parser    │ (inline)            │ Parse AC into discrete steps     │
    │ setup_role   │ (inline)            │ Load role credentials + perms    │
    │ login        │ (inline)            │ Playwright login + JWT verify    │
    │ planner      │ planner.py          │ Screenshot + a11y → LLM → action│
    │ executor     │ executor.py         │ Dispatch action via Playwright   │
    │ evaluator    │ evaluator.py        │ Judge result + decide routing    │
    │ verifier     │ verifier.py         │ LLM-as-judge step completion     │
    │ human_tkover │ human_takeover.py   │ Pause for human intervention     │
    │ reporter     │ reporter.py         │ Generate + upload audit report   │
    └──────────────┴─────────────────────┴──────────────────────────────────┘

Edge Rules
----------
All edges are sequential except the evaluator, which uses a conditional
edge to route between planner (retry/next step), setup_role (next role),
and reporter (done/fatal).

Usage
-----
    from backend.engine.graph import build_graph

    graph = build_graph()
    result = await graph.ainvoke(initial_state)

Dependencies
------------
  - ``langgraph``                     — StateGraph, END
  - ``backend/engine/planner.py``     — planner_node
  - ``backend/engine/executor.py``    — executor_node
  - ``backend/engine/evaluator.py``   — evaluator_node, route_after_evaluator
  - ``backend/engine/reporter.py``    — reporter_node
  - ``backend/engine/roles.py``       — get_role_context
  - ``backend/jira/client.py``        — fetch_ticket_context
  - ``backend/browser/context.py``    — BrowserManager
  - ``backend/config.py``             — settings

See Also
--------
  - ``backend/engine/state.py``    — VQAState definition
  - ``backend/api/routes.py``      — calls ``build_graph().ainvoke()``
"""

import logging
from typing import Any

from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from backend.browser.context import BrowserManager, get_manager, register_manager
from backend.engine.ac_parser import ac_parser_node
from backend.engine.critic_node import critic_node, route_after_critic  # critic-pass-llm-evaluator
from backend.engine.evaluator import evaluator_node, route_after_evaluator
from backend.engine.executor import executor_node
from backend.engine.ghost_login_node import ghost_login_node  # TASK-102: ghost login admin impersonation
from backend.engine.human_takeover import human_takeover_node
from backend.engine.persona_switch_node import persona_switch_node  # TASK-063: mid-test persona auth switch
from backend.engine.planner import planner_node
from backend.engine.playwright_executor import playwright_executor_node
from backend.engine.reporter import reporter_node
from backend.engine.roles import get_role_context, resolve_role_by_name
from backend.engine.state import VQAState
from backend.engine.state_tracker import create_tracker as _create_state_tracker
from backend.engine.verifier import route_after_verifier, step_verifier_node

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Inline node functions
# ---------------------------------------------------------------------------
# These nodes are simple enough to define inline rather than in separate
# modules.  They handle setup/teardown steps that don't warrant their own
# file.


async def jira_fetch_node(state: VQAState) -> dict:
    """
    Fetch Jira ticket data and populate the state.
    Runs the JiraACNegotiator to enforce quality gates and negotiation.

    Bug F fix: Check the in-memory JiraCache before hitting the Jira API.
    If a /preview-steps call already fetched this ticket within the last
    60 seconds, the cache returns the stored data immediately (HIT path).
    This eliminates the redundant double-fetch that occurred when a user
    previewed steps then immediately started a run for the same ticket.
    """
    ticket_id: str = state["jira_ticket"]["ticket_id"].strip().upper()
    run_id: str = state["run_id"]
    logger.info("[%s] Fetching Jira ticket: %s", run_id, ticket_id)

    # Bug F: Check cache before calling the Jira API
    from backend.config import settings
    from backend.jira.cache import get_jira_cache

    _jira_cache = get_jira_cache()
    cached_ticket = await _jira_cache.get(ticket_id, domain=settings.jira_domain)
    if cached_ticket is not None:
        logger.info(
            "[%s] jira_fetch_node: cache HIT for %s — skipping Jira API call",
            run_id,
            ticket_id,
        )
        return {"jira_ticket": cached_ticket}

    from backend.jira.negotiator import JiraACNegotiator

    is_preview = state.get("is_preview", False)
    negotiator = JiraACNegotiator(ticket_id, run_id, dry_run=is_preview)

    ticket_context, quality_result = await negotiator.fetch_and_gate_ac()

    if not ticket_context:
        return {"error": "Failed to fetch ticket context."}

    if quality_result and quality_result.quality_grade == "poor":
        pending = "\n\n---\n\n".join(negotiator.pending_comments) if negotiator.pending_comments else None
        return {
            "jira_ticket": ticket_context,
            "parse_quality": "rejected",
            "parse_quality_reason": "AC rejected by JiraACNegotiator quality gate.",
            "pending_jira_comment": pending,
        }

    # Propose test plan back to Jira for auto-sync and feedback
    if quality_result:
        try:
            await negotiator.propose_test_plan(ticket_context, quality_result)
        except Exception as e:
            logger.warning("[%s] Failed to propose test plan: %s", run_id, e)

    logger.info(
        "[%s] Jira fetch & negotiation complete: summary='%s', AC=%d chars",
        run_id,
        ticket_context.get("summary", "")[:60],
        len(ticket_context.get("acceptance_criteria", "")),
    )

    # Bug F: Store in cache for subsequent calls within the TTL window
    await _jira_cache.set(ticket_id, ticket_context)

    pending = "\n\n---\n\n".join(negotiator.pending_comments) if negotiator.pending_comments else None
    return {"jira_ticket": ticket_context, "pending_jira_comment": pending}


async def test_source_node(state: VQAState) -> dict:
    """
    Fetch acceptance criteria from the configured test source.

    Delegates to the appropriate ``TestSourceAdapter`` based on the
    ``source_type`` field in state.  Supports ``"jira"`` (default),
    ``"raw_text"``, ``"github"``, and ``"auto"`` (auto-detect from identifier).

    For Jira sources, this calls the existing ``fetch_ticket_context``
    path.  For raw text, it wraps the ``raw_ac_text`` field directly.

    Args
    ----
    state : VQAState
        Must contain ``source_type`` and either ``jira_ticket.ticket_id``
        (for Jira) or ``raw_ac_text`` (for raw text).

    Returns
    -------
    dict
        Partial state update: ``jira_ticket`` populated with
        adapter-sourced data (even for non-Jira sources, the
        ``jira_ticket`` dict is reused for state compatibility).
    """
    source_type = state.get("source_type", "jira")
    run_id = state["run_id"]

    # ── Phase 5E: Auto-detect source type from identifier ──────────────
    if source_type == "auto":
        from backend.adapters.adapter_factory import detect_source_type

        identifier = state.get("raw_ac_text", "") or state.get("jira_ticket", {}).get("ticket_id", "")
        source_type = detect_source_type(identifier)
        logger.info(
            "[%s] Auto-detected source type: %s (from: %s)",
            run_id,
            source_type,
            identifier[:50],
        )

    # Fast path: Jira (most common) — delegate to existing client
    if source_type == "jira":
        return await jira_fetch_node(state)

    # Adapter path: raw_text or github
    try:
        from backend.adapters import get_adapter

        adapter = get_adapter(source_type)

        if source_type == "raw_text":
            identifier = state.get("raw_ac_text", "")
        else:
            identifier = state.get("jira_ticket", {}).get("ticket_id", "")

        result = await adapter.fetch_ac(identifier)

        logger.info(
            "[%s] Test source (%s) fetch complete: id=%s, AC=%d chars",
            run_id,
            source_type,
            result.ticket_id,
            len(result.acceptance_criteria),
        )

        # Map ACResult → jira_ticket dict for state compatibility
        return {
            "jira_ticket": {
                "ticket_id": result.ticket_id,
                "summary": result.summary,
                "description": result.description,
                "acceptance_criteria": result.acceptance_criteria,
                "source_type": result.source_type,
                **result.raw_metadata,
            }
        }

    except Exception as exc:
        logger.error(
            "[%s] Test source (%s) fetch failed: %s — falling back to Jira",
            run_id,
            source_type,
            exc,
        )
        # Fallback to Jira if adapter fails
        return await jira_fetch_node(state)


# ---------------------------------------------------------------------------
# ac_parser_node — MOVED to backend/engine/ac_parser.py
# ---------------------------------------------------------------------------
# The structured two-stage AC parser (BDD normalizer → JSON compiler) is
# now in its own module.  It's imported at the top of this file:
#     from backend.engine.ac_parser import ac_parser_node
#
# The new parser dual-writes:
#   - test_plan (structured TestPlan dict with typed steps + assertions)
#   - acceptance_criteria_steps (legacy string list for backward compat)
# ---------------------------------------------------------------------------


async def _assert_angular_ready(page, run_id: str, target_url: str) -> None:
    """
    Assert that the Angular application has hydrated and the page is on the
    expected environment BEFORE the agent begins planning.

    REC 1 — Phase 0 health-check from Antigravity workflow.

    Two assertions are made:
      1. Angular app root visible — proves Angular has bootstrapped and
         injected the component tree (not just an empty HTML shell).
      2. Environment identity — if ``settings.expected_env_substring`` is
         set, the current URL must contain that substring. Prevents silent
         failures from running against the wrong deployment branch.

    Failures are logged as warnings (not exceptions) so a transient slow
    load or misconfigured setting doesn't abort the entire run.

    Args
    ----
    page : playwright.async_api.Page
        Live Playwright page after navigation.
    run_id : str
        Active run ID for log correlation.
    target_url : str
        The URL that was navigated to (used in error messages).
    """
    # ── 1. App root visibility (hydration proof) ────────────────────────────
    # MIGRATION: selectors now sourced from the active AppProfile.
    try:
        from backend.profiles import get_active_profile

        _APP_ROOT_SELECTORS = get_active_profile().app_root_selectors
    except Exception:
        # Fallback: hardcoded vSuite selectors (backward compat)
        _APP_ROOT_SELECTORS = [
            "app-root",
            "vp-root",
            "[ng-version]",
            "router-outlet",
        ]
    hydrated = False
    for sel in _APP_ROOT_SELECTORS:
        try:
            await page.locator(sel).first.wait_for(state="visible", timeout=8000)
            logger.info(
                "[%s] ✓ App hydration confirmed: '%s' is visible",
                run_id,
                sel,
            )
            hydrated = True
            break
        except Exception:
            continue

    if not hydrated:
        logger.warning(
            "[%s] ⚠ App hydration check: no app root found in DOM within 8s "
            "(selectors tried: %s). The page may not have bootstrapped — "
            "proceeding anyway but the agent may encounter empty content.",
            run_id,
            _APP_ROOT_SELECTORS,
        )

    # ── 2. Environment identity check ──────────────────────────────────────
    try:
        from backend.config import settings as _settings

        expected_env = getattr(_settings, "expected_env_substring", "") or ""
    except Exception:
        expected_env = ""

    if expected_env:
        current_url = page.url
        if expected_env.lower() not in current_url.lower():
            logger.error(
                "[%s] ⛔ ENVIRONMENT MISMATCH: URL '%s' does not contain '%s'. "
                "Are you pointing at the correct environment? "
                "Check settings.expected_env_substring and target_url.",
                run_id,
                current_url[:120],
                expected_env,
            )
        else:
            logger.info(
                "[%s] ✓ Environment identity confirmed: '%s' in URL",
                run_id,
                expected_env,
            )


async def _wait_for_post_login_spa_render(page, run_id: str) -> None:
    """
    FIX 3 — Deterministic SPA Synchronization Barrier.

    Wait for the Angular SPA to finish hydrating the post-login route before
    the planner takes its first screenshot. Without this, the planner captures
    a mid-redirect DOM with 3-10 elements and hallucinates being on the login
    page, generating actions like ``fill email`` on a dashboard that hasn't
    rendered yet.

    Called from login_node in all three exit paths:
      1. ``has_complete_creds`` path (page.goto + _assert_angular_ready)
      2. ``jwt_early`` path (JWT already in localStorage before login form)
      3. Full form-login path (after 5 s JWT polling)

    Three-tier gate (first passing tier wins, then returns immediately):

    **Tier 1 — Router hydration** (up to 8 s):
      Poll for ``router-outlet`` adjacent siblings > 0. Angular inserts routed
      components as *siblings after* the outlet element, not children inside it.
      Presence of siblings proves Angular has completed the route transition.

    **Tier 2 — Interactive density** (up to 5 s):
      Poll until the DOM has more than 5 enabled interactive elements
      (buttons, links, non-disabled inputs, role=button). An authenticated
      dashboard always has navigation items, action buttons, etc.
      An empty login shell or redirect limbo will have <= 2.

    **Tier 3 — Bounded fallback** (2 s):
      If both tiers time out, wait exactly 2 s and proceed. This is still
      deterministic (bounded) unlike naked ``asyncio.sleep`` calls and
      prevents the pipeline from hanging indefinitely.

    Args
    ----
    page : playwright.async_api.Page
        The Playwright page to interrogate.
    run_id : str
        Run identifier for structured log correlation.
    """
    # Tier 1: router-outlet rendered siblings — Angular has finished navigation
    try:
        await page.wait_for_function(
            """
            () => {
                const outlet = document.querySelector('router-outlet');
                if (!outlet) return false;
                // Angular renders routed components as sibling elements AFTER
                // the router-outlet, not as children inside it.
                let sibling = outlet.nextElementSibling;
                let count = 0;
                while (sibling) {
                    count++;
                    sibling = sibling.nextElementSibling;
                }
                return count >= 1;
            }
            """,
            timeout=8000,
        )
        logger.info("[%s] ✓ SPA barrier Tier1: router-outlet siblings rendered", run_id)
        return
    except Exception:
        logger.debug("[%s] SPA barrier Tier1 timed out (router-outlet siblings)", run_id)

    # Tier 2: interactive element density
    try:
        await page.wait_for_function(
            """
            () => {
                const els = document.querySelectorAll(
                    'button:not([disabled]), a[href], input:not([disabled]), [role="button"]'
                );
                return els.length > 5;
            }
            """,
            timeout=5000,
        )
        try:
            count = await page.evaluate(
                "document.querySelectorAll('button:not([disabled]), a[href], input:not([disabled])').length"
            )
        except Exception:
            count = "?"
        logger.info(
            "[%s] ✓ SPA barrier Tier2: %s interactive elements detected",
            run_id,
            count,
        )
        return
    except Exception:
        logger.debug("[%s] SPA barrier Tier2 timed out (interactive element count)", run_id)

    # Tier 3: bounded fallback
    logger.warning(
        "[%s] ⚠ SPA barrier: both tiers timed out — waiting 2 s as bounded fallback. "
        "The planner may encounter a partially rendered page on the first snapshot.",
        run_id,
    )
    try:
        await page.wait_for_timeout(2000)
    except Exception:
        pass


async def setup_role_node(state: VQAState) -> dict:
    """
    Load role credentials and permissions from the registry.

    Pops the next role from ``role_queue`` and loads its
    ``RoleContext`` from ``backend/engine/roles.py``.

    Args
    ----
    state : VQAState
        Must contain a non-empty ``role_queue``.

    Returns
    -------
    dict
        Partial state update: ``role_context`` with full credentials
        and permissions, ``role_queue`` with the front role consumed.
    """
    run_id: str = state["run_id"]
    queue: list[str] = list(state.get("role_queue", []))

    if not queue:
        logger.error("[%s] setup_role called with empty role_queue", run_id)
        return {}

    role_key: str = queue[0]
    remaining_queue: list[str] = queue[1:]

    logger.info(
        "[%s] Setting up role: %s (%d remaining in queue)",
        run_id,
        role_key,
        len(remaining_queue),
    )

    # Load role context from the registry
    role_context = dict(get_role_context(role_key))

    # ── Dynamic persona resolution ────────────────────────────────────
    # For multi-role integration tests, the AC step text may say:
    #   "Login as the assigned voicer"  → check run_memory.dynamic_actors
    #   "Login as the original creator" → check run_memory.initial_actor
    #
    # We inspect the current AC step text to decide whether to override
    # the role credentials with a dynamically tracked actor.
    run_memory = state.get("run_memory", {})
    ac_steps = state.get("jira_ticket", {}).get("acceptance_criteria_steps", [])
    ac_index = state.get("ac_step_index", 0)
    current_step_text = ac_steps[ac_index].lower() if ac_index < len(ac_steps) else ""

    # Check for "original submitter / creator" references
    INITIAL_ACTOR_KEYWORDS = [
        "original user",
        "original creator",
        "original submitter",
        "order submitter",
        "initial user",
        "who started",
        "who created",
        "first user",
    ]
    if any(kw in current_step_text for kw in INITIAL_ACTOR_KEYWORDS):
        initial_actor = run_memory.get("initial_actor", {})
        if initial_actor.get("email"):
            logger.info(
                "[%s] Persona resolution: step references initial actor → %s",
                run_id,
                initial_actor["email"][:30],
            )
            role_context["login_email"] = initial_actor["email"]

    # Check for dynamically assigned actor references
    DYNAMIC_ACTOR_KEYWORDS = {
        "voicer": ["assigned voicer", "the voicer", "voice talent", "assigned voice"],
        "editor": ["assigned editor", "the editor"],
        "producer": ["assigned producer", "the producer"],
        "mixer": ["assigned mixer", "the mixer"],
    }
    dynamic_actors = run_memory.get("dynamic_actors", {})
    for actor_role, keywords in DYNAMIC_ACTOR_KEYWORDS.items():
        if any(kw in current_step_text for kw in keywords):
            actor_name = dynamic_actors.get(actor_role, "")
            if actor_name:
                resolved = resolve_role_by_name(actor_name)
                if resolved:
                    logger.info(
                        "[%s] Persona resolution: '%s' → role '%s' (%s)",
                        run_id,
                        actor_name,
                        resolved["role_key"],
                        resolved["login_email"][:30],
                    )
                    role_context["login_email"] = resolved["login_email"]
                    role_context["login_password"] = resolved["login_password"]
                    role_context["role_name"] = resolved["role_name"]
                else:
                    logger.warning(
                        "[%s] Persona resolution: '%s' not found in role registry",
                        run_id,
                        actor_name,
                    )
            break

    # ── Credential priority chain ─────────────────────────────────────────
    # 1. injected_login_* (user supplied at execute-time, highest priority)
    # 2. jira_ticket.override_login_* (extracted from ticket description)
    # 3. role KB / env var / hardcoded fallback (lowest priority)
    injected_email = state.get("injected_login_email", "")
    injected_password = state.get("injected_login_password", "")
    ticket_email = state.get("jira_ticket", {}).get("override_login_email", "")
    ticket_password = state.get("jira_ticket", {}).get("override_login_password", "")
    credential_status = state.get("jira_ticket", {}).get("credential_status", "none")

    # Resolve final email and password
    final_email = injected_email or ticket_email or ""
    final_password = injected_password or ticket_password or ""

    if final_email or final_password:
        source = "injected" if injected_email else "ticket"
        logger.info(
            "[%s] Credential override (%s) — email: %s, credential_status: %s",
            run_id,
            source,
            final_email,
            credential_status,
        )
        if final_email:
            role_context["login_email"] = final_email
        if final_password:
            role_context["login_password"] = final_password
    else:
        logger.info(
            "[%s] No credential override — using role KB credentials",
            run_id,
        )

    logger.info(
        "[%s] Role '%s' loaded: email=%s, %d constraints",
        run_id,
        role_context["role_name"],
        role_context["login_email"][:25] + "...",
        len(role_context.get("constraints", [])),
    )

    return {
        "role_context": role_context,
        "role_queue": remaining_queue,
    }


async def login_node(state: VQAState) -> dict:
    """
    Launch the browser, navigate to the target URL, and log in.

    This node:
    1. Creates a new ``BrowserManager`` (or reuses if switching roles)
    2. Navigates to the login page
    3. Fills in the email and password
    4. Clicks the login button
    5. Waits for navigation to complete
    6. Verifies the JWT token is present in localStorage

    Args
    ----
    state : VQAState
        Must contain ``target_url``, ``role_context`` with credentials.

    Returns
    -------
    dict
        Partial state update:
        - ``browser_session_active``: True
        - ``current_page_url``: post-login URL
    """
    run_id: str = state["run_id"]
    target_url: str = state["target_url"]
    role_name: str = state["role_context"]["role_name"]

    # ── Ghost login: skip role pre-login ──────────────────────────────
    # When the test plan contains a GHOST_LOGIN step, the ghost_login_node
    # handles all authentication using admin credentials. The selected role's
    # credentials are irrelevant for the initial login — just navigate to
    # the target URL and let the AC steps drive from there.
    _test_plan = state.get("test_plan") or {}
    _plan_steps = (
        list(_test_plan.steps)
        if hasattr(_test_plan, "steps")
        else (_test_plan.get("steps") or [])
    )
    _override_steps = state.get("override_ac_steps") or []
    _steps_to_check = _plan_steps or _override_steps
    _has_ghost_login = any(
        (
            s.get("step_type") == "GHOST_LOGIN"
            if isinstance(s, dict)
            else getattr(s, "step_type", "") == "GHOST_LOGIN"
        )
        for s in _steps_to_check
    )
    if _has_ghost_login:
        logger.info(
            "[%s] GHOST_LOGIN step in test plan — skipping role pre-login, "
            "navigating to target URL. ghost_login_node will authenticate as admin.",
            run_id,
        )
        manager = BrowserManager(run_id=run_id)
        page = await manager.start()
        register_manager(run_id, manager)
        _create_state_tracker(run_id)
        await page.goto(target_url, wait_until="networkidle", timeout=30000)

        # Products like vPromotions live on a separate subdomain from the shared
        # vSuite SSO site. Navigating directly to the product URL redirects to the
        # vSuite login page when no session exists. When this happens, pre-authenticate
        # as admin using the ghost credentials so the planner can reach the product
        # page before ghost_login_node handles impersonation.
        if "/login" in page.url:
            try:
                from backend.engine.persona_switch_node import (
                    _ghost_creds as _gc_pre,
                    _login_with_ephemeral_creds as _pre_login,
                )
                from backend.engine.ghost_login_node import _resolve_ghost_login_url
                _pre_creds = _gc_pre.get(run_id, {})
                if _pre_creds.get("email") and _pre_creds.get("password"):
                    _ghost_auth_url = _resolve_ghost_login_url(target_url)
                    logger.info(
                        "[%s] Ghost login pre-auth: target redirected to login — "
                        "authenticating as admin at %s (email=%s)",
                        run_id,
                        _ghost_auth_url,
                        _pre_creds["email"][:30],
                    )
                    await _pre_login(
                        page, _pre_creds["email"], _pre_creds["password"], _ghost_auth_url, run_id
                    )
                    # Navigate to product URL when ghost login was on a different host
                    from urllib.parse import urlparse as _urlparse_pre
                    if _urlparse_pre(page.url).netloc != _urlparse_pre(target_url).netloc:
                        await page.goto(target_url, wait_until="networkidle", timeout=30000)
                        await _wait_for_post_login_spa_render(page, run_id)
            except Exception as _pre_auth_err:
                logger.warning(
                    "[%s] Ghost login pre-auth failed (non-fatal): %s",
                    run_id,
                    _pre_auth_err,
                )

        return {
            "browser_session_active": True,
            "current_page_url": page.url,
        }

    # ── Failed login testing: skip authentication ──────────────────────
    # When expect_login_failure=True, we navigate to the login page but
    # do NOT fill credentials or click Login.  The browser is left on the
    # blank login form so the AC steps can drive the login attempt with
    # intentionally wrong credentials and verify failure indicators.
    if state.get("expect_login_failure", False):
        logger.info(
            "[%s] expect_login_failure=True — navigating to login page "
            "WITHOUT authenticating. AC steps will drive the login attempt.",
            run_id,
        )
        manager = BrowserManager(run_id=run_id)
        page = await manager.start()
        register_manager(run_id, manager)
        _create_state_tracker(run_id)

        await page.goto(target_url, wait_until="networkidle", timeout=30000)

        # Verify we're on the login page (email input visible)
        try:
            email_input = page.get_by_role("textbox", name="Email")
            await email_input.wait_for(state="visible", timeout=10000)
            logger.info("[%s] ✓ Login page confirmed — email input visible", run_id)
        except Exception:
            logger.warning(
                "[%s] ⚠ Login page email input not found — page may have auto-redirected. Proceeding anyway.",
                run_id,
            )

        return {
            "browser_session_active": True,
            "current_page_url": page.url,
        }

    # ── Skip pre-login if ticket has COMPLETE credentials ──────────────
    # "complete" = both email + password found in ticket (or injected by user)
    # The AC steps will navigate to the page and handle the login form.
    credential_status = state.get("jira_ticket", {}).get("credential_status", "none")
    injected_email = state.get("injected_login_email", "")
    injected_password = state.get("injected_login_password", "")

    # A credential set is "complete" if the ticket status says so,
    # OR if both injected credentials were provided.
    has_complete_creds = credential_status == "complete" or (bool(injected_email) and bool(injected_password))

    if has_complete_creds:
        effective_email = injected_email or state.get("jira_ticket", {}).get("override_login_email", "")
        logger.info(
            "[%s] Complete credentials in ticket/injected (%s) — "
            "skipping pre-login, navigating to URL and letting AC steps handle auth.",
            run_id,
            effective_email,
        )
        manager = BrowserManager(run_id=run_id)
        page = await manager.start()
        register_manager(run_id, manager)
        _create_state_tracker(run_id)  # Phase 1: per-run deterministic state tracker
        await page.goto(target_url, wait_until="networkidle", timeout=30000)
        await _assert_angular_ready(page, run_id, target_url)  # REC 1
        await _wait_for_post_login_spa_render(page, run_id)  # Fix 3: SPA barrier

        # Track initial actor for persona resolution
        run_memory_update = {}
        existing_memory = state.get("run_memory", {})
        if not existing_memory.get("initial_actor"):
            run_memory_update = {
                "initial_actor": {
                    "email": state["role_context"].get("login_email", effective_email),
                    "role_key": state["role_context"].get("role_key", ""),
                    "role_name": state["role_context"].get("role_name", ""),
                }
            }
            logger.info(
                "[%s] Tracked initial actor: %s (%s)",
                run_id,
                state["role_context"].get("role_name", "?"),
                effective_email[:30],
            )

        return {
            "browser_session_active": True,
            "current_page_url": page.url,
            "run_memory": run_memory_update,
        }

    # ── No complete credentials — pre-login with role credentials ─────
    # Prefer ghost credentials supplied via the pre-run credential panel over
    # the role's stored credentials. This covers products like vPromotions where
    # direct password login requires user-provided credentials.
    email: str = state["role_context"]["login_email"]
    password: str = state["role_context"]["login_password"]
    try:
        from backend.engine.persona_switch_node import _ghost_creds as _g_creds
        _run_ghost = _g_creds.get(run_id, {})
        if _run_ghost.get("email") and _run_ghost.get("password"):
            email = _run_ghost["email"]
            password = _run_ghost["password"]
            logger.info(
                "[%s] Using user-provided ghost credentials for direct login (email=%s)",
                run_id,
                email[:30],
            )
    except Exception:
        pass

    logger.info("[%s] Pre-logging in as %s to %s", run_id, role_name, target_url)

    # ── Step 1: Launch browser ────────────────────────────────────────
    manager = BrowserManager(run_id=run_id)
    page = await manager.start()
    register_manager(run_id, manager)
    _create_state_tracker(run_id)  # Phase 1: per-run deterministic state tracker

    # ── Step 2: Navigate to target ────────────────────────────────────
    logger.info("[%s] Navigating to %s", run_id, target_url)
    await page.goto(target_url, wait_until="networkidle", timeout=30000)
    await _assert_angular_ready(page, run_id, target_url)  # REC 1

    # ── Step 3: JWT check BEFORE looking for login form ───────────────
    # MIGRATION: JWT key now sourced from the active AppProfile.
    try:
        from backend.profiles import get_active_profile as _gap_login

        _login_profile = _gap_login()
    except Exception:
        _login_profile = None

    _jwt_key = _login_profile.jwt_storage_key if _login_profile else "vc2JWT"

    if _jwt_key:
        jwt_early = await page.evaluate(f"localStorage.getItem('{_jwt_key}')")
    else:
        jwt_early = None  # Profile says skip JWT check
    if jwt_early:
        logger.info(
            "[%s] ✓ JWT already present in localStorage — skipping login form (role: %s)",
            run_id,
            role_name,
        )

        # Track initial actor for persona resolution
        run_memory_update = {}
        existing_memory = state.get("run_memory", {})
        if not existing_memory.get("initial_actor"):
            run_memory_update = {
                "initial_actor": {
                    "email": email,
                    "role_key": state["role_context"].get("role_key", ""),
                    "role_name": role_name,
                }
            }
            logger.info("[%s] Tracked initial actor: %s (%s)", run_id, role_name, email[:30])

        # Fix 3: SPA barrier — wait for Angular to render the authenticated view
        await _wait_for_post_login_spa_render(page, run_id)

        # Double check: did the page redirect to login or show the login form?
        # If so, the restored JWT was expired/invalid on the server!
        is_login_page = "/login" in page.url.lower() or "login" in page.url.lower()
        if not is_login_page:
            try:
                # Short check for visible email input
                is_login_page = await page.get_by_role("textbox", name="Email").is_visible()
            except Exception:
                pass

        if is_login_page:
            logger.warning(
                "[%s] ⚠ Restored session is invalid/expired (page is on %s). "
                "Invalidating cached state and performing fresh login form submission.",
                run_id,
                page.url,
            )
            # Invalidate cached state
            try:
                from backend.engine.auth_manager import invalidate_role_state
                invalidate_role_state(role_name)
            except Exception as inv_err:
                logger.warning("[%s] Failed to invalidate role state: %s", run_id, inv_err)

            # Since we are on the login page now, we fall through to the clean login form submission below!
        else:
            return {
                "browser_session_active": True,
                "current_page_url": page.url,
                "run_memory": run_memory_update,
            }

    # ── Step 4: Wait for login form to appear ─────────────────────────
    # MIGRATION: Login form selectors now sourced from the active AppProfile.
    _login_selectors = _login_profile.login_form_selectors if _login_profile else None

    email_input = None
    if _login_selectors and _login_selectors.email_input:
        for locator_step in _login_selectors.email_input:
            try:
                if locator_step.method == "get_by_role":
                    candidate = page.get_by_role(*locator_step.args, **locator_step.kwargs)
                elif locator_step.method == "get_by_placeholder":
                    candidate = page.get_by_placeholder(*locator_step.args)
                elif locator_step.method == "get_by_label":
                    candidate = page.get_by_label(*locator_step.args)
                elif locator_step.method == "css_selector":
                    candidate = page.locator(*locator_step.args)
                else:
                    continue
                await candidate.wait_for(state="visible", timeout=8000)
                email_input = candidate
                break
            except Exception:
                continue

    if email_input is None:
        # Fallback: hardcoded vSuite selectors (backward compat)
        try:
            email_input = page.get_by_role("textbox", name="Email")
            await email_input.wait_for(state="visible", timeout=15000)
        except Exception:
            try:
                email_input = page.get_by_placeholder("Email")
                await email_input.wait_for(state="visible", timeout=5000)
            except Exception:
                raise RuntimeError(f"[{run_id}] Cannot find login form and no JWT present")

    # ── Step 4: Fill credentials ──────────────────────────────────────
    await email_input.fill(email)
    logger.debug("[%s] Filled email: %s", run_id, email[:20] + "...")

    # Find and fill password (using profile selectors with fallback)
    password_input = None
    if _login_selectors and _login_selectors.password_input:
        for locator_step in _login_selectors.password_input:
            try:
                if locator_step.method == "get_by_role":
                    candidate = page.get_by_role(*locator_step.args, **locator_step.kwargs)
                elif locator_step.method == "get_by_placeholder":
                    candidate = page.get_by_placeholder(*locator_step.args)
                elif locator_step.method == "get_by_label":
                    candidate = page.get_by_label(*locator_step.args)
                elif locator_step.method == "css_selector":
                    candidate = page.locator(*locator_step.args)
                else:
                    continue
                await candidate.wait_for(state="visible", timeout=5000)
                password_input = candidate
                break
            except Exception:
                continue

    if password_input is None:
        # Fallback: hardcoded vSuite selectors (backward compat)
        password_input = page.get_by_role("textbox", name="Password")
        try:
            await password_input.wait_for(state="visible", timeout=5000)
        except Exception:
            password_input = page.get_by_placeholder("Password")
            await password_input.wait_for(state="visible", timeout=5000)

    await password_input.fill(password)
    logger.debug("[%s] Filled password", run_id)

    # ── Step 5: Click login button ────────────────────────────────────
    # MIGRATION: Login button selectors from the active AppProfile.
    _btn_candidates = []
    if _login_selectors and _login_selectors.submit_button:
        for locator_step in _login_selectors.submit_button:
            if locator_step.method == "get_by_role":
                _btn_candidates.append(page.get_by_role(*locator_step.args, **locator_step.kwargs))
            elif locator_step.method == "css_selector":
                _btn_candidates.append(page.locator(*locator_step.args).first)
            elif locator_step.method == "get_by_text":
                _btn_candidates.append(page.get_by_text(*locator_step.args))
    else:
        # Fallback: hardcoded vSuite button candidates (backward compat)
        _btn_candidates = [
            page.get_by_role("button", name="Log In"),
            page.get_by_role("button", name="Login"),
            page.get_by_role("button", name="Sign In"),
            page.locator("button[type='submit'], input[type='submit']").first,
        ]
    login_button = None
    for candidate in _btn_candidates:
        try:
            await candidate.wait_for(state="visible", timeout=4000)
            login_button = candidate
            logger.info("[%s] Login button found: %r", run_id, await candidate.inner_text())
            break
        except Exception:
            continue

    if login_button is None:
        # Last-ditch: any visible button on the page that looks like a submit
        login_button = page.locator("button[type='submit'], input[type='submit']").first
        try:
            await login_button.wait_for(state="visible", timeout=10000)
        except Exception as e:
            logger.error("[%s] Could not find a login button after all fallbacks: %s", run_id, e)
            raise

    await login_button.click()
    logger.info("[%s] Login button clicked — waiting for navigation...", run_id)

    # ── Step 6: Wait for post-login navigation ────────────────────────
    await page.wait_for_load_state("networkidle", timeout=30000)
    await _assert_angular_ready(page, run_id, target_url)  # REC 1 — post-login hydration

    # ── Step 7: Verify JWT ────────────────────────────────────────────
    # MIGRATION: JWT key from the active AppProfile.
    jwt = None
    if _jwt_key:
        for attempt in range(10):
            jwt = await page.evaluate(f"localStorage.getItem('{_jwt_key}')")
            if jwt:
                break
            await page.wait_for_timeout(500)

    if jwt:
        logger.info(
            "[%s] ✓ Login successful — JWT present in localStorage (attempt %d)",
            run_id,
            attempt + 1,
        )
    else:
        logger.warning(
            "[%s] ⚠ JWT still not found after 5s polling. "
            "Login may have failed, or the app uses a different auth token key.",
            run_id,
        )

    # Fix 3: SPA barrier — wait for Angular to finish rendering the post-login
    # dashboard before releasing control to the planner.
    await _wait_for_post_login_spa_render(page, run_id)

    # SSO redirect recovery: products like vPromotions live on a separate subdomain
    # from the shared SSO site. After login, SSO can redirect the browser to the
    # user's default app (e.g. two-test.vcreative.net). Navigate back to target_url
    # so the planner starts at the correct product page. Mirrors ghost_login_node's
    # needs_product_nav logic.
    from urllib.parse import urlparse as _urlparse
    if _urlparse(page.url).netloc != _urlparse(target_url).netloc:
        logger.info(
            "[%s] SSO redirect detected: ended at %s instead of %s — navigating back to target URL",
            run_id, page.url, target_url,
        )
        await page.goto(target_url, wait_until="networkidle", timeout=30000)
        await _wait_for_post_login_spa_render(page, run_id)

    # Register primary actor in registry for instant switching
    await manager.register_primary_actor(state["role_context"].get("role_key", ""))

    # ── Track initial actor for persona resolution ────────────────────
    run_memory_update = {}
    existing_memory = state.get("run_memory", {})
    if not existing_memory.get("initial_actor"):
        run_memory_update = {
            "initial_actor": {
                "email": email,
                "role_key": state["role_context"].get("role_key", ""),
                "role_name": role_name,
            }
        }
        logger.info("[%s] Tracked initial actor: %s (%s)", run_id, role_name, email[:30])

    return {
        "browser_session_active": True,
        "current_page_url": page.url,
        "run_memory": run_memory_update,
    }


# ---------------------------------------------------------------------------
# Mid-test actor switch node
# ---------------------------------------------------------------------------

# Canonical role keys recognised by get_role_context().
_VALID_ROLE_KEYS: frozenset[str] = frozenset(
    {
        "account_executive",
        "sales_manager",
        "sales_assistant",
        "production_manager",
        "producer",
        "gm_gsm",
        "dubber",
        "digital_director",
        "voice_talent",
    }
)


async def switch_actor_mid_run_node(state: VQAState) -> dict:
    """
    Swap the active browser context to a different authenticated role.

    Called by the evaluator when an ACCOUNT_SWITCH step completes.
    Uses ``BrowserManager.switch_actor()`` which either reactivates an
    already-registered context (~50 ms fast path) or authenticates a new
    one from Playwright storage state.

    Role resolution order:
    1. ``test_plan.steps[ac_index].input_value`` — canonical key set by the AC parser
    2. ROLE_ALIASES scan of the raw AC step text (fallback when test_plan absent)

    After a successful switch, ``role_context`` is updated with the new
    role's credentials and the graph advances to the planner.
    """
    from backend.engine.roles import ROLE_ALIASES

    run_id = state["run_id"]
    ac_index = state.get("ac_step_index", 0)
    ac_steps = state.get("jira_ticket", {}).get("acceptance_criteria_steps", [])
    current_step_text = ac_steps[ac_index] if ac_index < len(ac_steps) else ""

    # ── 1. Resolve target role key ─────────────────────────────────────────
    target_role_key: str | None = None

    # Primary: test_plan.steps[ac_index].input_value (set by AC parser)
    test_plan = state.get("test_plan")
    if test_plan:
        plan_steps = test_plan.get("steps", [])
        if ac_index < len(plan_steps):
            input_val = (plan_steps[ac_index].get("input_value") or "").strip()
            if input_val in _VALID_ROLE_KEYS:
                target_role_key = input_val
                logger.info(
                    "[%s] ACCOUNT_SWITCH: role from test_plan input_value: '%s'",
                    run_id,
                    target_role_key,
                )

    # Fallback: scan step text for ROLE_ALIASES
    if not target_role_key and current_step_text:
        step_lower = current_step_text.lower()
        for alias, canonical in ROLE_ALIASES.items():
            if alias in step_lower:
                target_role_key = canonical
                logger.info(
                    "[%s] ACCOUNT_SWITCH: role from alias '%s' → '%s'",
                    run_id,
                    alias,
                    target_role_key,
                )
                break

    if not target_role_key:
        logger.error(
            "[%s] ACCOUNT_SWITCH: cannot determine target role from step '%s' — "
            "skipping actor switch, advancing to next step",
            run_id,
            current_step_text[:120],
        )
        return {
            "_next_node": "planner",
            "ac_step_index": ac_index + 1,
            "last_error": "ACCOUNT_SWITCH: target role could not be resolved from step text",
        }

    # ── 2. Switch browser context ──────────────────────────────────────────
    try:
        manager = get_manager(run_id)
        await manager.switch_actor(target_role_key)
        logger.info(
            "[%s] ✓ ACCOUNT_SWITCH: browser context switched to '%s'",
            run_id,
            target_role_key,
        )
    except Exception as exc:
        logger.error(
            "[%s] ACCOUNT_SWITCH: switch_actor('%s') raised %s — continuing anyway",
            run_id,
            target_role_key,
            exc,
        )
        return {
            "_next_node": "planner",
            "ac_step_index": ac_index + 1,
            "last_error": f"ACCOUNT_SWITCH browser switch failed: {exc!s}",
        }

    # ── 3. Update role_context ─────────────────────────────────────────────
    try:
        new_role_context = dict(get_role_context(target_role_key))
    except KeyError:
        logger.warning(
            "[%s] ACCOUNT_SWITCH: no RoleContext for '%s' — role_context unchanged",
            run_id,
            target_role_key,
        )
        new_role_context = state.get("role_context", {})

    prev_role_name = state.get("role_context", {}).get("role_name", "?")
    new_role_name = new_role_context.get("role_name", target_role_key)
    logger.info(
        "[%s] ACCOUNT_SWITCH complete: '%s' → '%s', advancing to step %d/%d",
        run_id,
        prev_role_name,
        new_role_name,
        ac_index + 2,
        len(ac_steps),
    )

    return {
        "_next_node": "planner",
        "role_context": new_role_context,
        "ac_step_index": ac_index + 1,
        "retry_count": 0,
        "agent_critique": "",
        "last_error": "",
        "ac_step_fail_counts": {},
        "ac_step_action_fail_count": 0,
        "current_ac_step_action_count": 0,
        "ac_step_failure_diary": [],
        "action_repeat_counts": {},
    }


# ---------------------------------------------------------------------------
# Smart Replay Check node (FEAT-043 / TASK-031)
# ---------------------------------------------------------------------------


async def replay_check_node(state: VQAState) -> dict:
    """
    Check whether an accepted test exists and replay it if available.

    Sits between ``login`` and ``planner`` in the graph. On every run:

    1. If ``settings.enable_smart_replay=False`` — routes to ``planner``.
    2. If no accepted test exists — routes to ``planner`` (normal AI run).
    3. If an accepted test exists — dispatches stored actions and routes to
       ``reporter`` on success, or ``planner`` on any step failure (fallback).

    Returns
    -------
    dict
        Partial state update with ``replay_succeeded``, ``replay_failed``,
        and ``_next_node``.
    """
    from backend.engine.replay_engine import ReplayEngine

    run_id = state["run_id"]
    engine = ReplayEngine(run_id=run_id)
    return await engine.replay(state)


def route_after_replay_check(state: VQAState) -> str:
    """
    Conditional edge: decide where to go after replay_check_node.

    Routes:
    - ``"reporter"``    — replay succeeded; all actions executed deterministically.
    - ``"ghost_login"`` — current structured step is GHOST_LOGIN; skip planner entirely.
    - ``"planner"``     — no accepted test, or replay failed (transparent fallback).
    """
    if state.get("replay_succeeded"):
        logger.info(
            "[%s] Smart Replay succeeded — routing to reporter",
            state.get("run_id", ""),
        )
        return "reporter"

    # When the first (or current) structured step is GHOST_LOGIN and admin auth
    # has NOT yet been established for this run, route directly to
    # ghost_login_node before the planner ever sees the page. Without this, the
    # planner encounters the login-page redirect, the AUTH_GATE fires, and the
    # run loops until it exhausts retries with a misleading "credentials
    # invalid" message.
    #
    # Once ghost_admin_authenticated is set, the node has done its job (admin
    # session established, browser landed on the product URL) and the planner
    # handles the actual ghost-panel DOM interaction as a normal step — vQA
    # does not hardcode selectors for the products it tests.
    _test_plan = state.get("test_plan") or {}
    _plan_steps = (
        list(_test_plan.steps)
        if hasattr(_test_plan, "steps")
        else (_test_plan.get("steps") or [])
    )
    _struct_index = state.get("structured_step_index", 0)
    if _struct_index < len(_plan_steps):
        _step = _plan_steps[_struct_index]
        _step_type = (
            _step.get("step_type")
            if isinstance(_step, dict)
            else getattr(_step, "step_type", "")
        )
        if _step_type == "GHOST_LOGIN" and not state.get("ghost_admin_authenticated"):
            logger.info(
                "[%s] GHOST_LOGIN step at structured index %d — routing to ghost_login "
                "for admin auth (bypassing planner to avoid AUTH_GATE_BLOCKED loop)",
                state.get("run_id", ""),
                _struct_index,
            )
            return "ghost_login"

    return "planner"


def route_after_login(state: VQAState) -> str:
    """
    Conditional edge: decide whether to run AI agent or static Playwright test.
    """
    engine = state.get("execution_engine", "ai")
    if engine == "static":
        logger.info(
            "[%s] Routing to PlaywrightExecutor (Static Engine)",
            state.get("run_id", ""),
        )
        return "playwright_executor"

    return "replay_check"


def _route_supervisor_after_login(state: VQAState) -> str:
    """
    Conditional edge: decide whether to run Supervisor or static Playwright test.
    """
    engine = state.get("execution_engine", "ai")
    if engine == "static":
        return "playwright_executor"

    return "supervisor"


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------


def build_graph(checkpointer: Any = None) -> CompiledStateGraph:
    """
    Build and compile the complete vQA LangGraph StateGraph.

    Creates a graph with 8 nodes and the following edge topology:

    - Linear: jira_fetch → ac_parser → setup_role → login → planner
    - Inner loop: planner → executor → evaluator
    - Conditional: evaluator → {planner, setup_role, reporter}
    - Terminal: reporter → END

    Parameters
    ----------
    checkpointer : Any, optional
        Checkpointer instance (e.g. MemorySaver) for state persistence
        and thread-based updates.  Required when
        ``settings.enable_hitl_before_executor`` is True — LangGraph
        cannot resume from an interrupt without a checkpointer.

    Returns
    -------
    CompiledGraph
        A compiled graph ready for execution.

    HITL Interrupt (FEAT-114)
    -------------------------
    When ``settings.enable_hitl_before_executor`` is ``True``, the graph is
    compiled with ``interrupt_before=["executor"]``.  Execution will pause
    before every ``executor_node`` invocation.  The caller must:

    1. Detect the ``__interrupt__`` event in the stream or invoke result.
    2. Show the planned action to the user and await approval.
    3. Resume via ``POST /run/{run_id}/resume-executor`` (which calls
       ``graph.invoke(None, config={"configurable": {"thread_id": run_id}})``).

    Without ``ENABLE_HITL_BEFORE_EXECUTOR=True`` (the default), execution is
    fully autonomous and this parameter has no effect.

    Example
    -------
    >>> from backend.engine.graph import build_graph
    >>> from backend.engine.state import make_initial_state
    >>>
    >>> graph = build_graph()
    >>> initial = make_initial_state(
    ...     run_id="run-test",
    ...     jira_ticket_id="VC2-8967",
    ...     role="account_executive",
    ...     target_url="https://two-test.vcreative.net",
    ...     mode="headless",
    ... )
    >>> result = await graph.ainvoke(initial)
    >>> result["s3_report_url"]
    'https://vcreative-deployments.s3.amazonaws.com/.../report.html'
    """
    logger.info("Building vQA StateGraph...")

    # ── Create the graph with VQAState as the state schema ────────────
    graph = StateGraph(VQAState)

    # ── Register nodes ────────────────────────────────────────────────
    # Each node receives the full state and returns a partial update.

    graph.add_node("jira_fetch", jira_fetch_node)  # Fetch ticket from Jira
    graph.add_node("ac_parser", ac_parser_node)  # Parse AC into steps
    graph.add_node("critic", critic_node)  # Pre-execution LLM critic (critic-pass-llm-evaluator — Phase 2)
    graph.add_node("setup_role", setup_role_node)  # Load role creds + perms
    graph.add_node("login", login_node)  # Browser login + JWT
    graph.add_node("playwright_executor", playwright_executor_node)  # Static Playwright execution (TASK-059)
    graph.add_node("replay_check", replay_check_node)  # Smart Replay gate (FEAT-043)
    graph.add_node("planner", planner_node)  # SEE-THINK (multimodal)
    graph.add_node("executor", executor_node)  # ACT (Playwright)
    graph.add_node("evaluator", evaluator_node)  # JUDGE (routing)
    graph.add_node("verifier", step_verifier_node)  # VERIFY (LLM-as-judge)
    graph.add_node("human_takeover", human_takeover_node)  # PAUSE for human
    graph.add_node("reporter", reporter_node)  # REPORT (HTML + upload)
    graph.add_node("switch_actor_mid_run", switch_actor_mid_run_node)  # Mid-test role switch
    graph.add_node("persona_switch", persona_switch_node)  # Mid-test persona (auth context) switch — TASK-063
    graph.add_node("ghost_login", ghost_login_node)  # Mid-test ghost login impersonation — TASK-102

    from backend.engine.debugger import main_graph_debugger_node

    graph.add_node("debugger", main_graph_debugger_node)  # RAG-informed fix before human_takeover

    # ── Set entry point ───────────────────────────────────────────────
    graph.set_entry_point("jira_fetch")

    # ── Wire sequential edges ─────────────────────────────────────────
    # These run in strict order: fetch → parse → critic → setup → login → plan
    graph.add_edge("jira_fetch", "ac_parser")
    # critic-pass-llm-evaluator: critic fires between ac_parser and setup_role.
    # On pass (or API error / feature-disabled / static run): → setup_role.
    # On mismatch with retries remaining: → ac_parser (with critic_feedback in state).
    graph.add_edge("ac_parser", "critic")
    graph.add_conditional_edges(
        "critic",
        route_after_critic,
        {
            "setup_role": "setup_role",
            "ac_parser": "ac_parser",
        },
    )
    graph.add_edge("setup_role", "login")

    # ── login → execution_router ──────────────────────────────────────
    graph.add_conditional_edges(
        "login",
        route_after_login,
        {
            "playwright_executor": "playwright_executor",
            "replay_check": "replay_check",
        },
    )

    # ── playwright_executor → reporter (Terminal path for static runs) ─
    # Note: playwright_executor_node returns _next_node="reporter" or
    # is wired sequentially here.
    graph.add_edge("playwright_executor", "reporter")

    # ── Replay check → planner (no match) or reporter (replay succeeded) ──
    # Also routes to ghost_login when the current structured step is GHOST_LOGIN.
    graph.add_conditional_edges(
        "replay_check",
        route_after_replay_check,
        {
            "planner": "planner",
            "reporter": "reporter",
            "ghost_login": "ghost_login",
        },
    )

    # ── Wire the inner loop ───────────────────────────────────────────
    # planner → executor → evaluator (always this order)
    graph.add_edge("planner", "executor")
    graph.add_edge("executor", "evaluator")

    # ── Wire the conditional edge from evaluator ──────────────────────
    # Routes: planner (retry/next), setup_role (next role), reporter (done/fatal),
    # verifier (check step completion), human_takeover (stuck), login (re-auth)
    graph.add_conditional_edges(
        "evaluator",
        route_after_evaluator,
        {
            "planner": "planner",
            "setup_role": "setup_role",
            "reporter": "reporter",
            "verifier": "verifier",
            "human_takeover": "human_takeover",
            "login": "login",  # AUTH_GATE_BLOCKED re-authentication path
            "debugger": "debugger",  # RAG diagnosis after 5 consecutive Playwright failures
            "switch_actor_mid_run": "switch_actor_mid_run",  # Mid-test role switch
            "persona_switch": "persona_switch",  # Mid-test persona auth context switch — TASK-063
            "ghost_login": "ghost_login",  # Mid-test ghost login admin impersonation — TASK-102
        },
    )

    # ── Debugger → planner (retry with fix applied) ───────────────────
    graph.add_edge("debugger", "planner")

    # ── switch_actor_mid_run → planner ────────────────────────────────
    # After swapping browser contexts, resume normal planning for the next step.
    graph.add_edge("switch_actor_mid_run", "planner")

    # ── persona_switch → planner ──────────────────────────────────────
    # After replacing auth context (persona switch), resume normal planning.
    # persona_switch_node sets ac_step_index to the next step before returning.
    graph.add_edge("persona_switch", "planner")

    # ── ghost_login → planner ─────────────────────────────────────────
    # After performing admin ghost login impersonation, resume normal planning.
    # ghost_login_node sets ac_step_index to the next step before returning.
    graph.add_edge("ghost_login", "planner")

    # ── Wire the conditional edge from verifier ──────────────────────
    # Routes: planner (NOT_YET/FAILED) or evaluator (SATISFIED, for final routing)
    graph.add_conditional_edges(
        "verifier",
        route_after_verifier,
        {
            "planner": "planner",
            "evaluator": "evaluator",
        },
    )

    # ── Wire human_takeover conditional edge ─────────────────────────
    # After human completes (or skips), route back to planner or reporter.
    graph.add_conditional_edges(
        "human_takeover",
        route_after_evaluator,  # reads _next_node — same routing logic
        {
            "planner": "planner",
            "reporter": "reporter",
        },
    )

    # ── Wire terminal edge ────────────────────────────────────────────
    graph.add_edge("reporter", END)

    # ── Compile and return ────────────────────────────────────────────
    # FEAT-114: When ENABLE_HITL_BEFORE_EXECUTOR=True, compile with
    # interrupt_before=["executor"] so execution pauses before every
    # executor_node invocation for human approval.  Requires a checkpointer.
    from backend.config import settings as _cfg  # noqa: PLC0415

    if _cfg.enable_hitl_before_executor:
        compiled = graph.compile(
            checkpointer=checkpointer,
            interrupt_before=["executor"],
        )
        logger.info(
            "vQA StateGraph compiled WITH interrupt_before=['executor'] (FEAT-114 HITL mode). "
            "Graph will pause before each executor_node invocation for human approval."
        )
    else:
        compiled = graph.compile(checkpointer=checkpointer)
        logger.info(
            "vQA StateGraph compiled: 14 nodes (incl. verifier + human_takeover + debugger "
            "+ switch_actor_mid_run + persona_switch + ghost_login), ready to execute"
        )

    return compiled


# ---------------------------------------------------------------------------
# Supervisor-Worker graph builder (Phase 1)
# ---------------------------------------------------------------------------
# ADDITIVE — the existing build_graph() above is completely unchanged.
# The new graph is invoked via a separate entry point.


def route_to_worker(state: VQAState) -> str:
    """
    Conditional edge: route to the appropriate Worker based on the
    Supervisor's Intent.

    Routes worker_type → specialised worker node:
      - "form"     → form_worker
      - "table"    → table_worker
      - "verify"   → verify_worker
      - "navigate" → navigate_worker
      - "auth"     → auth_worker
      - fallback   → generic_worker
    """
    intents = state.get("supervisor_intents", [])
    if not intents:
        logger.info("route_to_worker: no supervisor_intents — defaulting to generic_worker")
        return "generic_worker"

    latest = intents[-1]
    worker_type = latest.get("worker_type", "form")

    route_map = {
        "form": "form_worker",
        "table": "table_worker",
        "verify": "verify_worker",
        "navigate": "navigate_worker",
        "auth": "auth_worker",
    }

    target_worker = route_map.get(worker_type, "generic_worker")
    logger.info(
        "route_to_worker: intent worker_type='%s' → %s",
        worker_type,
        target_worker,
    )
    return target_worker


def _route_supervisor_after_evaluator(state: VQAState) -> str:
    """
    Conditional edge for the Supervisor-Worker graph's evaluator.

    Translates the evaluator's ``_next_node`` for the new topology:
      - ``"planner"`` → ``"supervisor"`` (retry via re-classification)
      - All other routes are passed through unchanged.
    """
    route = state.get("_next_node", "")
    if not route:
        logger.warning("_route_supervisor_after_evaluator: _next_node is empty — defaulting to 'supervisor'")
        return "supervisor"

    # Evaluator emits "planner" for retries — redirect to supervisor
    if route == "planner":
        return "supervisor"

    return route


def build_supervisor_graph(checkpointer: Any = None) -> CompiledStateGraph:
    """
    Build and compile the Supervisor-Worker StateGraph.

    Topology::

        jira_fetch → ac_parser → setup_role → login
          → supervisor → [route_to_worker] → {specialised_worker}
            → executor → evaluator
              → verifier ↔ supervisor (retry)
              → human_takeover → supervisor | reporter
              → supervisor (next step)
              → setup_role (next role)
              → reporter → END

    Workers: form_worker, table_worker, verify_worker, navigate_worker,
    auth_worker, generic_worker (catch-all fallback).

    Returns
    -------
    langgraph.graph.StateGraph
        Compiled graph ready for ``graph.ainvoke(state)``.
    """
    from backend.engine.supervisor import supervisor_node
    from backend.engine.workers.auth_worker import auth_worker_node
    from backend.engine.workers.form_worker import form_worker_node
    from backend.engine.workers.generic_worker import generic_worker_node
    from backend.engine.workers.navigate_worker import navigate_worker_node
    from backend.engine.workers.table_worker import table_worker_node
    from backend.engine.workers.verify_worker import verify_worker_node

    logger.info("Building Supervisor-Worker StateGraph...")

    graph = StateGraph(VQAState)

    # ── Register nodes ────────────────────────────────────────────────
    graph.add_node("jira_fetch", jira_fetch_node)
    graph.add_node("ac_parser", ac_parser_node)
    graph.add_node("critic", critic_node)  # critic-pass-llm-evaluator
    graph.add_node("setup_role", setup_role_node)
    graph.add_node("login", login_node)
    graph.add_node("playwright_executor", playwright_executor_node)
    graph.add_node("supervisor", supervisor_node)

    # Workers (Phase 3 — all specialised workers active)
    graph.add_node("generic_worker", generic_worker_node)
    graph.add_node("form_worker", form_worker_node)
    graph.add_node("table_worker", table_worker_node)
    graph.add_node("verify_worker", verify_worker_node)
    graph.add_node("navigate_worker", navigate_worker_node)
    graph.add_node("auth_worker", auth_worker_node)

    graph.add_node("executor", executor_node)
    graph.add_node("evaluator", evaluator_node)
    graph.add_node("verifier", step_verifier_node)
    graph.add_node("human_takeover", human_takeover_node)
    graph.add_node("reporter", reporter_node)

    # Debugger (Phase 3C — RAG-informed fix before human_takeover)
    from backend.engine.debugger import main_graph_debugger_node

    graph.add_node("debugger", main_graph_debugger_node)

    # ── Entry point ───────────────────────────────────────────────────
    graph.set_entry_point("jira_fetch")

    # ── Pre-flight sequential edges ───────────────────────────────────
    graph.add_edge("jira_fetch", "ac_parser")
    # critic-pass-llm-evaluator: critic fires between ac_parser and setup_role.
    graph.add_edge("ac_parser", "critic")
    graph.add_conditional_edges(
        "critic",
        route_after_critic,
        {
            "setup_role": "setup_role",
            "ac_parser": "ac_parser",
        },
    )
    graph.add_edge("setup_role", "login")

    # ── login → execution_router (static vs supervisor) ───────────────
    graph.add_conditional_edges(
        "login",
        _route_supervisor_after_login,
        {
            "playwright_executor": "playwright_executor",
            "supervisor": "supervisor",
        },
    )

    # ── playwright_executor → reporter (Terminal path for static runs) ─
    graph.add_edge("playwright_executor", "reporter")

    # ── supervisor → [route_to_worker] ────────────────────────────────
    graph.add_conditional_edges(
        "supervisor",
        route_to_worker,
        {
            "generic_worker": "generic_worker",
            "form_worker": "form_worker",
            "table_worker": "table_worker",
            "verify_worker": "verify_worker",
            "navigate_worker": "navigate_worker",
            "auth_worker": "auth_worker",
        },
    )

    # ── All workers → executor → evaluator ─────────────────────────────
    graph.add_edge("generic_worker", "executor")
    graph.add_edge("form_worker", "executor")
    graph.add_edge("table_worker", "executor")
    graph.add_edge("verify_worker", "executor")
    graph.add_edge("navigate_worker", "executor")
    graph.add_edge("auth_worker", "executor")
    graph.add_edge("executor", "evaluator")

    # ── Evaluator routing (planner→supervisor redirect) ───────────────
    graph.add_conditional_edges(
        "evaluator",
        _route_supervisor_after_evaluator,
        {
            "supervisor": "supervisor",
            "setup_role": "setup_role",
            "reporter": "reporter",
            "verifier": "verifier",
            "human_takeover": "human_takeover",
            "login": "login",
            "debugger": "debugger",
        },
    )

    # ── Debugger → supervisor (retry with fix recommendation) ─────────
    graph.add_edge("debugger", "supervisor")

    # ── Verifier routing (planner→supervisor redirect) ────────────────
    graph.add_conditional_edges(
        "verifier",
        route_after_verifier,
        {
            "planner": "supervisor",
            "evaluator": "evaluator",
        },
    )

    # ── Human takeover routing ────────────────────────────────────────
    graph.add_conditional_edges(
        "human_takeover",
        _route_supervisor_after_evaluator,
        {
            "supervisor": "supervisor",
            "reporter": "reporter",
        },
    )

    # ── Terminal edge ─────────────────────────────────────────────────
    graph.add_edge("reporter", END)

    # ── Compile ───────────────────────────────────────────────────────
    compiled = graph.compile(checkpointer=checkpointer)
    logger.info("Supervisor-Worker StateGraph compiled: 17 nodes (supervisor + 6 workers + 10 core)")

    return compiled
