"""
vQA — Browser-Use Execution Node
====================================
Module: backend/engine/web_surfer.py

Replaces the legacy manual Playwright dispatch table with the ``browser-use``
library's high-level ``Agent``, backed by ``ChatBedrockConverse`` (Claude 3.5
Sonnet).  This eliminates brittle per-action try/except wrappers and delegates
element location, retry, and DOM-observation to the battle-tested browser-use
execution loop.

Authentication
--------------
When a ``role_name`` is supplied, ``run_browser_task`` calls
``backend.engine.auth_manager.ensure_role_authenticated()`` to guarantee that a
Playwright ``storage_state`` JSON file exists and is within-TTL before the
browser-use Agent launches.  The storage state restores cookies and
``localStorage`` (including ``vc2JWT``) so the agent starts on the authenticated
dashboard rather than the login page.

If ``role_name`` is ``None`` (the default), no auth state is loaded and the
agent starts an anonymous session.

Public API
----------
    from backend.engine.web_surfer import run_browser_task, BrowserResult

    # Anonymous session (no pre-auth)
    result = await run_browser_task(
        instruction="Navigate to https://two-test.vcreative.net and verify the login page loads.",
        max_steps=10,
    )

    # Pre-authenticated session
    result = await run_browser_task(
        instruction="Open the Production Orders table and sort by Due Days ascending.",
        role_name="account_executive",
        start_url="https://two-test.vcreative.net",
        max_steps=25,
    )

BrowserResult fields
--------------------
    success        bool    — True if the Agent completed the instruction
    final_url      str     — URL of the page when the agent finished
    extracted_text str     — Any text the agent extracted (e.g. table contents)
    error_message  str     — Raw exception or agent failure message (empty on success)
    steps_taken    int     — How many agent steps were executed
    history        list    — Raw AgentHistoryList entries (for audit / replay)
    role_name      str     — The role used for this task (empty if anonymous)
    auth_state_path str    — Absolute path to the storage-state file used (empty if none)

Configuration (via environment / .env)
---------------------------------------
    BROWSER_USE_MODEL_ID   Bedrock model ID (default: claude 3.5 sonnet cross-region)
    AWS_BEDROCK_REGION     Bedrock region (default: us-west-2)
    BROWSER_HEADLESS       "true"/"false" — run browser headless (default: "true")
    BROWSER_MAX_STEPS      Safety cap on agent steps (default: 50)
    AUTH_STATE_TTL_HOURS   Hours before auth state expires (default: 4, see auth_manager.py)

Dependencies (add to requirements.txt)
---------------------------------------
    browser-use>=0.1.40,<1.0.0
    langchain-aws>=0.2.0,<1.0.0

Notes
-----
- browser-use Agent launches its OWN Playwright context internally.
  Do NOT share the vQA BrowserManager with this class — they operate
  on independent browser sessions.
- The ``ChatBedrockConverse`` call uses cross-region inference profiles
  that match the model IDs already configured in ``backend/config.py``.
- ``storage_state`` is passed to ``BrowserConfig`` so browser-use loads
  the auth cookies/localStorage on context creation, before the agent
  takes any steps.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional-import guards
# ---------------------------------------------------------------------------
try:
    from browser_use import Agent as BrowserAgent
    from browser_use import Browser
    from browser_use.browser.profile import BrowserProfile as BrowserConfig

    _BROWSER_USE_AVAILABLE = True
except ImportError as _e:  # pragma: no cover
    _BROWSER_USE_AVAILABLE = False
    logger.warning(
        "web_surfer: browser-use not installed (%s). Install: pip install browser-use",
        _e,
    )

try:
    from langchain_aws import ChatBedrockConverse

    _LANGCHAIN_AWS_AVAILABLE = True
except ImportError as _e:  # pragma: no cover
    _LANGCHAIN_AWS_AVAILABLE = False
    logger.warning(
        "web_surfer: langchain-aws not installed (%s). Install: pip install langchain-aws",
        _e,
    )

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_HEADLESS = os.getenv("BROWSER_HEADLESS", "true").lower() == "true"
_MAX_STEPS_DEFAULT = int(os.getenv("BROWSER_MAX_STEPS", "50"))


# ---------------------------------------------------------------------------
# Return type
# ---------------------------------------------------------------------------


@dataclass
class BrowserResult:
    """
    Structured result returned by ``run_browser_task``.

    Attributes
    ----------
    success : bool
        True if the browser-use Agent completed the instruction without
        an unhandled exception.
    final_url : str
        The URL the browser was on when the agent finished (or errored).
        Empty string if the browser never launched.
    extracted_text : str
        Any content the agent explicitly extracted from the page
        (e.g., table text, form values).  May be empty.
    error_message : str
        Human-readable description of the failure.  Empty on success.
    steps_taken : int
        Number of agent steps executed before completion or failure.
    history : list[Any]
        Raw ``AgentHistoryList`` entries from browser-use.
        Useful for audit trails and replay.
    role_name : str
        The role that was authenticated for this session.
        Empty string for anonymous (no-auth) tasks.
    auth_state_path : str
        Absolute path to the Playwright storage-state JSON used.
        Empty string when no auth state was loaded (anonymous session).
    """

    success: bool
    final_url: str = ""
    extracted_text: str = ""
    error_message: str = ""
    steps_taken: int = 0
    history: list[Any] = field(default_factory=list)
    role_name: str = ""
    auth_state_path: str = ""


# ---------------------------------------------------------------------------
# LLM factory — delegates to centralized provider
# ---------------------------------------------------------------------------


def _build_llm() -> "ChatBedrockConverse":
    """
    Create an LLM client for the browser-use Agent.

    Delegates to the centralized ``get_llm()`` factory from ``backend.llm``.
    Uses the ``surfer`` purpose preset (8192 max_tokens, temp=0).

    Returns
    -------
    ChatBedrockConverse
        Configured LLM client with vision/tool-calling support.
    """
    from backend.llm import get_llm

    return get_llm("surfer", max_tokens=8192)


# ---------------------------------------------------------------------------
# Auth state resolution
# ---------------------------------------------------------------------------


def _resolve_auth_state(
    role_name: str | None,
    *,
    login_url: str | None,
    headless: bool,
    force_refresh: bool,
) -> str:
    """
    Resolve a Playwright storage-state path for ``role_name``.

    Calls ``auth_manager.ensure_role_authenticated()`` synchronously.
    This is safe to call from an async context because the auth manager
    uses ``playwright.sync_api`` (its own thread / event loop) internally.

    Args
    ----
    role_name : str | None
        vProMedia role key or alias.  ``None`` → anonymous session.
    login_url : str | None
        Override login URL passed through to the auth manager.
    headless : bool
        Whether the auto-login browser runs headlessly.
    force_refresh : bool
        Force a fresh login even if a valid state file exists.

    Returns
    -------
    str
        Absolute path to the storage-state JSON, or empty string if
        ``role_name`` is ``None`` or auth manager fails non-fatally.
    """
    if not role_name:
        return ""

    try:
        from backend.engine.auth_manager import ensure_role_authenticated

        state_path = ensure_role_authenticated(
            role_name,
            login_url=login_url,
            headless=headless,
            force_refresh=force_refresh,
        )
        logger.info(
            "web_surfer: auth state resolved for role '%s' → %s",
            role_name,
            state_path,
        )
        return state_path
    except (KeyError, ValueError) as exc:
        # Unknown role or missing credentials — surface immediately (hard fail)
        raise RuntimeError(f"web_surfer: auth setup for role '{role_name}' failed: {exc}") from exc
    except Exception as exc:
        # Login failure — surface as RuntimeError so the caller can decide
        # whether to retry or fall back to anonymous mode
        raise RuntimeError(f"web_surfer: Playwright login for role '{role_name}' failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Core async execution function
# ---------------------------------------------------------------------------


async def run_browser_task(
    instruction: str,
    *,
    role_name: str | None = None,
    start_url: str = "",
    max_steps: int = _MAX_STEPS_DEFAULT,
    headless: bool = _HEADLESS,
    login_url: str | None = None,
    force_auth_refresh: bool = False,
) -> BrowserResult:
    """
    Execute a natural-language browser instruction via browser-use Agent.

    The Agent uses ``ChatBedrockConverse`` (Claude 3.5 Sonnet) to perceive
    the current page state and decide which browser actions to take.  It
    runs entirely within its own Playwright browser context — independent
    of the vQA BrowserManager used by the main execution graph.

    When ``role_name`` is provided, the function first calls the
    ``AuthManager`` to guarantee a valid Playwright ``storage_state`` JSON
    exists for that role.  The storage state is injected into ``BrowserConfig``
    before the Agent launches, so the agent starts in an already-authenticated
    session (bypassing the login form entirely).

    Args
    ----
    instruction : str
        Natural-language task description for the agent.
        Example: "Navigate to the Production Orders table, sort by 'Due Days'
        ascending, and extract the first row's client name."
    role_name : str | None
        vProMedia role key or alias to authenticate as before running the task.
        Examples: ``"account_executive"``, ``"ae"``, ``"producer"``.
        If ``None``, the agent starts an anonymous browser session.
    start_url : str
        Optional URL to navigate to before the agent starts.
        If empty, the agent begins on the URL already loaded by the auth
        state (typically the post-login dashboard).
    max_steps : int
        Hard cap on the number of agent action steps (default 50).
        Prevents runaway agents on ambiguous instructions.
    headless : bool
        Whether to run the browser in headless mode (default: True).
        Set ``False`` for debugging / local inspection.
    login_url : str | None
        Override the login URL used by the AuthManager.
        Defaults to ``settings.target_url``.
    force_auth_refresh : bool
        If ``True``, delete the existing auth state file and perform a
        fresh Playwright login before starting the task.  Useful when
        credentials have changed or the session is suspected stale.

    Returns
    -------
    BrowserResult
        Structured result with success flag, final URL, extracted content,
        role attribution, auth state path, and any error message.

    Raises
    ------
    RuntimeError
        If ``role_name`` is unknown or the Playwright auto-login fails.
        The caller should catch this for graceful degradation.

    Examples
    --------
    >>> # Authenticated task
    >>> result = await run_browser_task(
    ...     "Open a Quick Order for Radio Commercial and verify the form loads.",
    ...     role_name="account_executive",
    ...     start_url="https://two-test.vcreative.net",
    ...     max_steps=30,
    ... )
    >>> assert result.success
    >>> assert result.role_name == "account_executive"
    >>> assert result.auth_state_path.endswith("account_executive_state.json")

    >>> # Anonymous task (no role)
    >>> result = await run_browser_task(
    ...     "Navigate to https://two-test.vcreative.net and confirm the login page loads.",
    ...     max_steps=5,
    ... )
    >>> assert result.auth_state_path == ""
    """
    if not instruction or not instruction.strip():
        return BrowserResult(
            success=False,
            error_message="run_browser_task: instruction must be a non-empty string",
            role_name=role_name or "",
        )

    if not _BROWSER_USE_AVAILABLE:
        return BrowserResult(
            success=False,
            error_message=("web_surfer: browser-use library not installed. Run: pip install browser-use"),
            role_name=role_name or "",
        )

    logger.info(
        "web_surfer: starting browser task — role=%s, instruction=%.120s, max_steps=%d",
        role_name or "anonymous",
        instruction,
        max_steps,
    )

    # ── Step 1: Resolve LLM ────────────────────────────────────────────────
    try:
        llm = _build_llm()
    except RuntimeError as exc:
        return BrowserResult(
            success=False,
            error_message=str(exc),
            role_name=role_name or "",
        )

    # ── Step 2: Resolve auth state (synchronous, may trigger Playwright login)
    # Run in a thread executor so the sync playwright.sync_api call does not
    # block the event loop (browser-use itself is async).
    auth_state_path: str = ""
    if role_name:
        try:
            loop = asyncio.get_event_loop()
            auth_state_path = await loop.run_in_executor(
                None,  # default ThreadPoolExecutor
                lambda: _resolve_auth_state(
                    role_name,
                    login_url=login_url,
                    headless=headless,
                    force_refresh=force_auth_refresh,
                ),
            )
        except RuntimeError as exc:
            # Auth failure is a hard error — surface immediately
            return BrowserResult(
                success=False,
                error_message=str(exc),
                role_name=role_name,
                auth_state_path="",
            )

    # ── Step 3: Build BrowserConfig with optional storage_state ───────────
    browser_config_kwargs: dict[str, Any] = {
        "headless": headless,
        "disable_security": False,
    }
    if auth_state_path:
        # Pass the path string — browser-use / Playwright will deserialise it
        browser_config_kwargs["storage_state"] = auth_state_path
        logger.info(
            "web_surfer: injecting auth state — role=%s, path=%s",
            role_name,
            auth_state_path,
        )

    browser_config = BrowserConfig(**browser_config_kwargs)

    # ── Step 4: Compose the full task description ──────────────────────────
    full_task = instruction
    if start_url and start_url.startswith("http"):
        full_task = f"First navigate to: {start_url}\n\nThen: {instruction}"
    elif auth_state_path and not start_url:
        # With auth state but no explicit start_url: hint the agent that it
        # should already be on the dashboard, not the login page.
        full_task = (
            f"You are already authenticated as '{role_name}'. "
            f"The session cookies and localStorage have been pre-loaded. "
            f"Do NOT navigate to the login page.\n\n"
            f"Task: {instruction}"
        )

    # ── Step 5: Run the Agent ──────────────────────────────────────────────
    agent_history: list[Any] = []
    final_url: str = ""
    extracted_text: str = ""
    steps_taken: int = 0

    try:
        browser = Browser(browser_profile=browser_config)
        agent = BrowserAgent(
            task=full_task,
            llm=llm,
            browser=browser,
            max_actions_per_step=5,  # Batch moderate; matches vQA cadence
            use_vision=True,  # Claude vision for DOM-ambiguous states
        )

        logger.info(
            "web_surfer: Agent created — role=%s, running up to %d steps …",
            role_name or "anonymous",
            max_steps,
        )
        history = await agent.run(max_steps=max_steps)

        # ── Extract result fields from AgentHistoryList ────────────────────
        agent_history = list(history) if history is not None else []
        steps_taken = len(agent_history)

        # Final URL: check the last history entry
        for entry in reversed(agent_history):
            url = getattr(entry, "url", None) or ""
            if url:
                final_url = url
                break

        # Extracted text: browser-use stores it in the agent result
        result_obj = getattr(history, "final_result", None)
        if callable(result_obj):
            result_str = result_obj()
            extracted_text = str(result_str) if result_str else ""
        elif isinstance(result_obj, str):
            extracted_text = result_obj

        # Success heuristic: agent finished without exception
        # browser-use sets is_done=True when the agent calls done()
        is_done = getattr(history, "is_done", None)
        if callable(is_done):
            success = bool(is_done())
        else:
            # If is_done is not available, treat a completed run as success
            success = True

        logger.info(
            "web_surfer: task COMPLETE — role=%s, success=%s, steps=%d, final_url=%s",
            role_name or "anonymous",
            success,
            steps_taken,
            final_url[:80] if final_url else "(unknown)",
        )

        return BrowserResult(
            success=success,
            final_url=final_url,
            extracted_text=extracted_text,
            error_message="" if success else "Agent did not call done() — task may be incomplete",
            steps_taken=steps_taken,
            history=agent_history,
            role_name=role_name or "",
            auth_state_path=auth_state_path,
        )

    except asyncio.TimeoutError as exc:
        logger.error(
            "web_surfer: task timed out after %d steps (role=%s): %s",
            steps_taken,
            role_name or "anonymous",
            exc,
        )
        return BrowserResult(
            success=False,
            final_url=final_url,
            error_message=f"TimeoutError after {steps_taken} steps: {exc}",
            steps_taken=steps_taken,
            history=agent_history,
            role_name=role_name or "",
            auth_state_path=auth_state_path,
        )
    except Exception as exc:  # pylint: disable=broad-except
        err_str = f"{type(exc).__name__}: {exc}"
        logger.error(
            "web_surfer: task FAILED at step %d (role=%s) — %s",
            steps_taken,
            role_name or "anonymous",
            err_str,
        )
        return BrowserResult(
            success=False,
            final_url=final_url,
            error_message=err_str,
            steps_taken=steps_taken,
            history=agent_history,
            role_name=role_name or "",
            auth_state_path=auth_state_path,
        )
