"""
vQA — Scoped Action Tool
==========================
Module: backend/engine/tools/scoped_action.py

Provides ``execute_scoped_click`` — a Playwright interaction tool
designed for **composite tables and nested UI containers** where the
same link/button text appears in multiple rows.

Problem
-------
In vSuite's Voice Request workflow, a Production Orders table may show
multiple jobs, each with an "Add Voice", "Edit", or "Delete" link.
A standard ``page.get_by_text("Add Voice")`` causes a STRICT_MODE
violation because Playwright finds 3+ matches.  The agent cannot
distinguish which "Add Voice" belongs to which job row.

Solution
--------
``execute_scoped_click`` uses Playwright's **locator filtering** to
first isolate a container (row/card/section) that contains unique
identifying text (``scope_text``), then clicks a target element
strictly inside that container (``target_text``).

This is semantically equivalent to::

    page.locator(".po-row, tr, .job-container")
        .filter(has_text="JOB 1")
        .get_by_text("Add Voice")
        .click()

Container Selectors
-------------------
The tool searches across multiple structural patterns used in vSuite:

  - ``tr``                — Standard HTML table rows
  - ``.po-row``           — Production Orders custom row components
  - ``.job-container``    — Voice Request job containers
  - ``.po-card``          — Card-layout rows
  - ``.p-datatable-row``  — PrimeNG DataTable rows
  - ``[role='row']``      — ARIA row role (accessibility-compliant)

Return Contract
---------------
Returns a dict with:
  - ``success: bool``    — whether the click was executed
  - ``error: str``       — empty on success, descriptive on failure

On failure, the error string is designed to be **fed back to the LLM**
so it can adjust its scope_text or target_text on the next attempt.

Dependencies
------------
  - ``playwright.async_api.Page`` — live browser page
  - No LLM calls — deterministic Playwright interaction.

See Also
--------
  - ``backend/engine/workers/table_worker.py`` — consumes this tool
  - ``backend/engine/schemas.py``              — PlannerAction.container_selector
"""

from __future__ import annotations

import logging
from typing import Any

from playwright.async_api import Page
from playwright.async_api import TimeoutError as PlaywrightTimeout

logger = logging.getLogger(__name__)

# Priority-ordered container selectors covering all vSuite table patterns.
# The tool tries each selector in order and picks the first one that
# contains the scope_text.
_CONTAINER_SELECTORS: list[str] = [
    "tr",  # Standard HTML table rows
    ".po-row",  # Production Orders custom row component
    ".job-container",  # Voice Request job containers
    ".po-card",  # Card-layout rows
    ".p-datatable-row",  # PrimeNG DataTable rows
    "[role='row']",  # ARIA row role
    ".p-panel",  # PrimeNG panel sections
    ".p-accordion-content",  # Accordion content sections
    "div[class*='row']",  # Generic row-like div fallback
]


async def execute_scoped_click(
    page: Page,
    scope_text: str,
    target_text: str,
    *,
    container_selectors: list[str] | None = None,
    timeout_ms: int = 5000,
    exact_scope: bool = False,
    exact_target: bool = False,
) -> dict[str, Any]:
    """
    Click an element inside a specific container identified by its text.

    Uses Playwright's ``.filter(has_text=...)`` to isolate a single
    container row, then ``.get_by_text(...)`` scoped within that
    container to click the exact target.

    This eliminates STRICT_MODE violations when the same button text
    (e.g. "Add Voice", "Edit", "Delete") appears in multiple table rows.

    Args
    ----
    page : Page
        The active Playwright page.

    scope_text : str
        Unique identifying text within the target container/row.
        This should be text that ONLY appears in the specific row you
        want to interact with — a Job Name, Order ID, Client Name, etc.
        Example: ``"JOB 1"``, ``"VC-12345"``, ``"Bob's Radio Spot"``

    target_text : str
        The button/link text to click INSIDE the scoped container.
        Example: ``"Add Voice"``, ``"Edit"``, ``"Delete"``, ``"View"``

    container_selectors : list[str] | None
        Override the default container selector priority list.
        Default: ``_CONTAINER_SELECTORS`` (tr, .po-row, .job-container, ...)

    timeout_ms : int
        Playwright timeout for element lookups (default 5000 ms).

    exact_scope : bool
        If True, use exact text matching for scope_text.
        Default False = substring matching.

    exact_target : bool
        If True, use exact text matching for target_text.
        Default False = substring matching.

    Returns
    -------
    dict[str, Any]
        Result dict with keys:
          - ``success`` (bool): True if the click was executed.
          - ``error`` (str): Empty on success, descriptive on failure.
          - ``scope_text`` (str): The scope_text that was used.
          - ``target_text`` (str): The target_text that was clicked.
          - ``container_selector`` (str): Which CSS selector matched.
          - ``container_count`` (int): How many containers matched scope_text.

    Example
    -------
    >>> result = await execute_scoped_click(
    ...     page=page,
    ...     scope_text="JOB 1",
    ...     target_text="Add Voice",
    ... )
    >>> result["success"]
    True
    """
    if not scope_text or not scope_text.strip():
        return {
            "success": False,
            "error": (
                "scoped_click: scope_text is empty. You MUST provide unique "
                "identifying text from the target row (e.g., a Job Name, "
                "Order ID, or Client Name) to disambiguate which row to "
                "interact with."
            ),
            "scope_text": scope_text,
            "target_text": target_text,
            "container_selector": "",
            "container_count": 0,
        }

    if not target_text or not target_text.strip():
        return {
            "success": False,
            "error": (
                "scoped_click: target_text is empty. You MUST provide the "
                "button or link text to click inside the scoped row "
                "(e.g., 'Add Voice', 'Edit', 'Delete')."
            ),
            "scope_text": scope_text,
            "target_text": target_text,
            "container_selector": "",
            "container_count": 0,
        }

    selectors = container_selectors or _CONTAINER_SELECTORS

    # ── Phase 1: Find the matching container ──────────────────────────
    matched_selector: str = ""
    matched_count: int = 0

    for css_sel in selectors:
        try:
            candidates = page.locator(css_sel).filter(has_text=scope_text)
            count = await candidates.count()
            if count > 0:
                matched_selector = css_sel
                matched_count = count
                logger.info(
                    "scoped_click: found %d container(s) matching '%s' with selector '%s'",
                    count,
                    scope_text[:50],
                    css_sel,
                )
                break
        except Exception as e:
            logger.debug(
                "scoped_click: selector '%s' lookup failed: %s",
                css_sel,
                str(e)[:80],
            )
            continue

    if not matched_selector:
        return {
            "success": False,
            "error": (
                f"scoped_click: no container found containing "
                f"scope_text='{scope_text}'. Tried selectors: "
                f"{', '.join(selectors[:5])}... "
                f"The scope_text must match visible text in a table row "
                f"or container. Check the INTERACTIVE ELEMENTS list for "
                f"the exact text."
            ),
            "scope_text": scope_text,
            "target_text": target_text,
            "container_selector": "",
            "container_count": 0,
        }

    # ── Phase 2: Isolate the specific container ───────────────────────
    container = page.locator(matched_selector).filter(has_text=scope_text).first

    # ── Phase 3: Click the target inside the container ────────────────
    try:
        target = container.get_by_text(target_text, exact=exact_target).first
        await target.scroll_into_view_if_needed(timeout=timeout_ms)
        await target.click(timeout=timeout_ms)

        logger.info(
            "scoped_click: SUCCESS — clicked '%s' inside container matching '%s' (selector='%s')",
            target_text,
            scope_text[:50],
            matched_selector,
        )

        return {
            "success": True,
            "error": "",
            "scope_text": scope_text,
            "target_text": target_text,
            "container_selector": matched_selector,
            "container_count": matched_count,
        }

    except PlaywrightTimeout:
        return {
            "success": False,
            "error": (
                f"scoped_click: found container matching scope_text="
                f"'{scope_text}' (selector='{matched_selector}'), but "
                f"target_text='{target_text}' was NOT FOUND inside it "
                f"(timed out after {timeout_ms}ms). "
                f"The button/link text may be different — check the "
                f"INTERACTIVE ELEMENTS list for the exact text within "
                f"that row."
            ),
            "scope_text": scope_text,
            "target_text": target_text,
            "container_selector": matched_selector,
            "container_count": matched_count,
        }

    except Exception as e:
        return {
            "success": False,
            "error": (
                f"scoped_click: unexpected error clicking '{target_text}' "
                f"inside container matching '{scope_text}': "
                f"{str(e)[:200]}"
            ),
            "scope_text": scope_text,
            "target_text": target_text,
            "container_selector": matched_selector,
            "container_count": matched_count,
        }


async def execute_scoped_fill(
    page: Page,
    scope_text: str,
    target_label: str,
    fill_value: str,
    *,
    container_selectors: list[str] | None = None,
    timeout_ms: int = 5000,
) -> dict[str, Any]:
    """
    Fill an input inside a specific container identified by its text.

    Same scoping logic as ``execute_scoped_click`` but targets an input
    by its ARIA label and fills it with a value.

    Args
    ----
    page : Page
        The active Playwright page.
    scope_text : str
        Unique identifying text within the target container/row.
    target_label : str
        The ARIA label of the input to fill.
    fill_value : str
        The value to type into the input.
    container_selectors : list[str] | None
        Override the default container selector priority list.
    timeout_ms : int
        Playwright timeout (default 5000 ms).

    Returns
    -------
    dict[str, Any]
        Result dict with ``success``, ``error``, metadata.
    """
    selectors = container_selectors or _CONTAINER_SELECTORS

    matched_selector = ""
    for css_sel in selectors:
        try:
            candidates = page.locator(css_sel).filter(has_text=scope_text)
            count = await candidates.count()
            if count > 0:
                matched_selector = css_sel
                break
        except Exception:
            continue

    if not matched_selector:
        return {
            "success": False,
            "error": (f"scoped_fill: no container found containing scope_text='{scope_text}'."),
            "scope_text": scope_text,
            "target_label": target_label,
            "fill_value": fill_value,
        }

    container = page.locator(matched_selector).filter(has_text=scope_text).first

    try:
        target = container.get_by_label(target_label).first
        await target.fill(fill_value, timeout=timeout_ms)

        logger.info(
            "scoped_fill: SUCCESS — filled '%s'='%s' inside container '%s'",
            target_label,
            fill_value[:50],
            scope_text[:50],
        )

        return {
            "success": True,
            "error": "",
            "scope_text": scope_text,
            "target_label": target_label,
            "fill_value": fill_value,
        }

    except Exception as e:
        return {
            "success": False,
            "error": (f"scoped_fill: error filling '{target_label}' inside container '{scope_text}': {str(e)[:200]}"),
            "scope_text": scope_text,
            "target_label": target_label,
            "fill_value": fill_value,
        }
