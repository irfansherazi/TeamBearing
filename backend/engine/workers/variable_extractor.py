"""
vQA — Extract_And_Store_Variable Tool
=======================================
Module: backend/engine/workers/variable_extractor.py

Provides the ``extract_and_store_variable`` async function that Workers
invoke to scrape dynamic values from the live browser page and store
them in the ``global_variables`` field of ``VQAState``.

Architecture Context
--------------------
In the Supervisor-Worker hierarchy, the Supervisor uses angle-bracket
tokens (e.g. ``<ORDER_ID>``, ``<SPOT_NAME>``) in AC steps that reference
values only available at runtime.  Workers call this tool after a
preceding step produces the value, and the Supervisor interpolates the
token in the next step's Intent.

Extraction Strategies
---------------------
Three strategies are supported, matching the common ways dynamic values
appear in vSuite's Angular UI:

    ``css_selector``
        Locates a single element by CSS selector and reads its
        ``textContent``.  Best for dedicated value containers like
        ``#order-number``, ``.confirmation-code``, or
        ``span.spot-id-label``.

    ``text_pattern``
        Reads the full ``<body>`` text content and applies a Python
        regex with one capture group.  Best for extracting values
        embedded in prose (e.g. "Order #VC-12345 created successfully").

    ``aria_label``
        Locates a form input by its ARIA label and reads its current
        ``inputValue``.  Best for pre-filled inputs whose value was
        assigned by the application (e.g. auto-generated reference
        numbers in read-only textboxes).

Return Contract
---------------
Returns a dict matching the ``_merge_dicts`` reducer on ``VQAState``:

    ``{"global_variables": {"VARIABLE_NAME": "scraped_value"}}``

The caller (Worker node) returns this dict directly as part of its
state update, and LangGraph merges the new key into the existing
``global_variables`` without overwriting other entries.

Dependencies
------------
  - ``playwright.async_api.Page`` — live browser page
  - No LLM calls — this is a deterministic Python extraction tool.

See Also
--------
  - ``backend/engine/state.py``      — ``global_variables`` field definition
  - ``backend/engine/supervisor.py`` — token interpolation (Phase 2)
"""

from __future__ import annotations

import logging
import re
from typing import Any

from playwright.async_api import Page

logger = logging.getLogger(__name__)


async def extract_and_store_variable(
    page: Page,
    variable_name: str,
    extraction_strategy: str,
    selector_or_pattern: str,
    *,
    timeout_ms: int = 5000,
) -> dict[str, Any]:
    """
    Scrape a dynamic value from the live browser page and format it
    for storage in ``VQAState.global_variables``.

    This is a **deterministic Python tool** — no LLM calls are made.
    It reads the DOM directly via Playwright and returns a state-update
    dict that the calling Worker node includes in its return value.

    Args
    ----
    page : Page
        The active Playwright page to extract from.

    variable_name : str
        The token name to store the value under.  Should be uppercase
        snake_case (e.g. ``"ORDER_ID"``, ``"SPOT_NAME"``).
        This becomes the key in ``global_variables``.

    extraction_strategy : str
        One of:
          - ``"css_selector"``  — locate by CSS, read ``textContent``
          - ``"text_pattern"``  — regex on full body text (1 capture group)
          - ``"aria_label"``    — locate by label, read ``inputValue``

    selector_or_pattern : str
        - For ``css_selector``:  a CSS selector string
          (e.g. ``"#order-number"``, ``"span.spot-id"``)
        - For ``text_pattern``:  a Python regex with exactly one
          capture group (e.g. ``r"Order #(\\w+-\\d+)"``)
        - For ``aria_label``:    the ARIA label text
          (e.g. ``"Order Number"``, ``"Reference Code"``)

    timeout_ms : int
        Playwright timeout for element lookup (default 5000 ms).
        Only applies to ``css_selector`` and ``aria_label`` strategies.

    Returns
    -------
    dict[str, Any]
        State update dict:
        ``{"global_variables": {variable_name: "<extracted_value>"}}``

        The caller returns this dict directly and LangGraph's
        ``_merge_dicts`` reducer merges the new key into the existing
        ``global_variables`` without overwriting other entries.

    Raises
    ------
    ValueError
        If ``extraction_strategy`` is not one of the supported values,
        or if the extraction yields an empty/None result.

    Example
    -------
    >>> # In a Worker node:
    >>> result = await extract_and_store_variable(
    ...     page=page,
    ...     variable_name="ORDER_ID",
    ...     extraction_strategy="css_selector",
    ...     selector_or_pattern="#order-number",
    ... )
    >>> # result == {"global_variables": {"ORDER_ID": "VC-12345"}}
    >>> return result  # LangGraph merges into state
    """
    if not variable_name:
        raise ValueError("variable_name must be a non-empty string (e.g. 'ORDER_ID', 'SPOT_NAME')")
    if not selector_or_pattern:
        raise ValueError("selector_or_pattern must be a non-empty string (CSS selector, regex pattern, or ARIA label)")

    value: str | None = None

    # ── Strategy 1: CSS Selector → textContent ────────────────────────
    if extraction_strategy == "css_selector":
        element = page.locator(selector_or_pattern)
        raw = await element.text_content(timeout=timeout_ms)
        value = raw.strip() if raw else None

        logger.info(
            "extract_variable [css_selector]: '%s' → selector='%s' → '%s'",
            variable_name,
            selector_or_pattern,
            (value or "")[:80],
        )

    # ── Strategy 2: Text Pattern → regex capture group ────────────────
    elif extraction_strategy == "text_pattern":
        body_text = await page.text_content("body", timeout=timeout_ms)
        if body_text:
            match = re.search(selector_or_pattern, body_text)
            if match and match.lastindex and match.lastindex >= 1:
                value = match.group(1).strip()
            else:
                value = None

        logger.info(
            "extract_variable [text_pattern]: '%s' → pattern='%s' → '%s'",
            variable_name,
            selector_or_pattern[:60],
            (value or "")[:80],
        )

    # ── Strategy 3: ARIA Label → inputValue ───────────────────────────
    elif extraction_strategy == "aria_label":
        element = page.get_by_label(selector_or_pattern)
        raw = await element.input_value(timeout=timeout_ms)
        value = raw.strip() if raw else None

        logger.info(
            "extract_variable [aria_label]: '%s' → label='%s' → '%s'",
            variable_name,
            selector_or_pattern,
            (value or "")[:80],
        )

    else:
        raise ValueError(
            f"Unknown extraction_strategy: '{extraction_strategy}'. "
            f"Supported: 'css_selector', 'text_pattern', 'aria_label'."
        )

    # ── Validate extraction result ────────────────────────────────────
    if not value:
        raise ValueError(
            f"extract_and_store_variable: could not extract "
            f"'{variable_name}' using strategy='{extraction_strategy}', "
            f"selector_or_pattern='{selector_or_pattern}'. "
            f"The element was not found, returned empty text, or the "
            f"regex pattern did not match any content on the page."
        )

    logger.info(
        "extract_variable: stored '%s' = '%s' in global_variables",
        variable_name,
        value[:80],
    )

    return {"global_variables": {variable_name: value}}
