"""
vQA — Set-of-Marks (SoM) Visual DOM Mapper
============================================
Module: backend/browser/set_of_marks.py

Implements the "Set-of-Marks" (SoM) prompting technique for browser agents.
Instead of asking the LLM to hallucinate CSS selectors from a screenshot,
SoM overlays numbered bounding boxes on every interactive element, takes a
screenshot of the annotated page, and returns a strict mapping of
  { box_id (int) → css_selector (str) }

The planner can then output {"action": "click", "box_id": 12} and the
executor resolves it to the exact CSS selector — zero hallucination.

Architecture
------------
  planner_node
    └─▶ capture_set_of_marks(page)
          ├─▶ _inject_som_overlay(page)  → JS injects numbered boxes + stamps data
          ├─▶ capture_screenshot_b64(page)  → annotated image
          ├─▶ _extract_som_map(page)  → {id: selector} dict from stamped data
          └─▶ _cleanup_som_overlay(page)   → remove injected DOM elements

SoM is activated when:
  - The agent has been on the same AC step for 3+ planning iterations
  - OR the planner is in HEALING TIER 3 (retry_count >= 3)
  - OR the run config has `use_som: true`

It is NOT run on every iteration — the overhead of JS injection + full
screenshot rebuild is ~200–400ms per call.

Selector Generation Strategy
-----------------------------
For each interactive element, the JS generates the MOST SPECIFIC unique
CSS selector using this priority:
  1. data-testid / data-cy / data-vqa  (test attributes — always unique)
  2. id attribute (if unique on page)
  3. Tag + class fingerprint (e.g., "button.po-new-request-btn")
  4. Nth-child positional fallback (e.g., "ul > li:nth-child(3) > button")

This mirrors what human engineers write — stable, semantic selectors first,
positional fallback only when nothing else distinguishes the element.

Usage (in planner.py)
---------------------
    from backend.browser.set_of_marks import capture_set_of_marks

    if _should_use_som(state):
        som_screenshot_b64, som_map = await capture_set_of_marks(page)
        # Store in state for executor resolution
        state_updates["som_element_map"] = som_map
        # Send annotated screenshot to LLM instead of regular screenshot
        screenshot_b64 = som_screenshot_b64

Usage (in executor.py)
----------------------
    # Resolve box_id → css_selector if planner used SoM mode
    if action.get("box_id") is not None:
        som_map = state.get("som_element_map", {})
        box_id = str(action["box_id"])
        css_sel = som_map.get(box_id)
        if css_sel:
            action = {**action, "strategy": "css_selector", "name": css_sel}
        else:
            raise ValueError(f"SoM box_id {box_id} not found in element map")
"""

import base64
import logging
from typing import Any

logger = logging.getLogger(__name__)

# ── Tuning constants ──────────────────────────────────────────────────────────

# Maximum number of elements to label. Above this the screenshot gets noisy.
_MAX_SOM_ELEMENTS = 50

# Box styling — chosen to be visible on both light and dark backgrounds.
_BOX_COLOR = "rgba(220, 38, 38, 0.85)"  # Red-600, semi-transparent
_LABEL_BG = "rgba(220, 38, 38, 1.0)"  # Solid red for the number chip
_LABEL_TEXT_COLOR = "#ffffff"
_BOX_BORDER = "2px solid rgba(220, 38, 38, 0.95)"

# DOM attribute written onto each element so the extractor can read back
# the selector that was generated for it.
_SOM_DATA_ATTR = "data-vqa-som-id"
_SOM_SEL_ATTR = "data-vqa-som-sel"

# CSS class added to the overlay container div
_OVERLAY_CLASS = "__vqa_som_overlay__"


# ── JavaScript: selector generation ──────────────────────────────────────────

_JS_GENERATE_SELECTOR = """
(el) => {
  // Priority 1: data-testid / data-cy / data-vqa-id (test attributes — always unique)
  for (const attr of ['data-testid', 'data-cy', 'data-vqa-id', 'data-som-id']) {
    const val = el.getAttribute(attr);
    if (val) return `[${attr}="${val}"]`;
  }

  // Priority 2: id (verify uniqueness)
  if (el.id) {
    const candidates = document.querySelectorAll(`#${CSS.escape(el.id)}`);
    if (candidates.length === 1) return `#${CSS.escape(el.id)}`;
  }

  // Priority 3: tag + significant class
  const tag = el.tagName.toLowerCase();
  const significantClasses = Array.from(el.classList)
    .filter(c => !c.startsWith('ng-') && !c.startsWith('p-') && c.length > 2)
    .slice(0, 3);
  if (significantClasses.length > 0) {
    const sel = tag + '.' + significantClasses.join('.');
    const candidates = document.querySelectorAll(sel);
    if (candidates.length === 1) return sel;
  }

  // Priority 4: Include PrimeNG component class (p-select, p-button, etc.)
  const primeClasses = Array.from(el.classList)
    .filter(c => c.startsWith('p-') && c.length > 3)
    .slice(0, 2);
  if (primeClasses.length > 0) {
    const sel = tag + '.' + primeClasses.join('.');
    const candidates = document.querySelectorAll(sel);
    if (candidates.length === 1) return sel;
  }

  // Priority 5: nth-child positional fallback
  function getPath(node) {
    if (!node || node === document.body) return 'body';
    // Pierce shadow boundaries when climbing the tree
    const parent = node.parentElement || (node.getRootNode && node.getRootNode().host);
    if (!parent) return node.tagName.toLowerCase();
    const children = parent.shadowRoot ? Array.from(parent.shadowRoot.children) : Array.from(parent.children);
    const idx = children.indexOf(node) + 1;
    return getPath(parent) + '>' + node.tagName.toLowerCase() + ':nth-child(' + idx + ')';
  }

  }
  return getPath(el);
}
"""


# ── JavaScript: inject numbered overlay ──────────────────────────────────────

_JS_INJECT_OVERLAY = f"""
() => {{
  // Remove any previous overlay
  document.querySelectorAll('.{_OVERLAY_CLASS}').forEach(el => el.remove());
  document.querySelectorAll('[{_SOM_DATA_ATTR}]').forEach(el => {{
    el.removeAttribute('{_SOM_DATA_ATTR}');
    el.removeAttribute('{_SOM_SEL_ATTR}');
  }});

  // Selector generator (inline — same logic as _JS_GENERATE_SELECTOR)
  function generateSelector(el) {{
    for (const attr of ['data-testid', 'data-cy', 'data-vqa-id']) {{
      const val = el.getAttribute(attr);
      if (val) return `[${{attr}}="${{val}}"]`;
    }}
    if (el.id) {{
      try {{
        const candidates = document.querySelectorAll('#' + CSS.escape(el.id));
        if (candidates.length === 1) return '#' + CSS.escape(el.id);
      }} catch(e) {{}}
    }}
    const tag = el.tagName.toLowerCase();
    const sigClasses = Array.from(el.classList)
      .filter(c => !c.startsWith('ng-') && c.length > 2).slice(0, 3);
    if (sigClasses.length > 0) {{
      const sel = tag + '.' + sigClasses.join('.');
      try {{
        if (document.querySelectorAll(sel).length === 1) return sel;
      }} catch(e) {{}}
    }}
    function getPath(node) {{
      if (!node || node === document.body) return 'body';
      // Pierce shadow boundaries when climbing the tree
      const parent = node.parentElement || (node.getRootNode && node.getRootNode().host);
      if (!parent) return node.tagName.toLowerCase();
      const children = parent.shadowRoot ? Array.from(parent.shadowRoot.children) : Array.from(parent.children);
      const idx = children.indexOf(node) + 1;
      return getPath(parent) + '>' + node.tagName.toLowerCase() + ':nth-child(' + idx + ')';
    }}

    return getPath(el);
  }}

  function queryAllPiercing(selector, root = document) {{
    let results = Array.from(root.querySelectorAll(selector));
    const all = root.querySelectorAll('*');
    for (const el of all) {{
      if (el.shadowRoot) {{
        results = results.concat(queryAllPiercing(selector, el.shadowRoot));
      }}
    }}
    return results;
  }}

  const INTERACTIVE_SELECTOR = [
    'button:not([disabled]):not([aria-hidden="true"])',
    'a[href]:not([aria-hidden="true"])',
    'input:not([type="hidden"]):not([disabled])',
    'select:not([disabled])',
    'textarea:not([disabled])',
    '[role="button"]:not([disabled]):not([aria-hidden="true"])',
    '[role="tab"]:not([aria-hidden="true"])',
    '[role="checkbox"]',
    '[role="radio"]',
    '[role="switch"]',
    '[role="combobox"]:not([aria-hidden="true"])',
    '[role="option"]',
    '[role="menuitem"]',
    'p-select:not([aria-hidden="true"])',
    'p-checkbox:not([disabled])',
    'p-button:not([disabled])',
  ].join(',');

  const elements = queryAllPiercing(INTERACTIVE_SELECTOR)
    .filter(el => {{
      // Must be visible in the viewport
      const rect = el.getBoundingClientRect();
      return rect.width > 0 && rect.height > 0 &&
             rect.top >= 0 && rect.left >= 0 &&
             rect.bottom <= (window.innerHeight + 200) &&
             rect.right <= (window.innerWidth + 200) &&
             window.getComputedStyle(el).visibility !== 'hidden' &&
             window.getComputedStyle(el).display !== 'none';
    }})
    .slice(0, {_MAX_SOM_ELEMENTS});

  const container = document.createElement('div');
  container.className = '{_OVERLAY_CLASS}';
  container.style.cssText = `
    position: fixed; top: 0; left: 0; width: 0; height: 0;
    z-index: 2147483647; pointer-events: none; overflow: visible;
  `;
  document.body.appendChild(container);

  const results = [];

  elements.forEach((el, idx) => {{
    const id = idx + 1;
    const sel = generateSelector(el);

    // Stamp the element with its SoM ID + selector for later readback
    el.setAttribute('{_SOM_DATA_ATTR}', String(id));
    el.setAttribute('{_SOM_SEL_ATTR}', sel);

    // Draw bounding box overlay
    const rect = el.getBoundingClientRect();
    const scrollX = window.scrollX;
    const scrollY = window.scrollY;

    // Box outline
    const box = document.createElement('div');
    box.style.cssText = `
      position: absolute;
      left: ${{rect.left + scrollX}}px;
      top: ${{rect.top + scrollY}}px;
      width: ${{rect.width}}px;
      height: ${{rect.height}}px;
      border: {_BOX_BORDER};
      border-radius: 3px;
      box-sizing: border-box;
      pointer-events: none;
    `;
    container.appendChild(box);

    // Number chip (top-left of box)
    const chip = document.createElement('div');
    chip.style.cssText = `
      position: absolute;
      left: ${{rect.left + scrollX - 2}}px;
      top: ${{rect.top + scrollY - 18}}px;
      background: {_LABEL_BG};
      color: {_LABEL_TEXT_COLOR};
      font: bold 11px/16px monospace;
      padding: 0 4px;
      border-radius: 3px 3px 3px 0;
      min-width: 18px;
      text-align: center;
      pointer-events: none;
      white-space: nowrap;
    `;
    chip.textContent = String(id);
    container.appendChild(chip);

    results.push({{ id, selector: sel }});
  }});

  return results;
}}
"""


# ── JavaScript: cleanup ──────────────────────────────────────────────────────

_JS_CLEANUP = f"""
() => {{
  document.querySelectorAll('.{_OVERLAY_CLASS}').forEach(el => el.remove());
  document.querySelectorAll('[{_SOM_DATA_ATTR}]').forEach(el => {{
    el.removeAttribute('{_SOM_DATA_ATTR}');
    el.removeAttribute('{_SOM_SEL_ATTR}');
  }});
}}
"""


# ── Public API ───────────────────────────────────────────────────────────────


async def capture_set_of_marks(
    page: Any,  # playwright Page
    *,
    cleanup: bool = True,
) -> tuple[str, dict[str, str]]:
    """
    Annotate the page with numbered boxes, screenshot it, return map.

    Workflow
    --------
    1. Inject JS overlay: draw numbered red boxes on all visible interactive elements.
    2. Stamp each element with ``data-vqa-som-id`` and ``data-vqa-som-sel``.
    3. Capture a screenshot of the annotated page.
    4. Read back the ``{id: selector}`` map from the stamped attributes.
    5. Optionally remove all injected DOM elements (default: yes).

    Args
    ----
    page : playwright.async_api.Page
        The live browser page.
    cleanup : bool
        If True (default), remove the overlay after the screenshot.
        Set to False in HITL mode so the user sees numbered boxes.

    Returns
    -------
    tuple[str, dict[str, str]]
        (screenshot_b64, element_map) where:
        - screenshot_b64: PNG screenshot as base64 string (annotated)
        - element_map: {str(box_id): css_selector} for all labeled elements
          e.g. {"1": "button#submit-order", "12": "p-select.po-col-duedaysCol"}

    Raises
    ------
    RuntimeError
        If the page is closed or JS injection fails fatally.
    """
    if page.is_closed():
        raise RuntimeError("capture_set_of_marks: page is already closed")

    # 1. Inject overlay and collect element data
    try:
        raw_results: list[dict] = await page.evaluate(_JS_INJECT_OVERLAY)
    except Exception as e:
        logger.error("SoM overlay injection failed: %s", e)
        raise RuntimeError(f"SoM overlay injection failed: {e}") from e

    if not raw_results:
        logger.warning("SoM: no interactive elements found on page — falling back to plain screenshot")
        screenshot_bytes = await page.screenshot(type="png", full_page=False)
        return base64.b64encode(screenshot_bytes).decode(), {}

    # Build the element map: box_id (str) → css_selector
    element_map: dict[str, str] = {
        str(item["id"]): item["selector"] for item in raw_results if item.get("id") and item.get("selector")
    }

    logger.info(
        "SoM: annotated %d interactive elements (%.0f%% of page)",
        len(element_map),
        100 * len(element_map) / max(len(raw_results), 1),
    )

    # 2. Capture annotated screenshot
    try:
        screenshot_bytes = await page.screenshot(type="png", full_page=False)
        screenshot_b64 = base64.b64encode(screenshot_bytes).decode()
    except Exception as e:
        logger.error("SoM: screenshot capture failed: %s", e)
        if cleanup:
            await _cleanup_overlay(page)
        raise RuntimeError(f"SoM screenshot failed: {e}") from e

    # 3. Cleanup overlay
    if cleanup:
        await _cleanup_overlay(page)

    return screenshot_b64, element_map


async def _cleanup_overlay(page: Any) -> None:
    """Remove the SoM overlay from the page. Best-effort — never raises."""
    try:
        await page.evaluate(_JS_CLEANUP)
    except Exception as e:
        logger.debug("SoM cleanup error (non-fatal): %s", e)


def resolve_box_id(
    action: dict,
    som_map: dict[str, str],
) -> dict:
    """
    Resolve a ``box_id`` action to a concrete ``css_selector`` action.

    Called by the executor when the planner emits ``{"action": "click", "box_id": 12}``.
    Looks up the CSS selector from the SoM element map and returns a new
    action dict with ``strategy: css_selector, name: <selector>``.

    Args
    ----
    action : dict
        The planned action from the LLM. May contain ``box_id`` (int or str).
    som_map : dict[str, str]
        The element map returned by ``capture_set_of_marks()``.
        Stored in ``VQAState.som_element_map``.

    Returns
    -------
    dict
        A new action dict with ``strategy`` and ``name`` populated.
        Returns the original action unchanged if ``box_id`` is not present.

    Raises
    ------
    ValueError
        If ``box_id`` is present but not found in ``som_map``.
    """
    box_id = action.get("box_id")
    if box_id is None:
        return action  # Not a SoM action — pass through unchanged

    key = str(box_id)
    css_selector = som_map.get(key)
    if not css_selector:
        available = ", ".join(sorted(som_map.keys(), key=lambda x: int(x) if x.isdigit() else 0)[:10])
        raise ValueError(
            f"SoM box_id '{box_id}' not found in element map. "
            f"Available IDs (first 10): [{available}]. "
            f"Re-run capture_set_of_marks() to refresh the map if the page changed."
        )

    resolved = {**action}
    resolved.pop("box_id", None)
    resolved["strategy"] = "css_selector"
    resolved["name"] = css_selector
    logger.info("SoM: resolved box [%s] → css_selector('%s')", key, css_selector[:80])
    return resolved


def should_activate_som(state: dict) -> bool:
    """
    Return True if the planner should use Set-of-Marks mode for this iteration.

    Activates on:
    - Healing tier 3 (retry_count >= 3) — LLM is stuck, SoM gives it a lifeline
    - 4+ planner iterations on the same AC step — signs of oscillation
    - Explicit ``use_som: true`` in run config
    - Consecutive repeat loop detected (action_repeat_count on same action >= 3)

    Does NOT activate on:
    - First attempt (retry_count == 0, iteration == 0) — avoid overhead on happy path
    - After a successful action (retry_count == 0) — save overhead
    """
    if state.get("use_som", False):
        return True

    retry_count = state.get("retry_count", 0)
    if retry_count >= 3:
        return True

    # Check planner iterations on this AC step specifically
    state.get("ac_step_index", 0)
    state.get("planner_iteration", 0)
    # Rough proxy: if we've been planning for 6+ steps since ac_step reset
    ac_step_action_fail = state.get("ac_step_action_fail_count", 0)
    if ac_step_action_fail >= 3:
        return True

    return False


def format_som_prompt_block(element_map: dict[str, str]) -> str:
    """
    Format the SoM element map as a prompt injection block.

    The planner receives this block instead of (or alongside) the
    regular accessible element list. It describes:
    1. That numbered boxes are drawn on the screenshot
    2. The exact box-id → selector mapping
    3. How to emit a box_id action

    Returns
    str
        System prompt block ready for injection.
    """
    if not element_map:
        return ""

    sep = "═" * 63
    lines = [
        f"\n{sep}",
        "🔢 SET-OF-MARKS MODE — Numbered boxes are drawn on the screenshot.",
        "Each box has a number in the top-left corner. To interact with",
        'an element, emit {"action": "click", "box_id": <number>} instead',
        "of guessing a CSS selector. DO NOT hallucinate locators.",
        sep,
        "ELEMENT MAP (box_id → what you're clicking):",
    ]
    for box_id, selector in sorted(element_map.items(), key=lambda x: int(x[0]) if x[0].isdigit() else 0):
        lines.append(f"  [{box_id:>2}] → {selector[:80]}")
    lines.extend(
        [
            sep,
            "USAGE EXAMPLES:",
            '  Click box 7:   {"action": "click", "box_id": 7}',
            '  Fill box 3:    {"action": "fill", "box_id": 3, "value": "hello@example.com"}',
            "IMPORTANT: box IDs are only valid for THIS screenshot.",
            "If you navigate or the page changes, NEW box IDs will be issued.",
            sep,
        ]
    )
    return "\n".join(lines)
