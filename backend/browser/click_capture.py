"""
vQA — Click-to-Teach: Auto-Capture Click Interceptor
======================================================
Module: backend/browser/click_capture.py

Replaces manual CSS/XPath input in the Pause-and-Teach HITL panel with an
"auto-capture" mode. When the user clicks anywhere on the screenshots shown in
TakeoverPanel, the backend identifies the exact DOM element at that pixel
position, generates the most robust CSS selector for it, injects a green
highlight overlay so the user gets visual confirmation, and returns all metadata
to the frontend.

The user never has to type a selector. They only answer: "Why did you click
this?" That explanation is saved to the KB.

Architecture
------------
  TakeoverPanel (frontend)
    ── user clicks screenshot in capture mode ──▶ POST /runs/{id}/teach/capture-click
                                                      └─▶ capture_element_at(page, x_pct, y_pct)
                                                            ├─▶ JS: document.elementFromPoint(x, y)
                                                            ├─▶ JS: generateSelector(el)   ← best CSS
                                                            ├─▶ JS: inject green highlight overlay
                                                            └─▶ return {selector, tag, text, role}
                                                      └─▶ capture_screenshot_b64(page)  ← highlighted
                                                  ◀── {selector, element_label, screenshot_b64}
    ── shows "Captured: th.po-col-clientCol (CLIENT)" ──
    ── user types "Why?" ──▶ POST /runs/{id}/teach  (existing endpoint)
                                └─▶ executes click via Playwright
                                └─▶ writes to selector_registry + human_guidance.md

Selector priority (all in JS, no Python post-processing):
  1. data-testid / data-cy / data-vqa-id  ← test-id attributes (always unique)
  2. aria-label attribute                  ← semantic, stable
  3. #id (verified unique)                 ← stable if present
  4. tag.class fingerprint                 ← Angular/PrimeNG component classes
  5. nth-child positional path             ← fallback, always works

Highlight design:
  - Thick green (#22c55e) 3px outline with 20% fill
  - Label chip in top-left corner showing element type + truncated text
  - Cleaned up automatically after screenshot is captured
  - Never modifies the element's own styles (overlay div approach)
  - z-index: MAX_INT — visible above all PrimeNG overlays and dialogs

Dependencies
------------
  - playwright.async_api.Page
  - backend.browser.screenshot.capture_screenshot_b64
"""

import base64
import logging
from typing import Any

logger = logging.getLogger(__name__)

# ── Highlight styling ─────────────────────────────────────────────────────────

_CAPTURE_OVERLAY_CLASS = "__vqa_capture_overlay__"
_HIGHLIGHT_BORDER = "3px solid #22c55e"  # Tailwind green-500
_HIGHLIGHT_BG = "rgba(34, 197, 94, 0.12)"  # 12% fill
_LABEL_BG = "#16a34a"  # green-600 solid
_LABEL_TEXT = "#ffffff"

# ── JS: identify + highlight element at (x, y) ───────────────────────────────

_JS_CAPTURE_AT_POINT = r"""
([x, y]) => {
  // ── 1. Find element at coordinates ──────────────────────────────
  const el = document.elementFromPoint(x, y);
  if (!el || el === document.body || el === document.documentElement) {
    return null;
  }

  // ── 2. Walk up to nearest meaningful interactive ancestor ────────
  // If the user clicks a span inside a button, we want the button.
  // Walk up max 4 levels or until we hit an interactive element.
  const INTERACTIVE_TAGS = new Set([
    'button','a','input','select','textarea',
    'p-select','p-button','p-checkbox'
  ]);
  const INTERACTIVE_ROLES = new Set([
    'button','link','textbox','combobox','checkbox',
    'radio','switch','menuitem','tab','option','slider'
  ]);

  let target = el;
  for (let i = 0; i < 4; i++) {
    const parent = target.parentElement;
    if (!parent || parent === document.body) break;
    const role = parent.getAttribute('role') || '';
    const tag = parent.tagName.toLowerCase();
    if (INTERACTIVE_TAGS.has(tag) || INTERACTIVE_ROLES.has(role)) {
      target = parent;
      break;
    }
  }

  // ── 3. Generate best CSS selector ────────────────────────────────
  function generateSelector(element) {
    // Priority 1: test-id attributes (always unique by convention)
    for (const attr of ['data-testid', 'data-cy', 'data-vqa-id', 'data-id']) {
      const val = element.getAttribute(attr);
      if (val) return `[${attr}="${val}"]`;
    }

    // Priority 2: aria-label (semantic, stable)
    const ariaLabel = element.getAttribute('aria-label');
    if (ariaLabel) {
      const tag = element.tagName.toLowerCase();
      const sel = `${tag}[aria-label="${ariaLabel}"]`;
      try {
        if (document.querySelectorAll(sel).length === 1) return sel;
      } catch(e) {}
    }

    // Priority 3: unique #id
    if (element.id) {
      try {
        const esc = CSS.escape(element.id);
        if (document.querySelectorAll('#' + esc).length === 1) return '#' + esc;
      } catch(e) {}
    }

    // Priority 4: tag + semantic classes (filter Angular/ng-* noise)
    const tag = element.tagName.toLowerCase();

    // 4a: Non-Angular, non-PrimeNG classes first (app-specific, most stable)
    const appClasses = Array.from(element.classList)
      .filter(c => !c.startsWith('ng-') && !c.startsWith('p-') &&
                   c.length > 2 && !/^[a-z]+-\d+$/.test(c))
      .slice(0, 3);
    if (appClasses.length > 0) {
      const sel = tag + '.' + appClasses.join('.');
      try {
        if (document.querySelectorAll(sel).length === 1) return sel;
      } catch(e) {}
    }

    // 4b: PrimeNG component classes (po-col-*, p-select, etc.)
    const poClasses = Array.from(element.classList)
      .filter(c => c.startsWith('po-') || (c.startsWith('p-') && c.length > 3))
      .slice(0, 2);
    if (poClasses.length > 0) {
      const sel = tag + '.' + poClasses.join('.');
      try {
        if (document.querySelectorAll(sel).length === 1) return sel;
      } catch(e) {}
    }

    // 4c: Combined app + PrimeNG for compound column headers
    if (appClasses.length > 0 && poClasses.length > 0) {
      const sel = tag + '.' + [...appClasses, ...poClasses].join('.');
      try {
        if (document.querySelectorAll(sel).length === 1) return sel;
      } catch(e) {}
    }

    // Priority 5: nth-child positional path (fallback — always unique)
    function getPath(node) {
      if (!node || node === document.body) return 'body';
      const parent = node.parentElement;
      if (!parent) return node.tagName.toLowerCase();
      const idx = Array.from(parent.children).indexOf(node) + 1;
      return getPath(parent) + ' > ' + node.tagName.toLowerCase() + ':nth-child(' + idx + ')';
    }
    return getPath(element);
  }

  const selector = generateSelector(target);

  // ── 4. Collect element metadata ───────────────────────────────────
  const rect = target.getBoundingClientRect();
  const tag = target.tagName.toLowerCase();
  const role = target.getAttribute('role') || tag;
  const text = (target.innerText || target.value || target.getAttribute('aria-label') || '').trim().substring(0, 80);
  const ariaLabel = target.getAttribute('aria-label') || '';
  const placeholder = target.getAttribute('placeholder') || '';

  // ── 5. Inject green highlight overlay ────────────────────────────
  // Remove any previous highlight first
  document.querySelectorAll('.__vqa_capture_overlay__').forEach(el => el.remove());

  const container = document.createElement('div');
  container.className = '__vqa_capture_overlay__';
  container.style.cssText = `
    position: fixed; top: 0; left: 0; width: 0; height: 0;
    z-index: 2147483647; pointer-events: none; overflow: visible;
  `;

  // Green bounding box
  const box = document.createElement('div');
  box.style.cssText = `
    position: absolute;
    left: ${rect.left + window.scrollX}px;
    top: ${rect.top + window.scrollY}px;
    width: ${rect.width}px;
    height: ${rect.height}px;
    border: 3px solid #22c55e;
    background: rgba(34, 197, 94, 0.12);
    border-radius: 4px;
    box-sizing: border-box;
    pointer-events: none;
  `;
  container.appendChild(box);

  // Label chip
  const chip = document.createElement('div');
  const labelText = text || ariaLabel || placeholder || tag;
  chip.style.cssText = `
    position: absolute;
    left: ${rect.left + window.scrollX - 1}px;
    top: ${rect.top + window.scrollY - 22}px;
    background: #16a34a;
    color: #fff;
    font: bold 11px/18px monospace;
    padding: 0 6px;
    border-radius: 4px 4px 4px 0;
    max-width: 280px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    pointer-events: none;
  `;
  chip.textContent = `${tag}${role !== tag ? ' [' + role + ']' : ''}: ${labelText || '(no text)'}`;
  container.appendChild(chip);

  document.body.appendChild(container);

  return {
    selector,
    tag,
    role,
    text: text || ariaLabel || placeholder || '(no visible text)',
    ariaLabel,
    matchCount: (function() {
      try { return document.querySelectorAll(selector).length; } catch(e) { return 1; }
    })(),
    rect: { x: rect.left, y: rect.top, width: rect.width, height: rect.height },
  };
}
"""

_JS_CLEAR_CAPTURE_HIGHLIGHT = """
() => {
  document.querySelectorAll('.__vqa_capture_overlay__').forEach(el => el.remove());
}
"""


# ── Public API ────────────────────────────────────────────────────────────────


async def capture_element_at(
    page: Any,  # playwright Page
    x_pct: float,
    y_pct: float,
) -> dict:
    """
    Identify the DOM element at the given viewport-relative coordinates and
    inject a green highlight around it.

    Args
    ----
    page : playwright.async_api.Page
        The active browser page.
    x_pct : float
        Horizontal position as a fraction of viewport width (0.0–1.0).
    y_pct : float
        Vertical position as a fraction of viewport height (0.0–1.0).

    Returns
    -------
    dict with keys:
        selector   : str — best CSS selector for the element
        tag        : str — HTML tag name (e.g. "button", "th")
        role       : str — ARIA role or tag name
        text       : str — visible text / aria-label (truncated to 80 chars)
        ariaLabel  : str — aria-label attribute if present
        matchCount : int — number of elements matching the generated selector
        rect       : dict — {x, y, width, height} bounding box in viewport px

    Returns {} if no element found at the given coordinates.
    """
    if page.is_closed():
        logger.warning("capture_element_at: page is closed")
        return {}

    viewport = page.viewport_size or {"width": 1280, "height": 720}
    x_px = x_pct * viewport["width"]
    y_px = y_pct * viewport["height"]

    try:
        result = await page.evaluate(_JS_CAPTURE_AT_POINT, [x_px, y_px])
        if not result:
            logger.info(
                "capture_element_at: no element at (%.1f, %.1f) px",
                x_px,
                y_px,
            )
            return {}

        logger.info(
            "capture_element_at: captured <%s> '%s' → selector='%s' (matches=%d)",
            result.get("tag", "?"),
            result.get("text", "")[:40],
            result.get("selector", "")[:60],
            result.get("matchCount", -1),
        )
        return result

    except Exception as e:
        logger.error("capture_element_at JS evaluation failed: %s", e)
        return {}


async def highlight_and_screenshot(
    page: Any,
    x_pct: float,
    y_pct: float,
) -> tuple[str, dict]:
    """
    Identify the element at (x_pct, y_pct), highlight it with a green overlay,
    take a screenshot, remove the overlay, and return both.

    This is the primary entry point used by the ``/teach/capture-click`` endpoint.

    Args
    ----
    page : playwright Page
    x_pct, y_pct : viewport-relative coordinates (0.0–1.0)

    Returns
    -------
    tuple[str, dict]
        (screenshot_b64, element_info)
        screenshot_b64 : PNG with green highlight as base64 string
        element_info   : {selector, tag, role, text, ariaLabel, matchCount, rect}
                         or {} if nothing found
    """
    if page.is_closed():
        return "", {}

    # Inject highlight + get element info (single round-trip JS call)
    element_info = await capture_element_at(page, x_pct, y_pct)

    # Capture screenshot WITH the highlight visible
    try:
        screenshot_bytes = await page.screenshot(type="png", full_page=False)
        screenshot_b64 = base64.b64encode(screenshot_bytes).decode()
    except Exception as e:
        logger.error("highlight_and_screenshot: screenshot failed: %s", e)
        screenshot_b64 = ""

    # Remove highlight after screenshot (non-blocking, best-effort)
    await clear_highlight(page)

    return screenshot_b64, element_info


async def clear_highlight(page: Any) -> None:
    """Remove the capture highlight overlay. Best-effort — never raises."""
    try:
        if not page.is_closed():
            await page.evaluate(_JS_CLEAR_CAPTURE_HIGHLIGHT)
    except Exception as e:
        logger.debug("clear_highlight (non-fatal): %s", e)


def build_element_label(element_info: dict) -> str:
    """
    Build a human-readable label for the captured element suitable for display
    in the TakeoverPanel UI.

    Examples:
        "th.po-col-clientCol — CLIENT column header"
        "button#submit-order-btn — 'Submit Order'"
        "p-select (combobox) — Sort options"
    """
    selector = element_info.get("selector", "(unknown)")
    tag = element_info.get("tag", "")
    role = element_info.get("role", "")
    text = element_info.get("text", "").strip()
    aria = element_info.get("ariaLabel", "").strip()
    match_count = element_info.get("matchCount", 1)

    role_part = f" ({role})" if role and role != tag else ""
    text_part = f" — '{text[:50]}'" if text else (f" — [{aria[:50]}]" if aria else "")
    uniqueness = "" if match_count == 1 else f" ⚠️ {match_count} matches"

    return f"{selector}{role_part}{text_part}{uniqueness}"
