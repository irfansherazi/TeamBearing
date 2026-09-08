"""
vQA — Table Search Macro Tool
================================
Module: backend/engine/tools/table_search.py

Provides ``execute_table_search`` — a deterministic Playwright macro that
finds and fills the table search input, presses Enter, and waits for the
table to re-render.

Problem
-------
The agent gets stuck in an infinite scroll loop when searching for a
specific row (e.g., "a spot named 'Demo'" or "status 'Needs Producing'").
It scrolls 5-10 times, ignores soft guardrails, and eventually times out.
The root cause: **PrimeNG tables are paginated** — scrolling only moves
the viewport within the current page of results; it does NOT load more rows.

Solution
--------
``execute_table_search`` provides a single atomic tool that:

1. Locates the table search input (multiple selector strategies)
2. Clears any existing search text
3. Fills the new search query
4. Presses Enter to trigger the filter
5. Waits for the table to re-render (spinners + network idle)
6. Returns the result to the LLM

The agent can then use ``scoped_click`` to interact with the filtered row.

Search Input Selectors
----------------------
The tool tries multiple selector strategies in priority order,
covering vSuite's various search input patterns:

1. ``input[placeholder*='Search']``  — standard placeholder text
2. ``input.p-inputtext``             — PrimeNG input component
3. ``input[type='text']``            — generic text input inside filter bars
4. ``.p-datatable-filter input``     — PrimeNG inline column filter
5. ``[aria-label*='Search']``        — ARIA-labelled search inputs

Dependencies
------------
  - ``playwright.async_api.Page``                    — live browser page
  - ``backend.browser.network_sync``                 — wait_for_spinners_cleared,
                                                       wait_for_data_settled

See Also
--------
  - ``backend/engine/tools/scoped_action.py``  — row-scoped click after search
  - ``backend/engine/workers/table_worker.py`` — consumes this tool
"""

from __future__ import annotations

import logging
from typing import Any

from playwright.async_api import Page
from playwright.async_api import TimeoutError as PlaywrightTimeout

logger = logging.getLogger(__name__)


# Priority-ordered search input selectors covering vSuite patterns.
_SEARCH_SELECTORS: list[str] = [
    "input[placeholder*='Search' i]",  # Placeholder contains "Search" (case-insensitive)
    "input[placeholder*='search' i]",  # Lowercase variant
    "input[placeholder*='Filter' i]",  # Filter variant
    ".p-inputtext[placeholder*='Search' i]",  # PrimeNG input with placeholder
    "input.p-inputtext",  # PrimeNG input class
    "[aria-label*='Search' i]",  # ARIA-labelled search
    "[aria-label*='Filter' i]",  # ARIA-labelled filter
    ".p-datatable-header input",  # Input inside PrimeNG table header
    ".po-filter-bar input",  # vSuite custom filter bar
    "input[type='search']",  # HTML5 search input type
]


async def execute_table_search(
    page: Page,
    search_query: str,
    *,
    search_selectors: list[str] | None = None,
    timeout_ms: int = 5000,
    network_wait_ms: int = 8000,
    clear_first: bool = True,
) -> dict[str, Any]:
    """
    Search a PrimeNG/vSuite table by filling the search input and
    waiting for the table to re-render.

    This is a deterministic macro — no LLM reasoning is needed.  The
    agent calls this tool instead of scrolling when it cannot find a
    specific row in the visible table data.

    Processing:
      1. Find the table search input (tries multiple selectors)
      2. Clear any existing search text (if clear_first=True)
      3. Fill the search query
      4. Press Enter to trigger the filter
      5. Wait for spinners to clear + network to settle
      6. Return success/failure with metadata

    Args
    ----
    page : Page
        The active Playwright page.

    search_query : str
        The text to search for in the table.
        Examples: ``"Demo"``, ``"Needs Producing"``, ``"VC-12345"``

    search_selectors : list[str] | None
        Override the default search input selector list.

    timeout_ms : int
        Playwright timeout for input lookups (default 5000 ms).

    network_wait_ms : int
        Maximum wait for the table to re-render after search
        (default 8000 ms — PrimeNG tables may debounce).

    clear_first : bool
        If True, clear any existing search text before filling.
        Default True.

    Returns
    -------
    dict[str, Any]
        Result dict with keys:
          - ``success`` (bool): True if the search was executed.
          - ``error`` (str): Empty on success, descriptive on failure.
          - ``search_query`` (str): The query that was searched.
          - ``matched_selector`` (str): Which input selector worked.
          - ``table_refreshed`` (bool): Whether the table data settled.

    Example
    -------
    >>> result = await execute_table_search(page, "Needs Producing")
    >>> result["success"]
    True
    >>> result["table_refreshed"]
    True
    """
    if not search_query or not search_query.strip():
        return {
            "success": False,
            "error": (
                "table_search: search_query is empty. You MUST provide "
                "the text you are looking for (e.g., a spot name, status, "
                "client name, or order ID)."
            ),
            "search_query": search_query,
            "matched_selector": "",
            "table_refreshed": False,
        }

    selectors = search_selectors or _SEARCH_SELECTORS

    # ── Phase 1: Find the search input ────────────────────────────────
    matched_selector: str = ""
    search_input = None

    for css_sel in selectors:
        try:
            locator = page.locator(css_sel)
            count = await locator.count()
            if count > 0:
                # Verify the first match is visible and enabled
                first = locator.first
                is_visible = await first.is_visible(timeout=1000)
                if is_visible:
                    search_input = first
                    matched_selector = css_sel
                    logger.info(
                        "table_search: found search input with selector '%s'",
                        css_sel,
                    )
                    break
        except Exception as e:
            logger.debug(
                "table_search: selector '%s' lookup failed: %s",
                css_sel,
                str(e)[:80],
            )
            continue

    if search_input is None:
        return {
            "success": False,
            "error": (
                "table_search: no search input found on the current page. "
                f"Tried selectors: {', '.join(selectors[:5])}... "
                "The table may not have a search bar. Try using "
                "pagination ('Next Page') to find the target row, "
                "or check if there is a column filter input instead."
            ),
            "search_query": search_query,
            "matched_selector": "",
            "table_refreshed": False,
        }

    # ── Phase 2: Clear existing text and fill the search query ────────
    try:
        # Click to focus the input
        await search_input.click(timeout=timeout_ms)

        # Clear existing text
        if clear_first:
            await search_input.fill("", timeout=timeout_ms)
            await page.wait_for_timeout(100)

        # Fill the search query
        await search_input.fill(search_query, timeout=timeout_ms)

        logger.info(
            "table_search: filled search input with '%s'",
            search_query[:50],
        )

    except PlaywrightTimeout:
        return {
            "success": False,
            "error": (
                f"table_search: found search input ('{matched_selector}') "
                f"but timed out while filling '{search_query}'. "
                f"The input may be disabled or read-only."
            ),
            "search_query": search_query,
            "matched_selector": matched_selector,
            "table_refreshed": False,
        }
    except Exception as e:
        return {
            "success": False,
            "error": (f"table_search: error filling search input: {str(e)[:200]}"),
            "search_query": search_query,
            "matched_selector": matched_selector,
            "table_refreshed": False,
        }

    # ── Phase 3: Press Enter to trigger the filter ────────────────────
    try:
        await page.keyboard.press("Enter")
        logger.info("table_search: pressed Enter to trigger filter")
    except Exception as e:
        logger.warning(
            "table_search: Enter key press failed (%s) — continuing anyway (some inputs auto-filter on type)",
            str(e)[:80],
        )

    # ── Phase 4: Wait for the table to re-render ──────────────────────
    # Two-phase wait:
    #   1. Spinners clear (visual readiness) — max 3s
    #   2. Network settles (data readiness)  — max configurable
    table_refreshed = False

    try:
        from backend.browser.network_sync import (
            wait_for_data_settled,
            wait_for_spinners_cleared,
        )

        # Phase 4a: Wait for spinners
        await wait_for_spinners_cleared(page, timeout_ms=3000)

        # Phase 4b: Wait for network/DOM to settle
        table_refreshed = await wait_for_data_settled(
            page,
            timeout_ms=network_wait_ms,
        )

        logger.info(
            "table_search: table %s after search for '%s'",
            "refreshed" if table_refreshed else "may still be loading",
            search_query[:50],
        )

    except Exception as e:
        logger.warning(
            "table_search: network sync failed (%s) — proceeding with a fixed wait",
            str(e)[:80],
        )
        await page.wait_for_timeout(2000)

    return {
        "success": True,
        "error": "",
        "search_query": search_query,
        "matched_selector": matched_selector,
        "table_refreshed": table_refreshed,
    }


async def clear_table_search(
    page: Page,
    *,
    search_selectors: list[str] | None = None,
    timeout_ms: int = 5000,
    network_wait_ms: int = 5000,
) -> dict[str, Any]:
    """
    Clear the table search input and wait for the table to show all rows.

    Call this after a search to reset the table back to its unfiltered state.

    Args
    ----
    page : Page
        The active Playwright page.
    search_selectors : list[str] | None
        Override the search input selectors.
    timeout_ms : int
        Input interaction timeout.
    network_wait_ms : int
        Table refresh wait timeout.

    Returns
    -------
    dict[str, Any]
        Result dict with ``success``, ``error``, metadata.
    """
    selectors = search_selectors or _SEARCH_SELECTORS

    for css_sel in selectors:
        try:
            locator = page.locator(css_sel).first
            if await locator.is_visible(timeout=1000):
                await locator.fill("", timeout=timeout_ms)
                await page.keyboard.press("Enter")

                try:
                    from backend.browser.network_sync import (
                        wait_for_data_settled,
                        wait_for_spinners_cleared,
                    )

                    await wait_for_spinners_cleared(page, timeout_ms=3000)
                    await wait_for_data_settled(page, timeout_ms=network_wait_ms)
                except Exception:
                    await page.wait_for_timeout(2000)

                logger.info(
                    "clear_table_search: cleared search input ('%s')",
                    css_sel,
                )
                return {
                    "success": True,
                    "error": "",
                    "matched_selector": css_sel,
                }
        except Exception:
            continue

    return {
        "success": False,
        "error": "clear_table_search: no visible search input found to clear.",
        "matched_selector": "",
    }
