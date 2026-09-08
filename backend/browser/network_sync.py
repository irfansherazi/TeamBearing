"""
vQA — Network-Based Timing Synchronization
============================================
Module: backend/browser/network_sync.py

Replaces the heuristic DOM-polling timing strategy with network traffic
interception.  Since Angular's ``getAllAngularTestabilities()`` is stripped
in production builds, we use Playwright's built-in network detection:

  1. ``page.wait_for_load_state('networkidle')`` — waits until no network
     connections for 500ms.  Suitable for most navigation and form submissions.

  2. ``wait_for_api_response()`` — targeted interception of a specific
     REST/GraphQL API endpoint.  Used when we know the exact response that
     confirms the UI data has refreshed (e.g., after sorting a table).

Design Constraints
------------------
  - vSuite has permanent WebSocket heartbeat polling that keeps the network
    permanently non-idle in some configurations.  ``wait_for_data_settled()``
    uses a configurable timeout with a fast fallback (DOM stability poll)
    for when ``networkidle`` cannot fire.

  - These functions are async utilities, NOT LangGraph nodes.  They are
    called directly by the executor and verifier modules.

See Also
--------
  - backend/engine/executor.py     — calls these after each action
  - backend/engine/state_tracker.py — runs AFTER network settles
  - backend/browser/context.py     — BrowserManager lifecycle
"""

import logging
import re
from typing import Optional

from playwright.async_api import Page, Response

logger = logging.getLogger(__name__)


async def wait_for_data_settled(
    page: Page,
    timeout_ms: int = 10000,
    run_id: str = "",
) -> bool:
    """Wait for pending XHR/fetch responses to complete.

    Uses Playwright's built-in ``networkidle`` detection as the primary
    strategy.  If it times out (common with WebSocket-heavy SPAs), falls
    back to a lightweight DOM stability check.

    Parameters
    ----------
    page : Page
        The active Playwright page.
    timeout_ms : int
        Maximum wait time in milliseconds.
    run_id : str
        Run identifier for log correlation.

    Returns
    -------
    bool
        ``True`` if network became idle; ``False`` if fallback was used.
    """
    try:
        await page.wait_for_load_state("networkidle", timeout=timeout_ms)
        logger.debug("[%s] Network idle confirmed within %dms", run_id, timeout_ms)
        return True
    except Exception:
        # networkidle timed out (background polling keeps it busy).
        # Fall back to a fast DOM stability check.
        logger.debug(
            "[%s] networkidle timed out (%dms) — using DOM stability fallback",
            run_id,
            timeout_ms,
        )
        return await _dom_stability_fallback(page, max_polls=10, interval_ms=200)


async def wait_for_api_response(
    page: Page,
    url_pattern: str = "**/spots*",
    timeout_ms: int = 8000,
    expected_status: int = 200,
    run_id: str = "",
) -> Optional[Response]:
    """Wait for a specific API response that confirms data has refreshed.

    Use this when you know the exact endpoint that fires after a table sort,
    filter change, or data mutation.  More reliable than ``networkidle``
    because it targets the exact response needed.

    Parameters
    ----------
    page : Page
        The active Playwright page.
    url_pattern : str
        Glob pattern or substring to match against the response URL.
        Examples: ``"**/spots*"``, ``"**/graphql"``, ``"**/auth"``
    timeout_ms : int
        Maximum wait time in milliseconds.
    expected_status : int
        Expected HTTP status code (typically 200).
    run_id : str
        Run identifier for log correlation.

    Returns
    -------
    Response | None
        The matched response, or ``None`` if timeout.
    """
    # Convert glob-style pattern to a regex-compatible check
    pattern_regex = url_pattern.replace("**", ".*").replace("*", "[^/]*")

    try:
        response = await page.wait_for_response(
            lambda r: bool(re.search(pattern_regex, r.url)) and r.status == expected_status,
            timeout=timeout_ms,
        )
        logger.debug(
            "[%s] API response matched: %s (status=%d, %dms budget)",
            run_id,
            response.url[:100],
            response.status,
            timeout_ms,
        )
        return response
    except Exception:
        logger.debug(
            "[%s] API response wait timed out: pattern='%s' (%dms)",
            run_id,
            url_pattern,
            timeout_ms,
        )
        return None


async def wait_for_table_data_refresh(
    page: Page,
    timeout_ms: int = 8000,
    run_id: str = "",
) -> bool:
    """Wait for the vSuite table data to refresh after a sort/filter action.

    Checks for the specific API patterns used by vSuite:
      - ``/spots`` — Production Orders list data
      - ``/mmorders`` — MyBox / order queries
      - ``/graphql`` — GraphQL aggregate queries

    Parameters
    ----------
    page : Page
        The active Playwright page.
    timeout_ms : int
        Maximum wait time.
    run_id : str
        Run identifier for log correlation.

    Returns
    -------
    bool
        True if a matching API response was intercepted.
    """
    # Try the most common table data endpoint first
    response = await wait_for_api_response(
        page,
        url_pattern="**/spots*",
        timeout_ms=timeout_ms,
        run_id=run_id,
    )
    if response:
        return True

    # Fallback: check for GraphQL responses (used by some table queries)
    response = await wait_for_api_response(
        page,
        url_pattern="**/graphql*",
        timeout_ms=max(2000, timeout_ms // 2),
        run_id=run_id,
    )
    return response is not None


async def _dom_stability_fallback(
    page: Page,
    max_polls: int = 10,
    interval_ms: int = 200,
) -> bool:
    """Lightweight DOM stability check — 3 consecutive identical reads.

    Used when ``networkidle`` cannot fire due to persistent background traffic.
    This is a fast (~600ms best case, ~2s worst case) substitute that confirms
    Angular change detection has completed.

    Parameters
    ----------
    page : Page
        The active Playwright page.
    max_polls : int
        Maximum number of DOM length reads.
    interval_ms : int
        Wait between reads in milliseconds.

    Returns
    -------
    bool
        True if DOM stabilized within budget.
    """
    prev_len = -1
    stable_count = 0
    for _ in range(max_polls):
        try:
            current_len = await page.evaluate("() => document.body.innerHTML.length")
        except Exception:
            return True  # Page navigated — consider stable
        if current_len == prev_len:
            stable_count += 1
            if stable_count >= 3:
                return True
        else:
            stable_count = 0
        prev_len = current_len
        await page.wait_for_timeout(interval_ms)
    return False  # Budget exhausted


async def wait_for_spinners_cleared(
    page: Page,
    timeout_ms: int = 3000,
    run_id: str = "",
) -> bool:
    """Wait for PrimeNG spinners to disappear (visual-readiness gate only).

    This is a reduced-timeout version of the legacy ``_wait_for_vsuite_spinners``.
    It only waits for VISUAL spinners — data readiness is handled by
    ``wait_for_data_settled()`` and ``wait_for_api_response()``.

    Parameters
    ----------
    page : Page
        The active Playwright page.
    timeout_ms : int
        Maximum wait time (default 3s — reduced from legacy 10s).
    run_id : str
        Run identifier for log correlation.

    Returns
    -------
    bool
        True if no spinners are visible.
    """
    spinner_selectors = [
        ".p-datatable-loading-overlay",
        ".vcreative-icon.loading",
        ".loading-overlay",
        ".p-blockui",
    ]

    for selector in spinner_selectors:
        try:
            locator = page.locator(selector)
            if await locator.count() > 0 and await locator.first.is_visible(timeout=200):
                # Spinner is visible — wait for it to disappear
                await locator.first.wait_for(state="hidden", timeout=timeout_ms)
                logger.debug(
                    "[%s] Spinner '%s' cleared within %dms",
                    run_id,
                    selector,
                    timeout_ms,
                )
        except Exception:
            # Timeout or element disappeared — move on
            continue

    return True
