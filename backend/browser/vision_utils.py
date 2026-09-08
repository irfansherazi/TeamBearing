"""
vQA — Vision-Language Model (VLM) Set-of-Marks Utilities
==========================================================
Module: backend/browser/vision_utils.py

Implements the coordinate-based Set-of-Marks (SoM) strategy for vision-first
browser navigation.  Instead of feeding the LLM a text accessibility tree
(which explodes prompt limits on Angular/PrimeNG pages), this module:

  1. Injects numbered bounding boxes on every interactive element
  2. Takes a JPEG screenshot of the annotated page
  3. Returns a coordinate map:  mark_id → {x, y, selector}
  4. Removes all injected marks from the DOM

The LLM sees ONLY the annotated screenshot and emits
``{"action": "coordinate_action", "mark_id": 14}`` — the executor resolves
the mark_id to exact (x, y) pixel coordinates and executes
``page.mouse.click(x, y)``.

Coordinate Drift Defense
-------------------------
If the page shifts between screenshot capture and click execution (sticky
headers, Angular animations, lazy-loaded images), the executor falls back to
the CSS selector stored in the same map entry:

    coords = mark_map["14"]
    try:
        await page.mouse.click(coords["x"], coords["y"])
    except:
        await page.locator(coords["selector"]).click()

This dual-resolution strategy makes execution virtually bulletproof.

Architecture
------------
  planner_node (vision_mode == "som_coordinates")
    └─▶ draw_marks_and_snapshot(page)
          ├─▶ _inject_som_overlay(page)  → JS draws numbered boxes
          ├─▶ page.screenshot(jpeg, q=80) → annotated JPEG
          ├─▶ _extract_coordinate_map()   → {id: {x, y, selector}}
          └─▶ _cleanup_overlay(page)      → remove injected DOM

Usage
-----
    from backend.browser.vision_utils import draw_marks_and_snapshot

    screenshot_b64, mark_map = await draw_marks_and_snapshot(page)
    # mark_map: {"1": {"x": 150, "y": 320, "selector": "button#submit"}, ...}
    # screenshot_b64: base64-encoded JPEG of the annotated page

See Also
--------
    backend/browser/set_of_marks.py  — CSS-selector-only SoM (legacy path)
    backend/engine/planner.py        — vision_mode branching
    backend/engine/executor.py       — coordinate_action dispatcher
"""

import base64
import logging
from typing import Any

logger = logging.getLogger(__name__)

# ── Tuning constants ──────────────────────────────────────────────────────────

# Maximum number of elements to label. Above this the screenshot gets noisy
# and overlapping chips become illegible.
_MAX_SOM_ELEMENTS = 60

# Box styling — high-contrast red on both light and dark backgrounds.
_BOX_COLOR = "rgba(220, 38, 38, 0.85)"  # Red-600, semi-transparent
_LABEL_BG = "rgba(220, 38, 38, 1.0)"  # Solid red for the number chip
_LABEL_TEXT_COLOR = "#ffffff"
_BOX_BORDER = "2px solid rgba(220, 38, 38, 0.95)"

# CSS class for the overlay container — used for cleanup
_OVERLAY_CLASS = "__vqa_vision_overlay__"


# ── JavaScript: inject numbered overlay with center coordinates ──────────────

_JS_INJECT_OVERLAY = f"""
() => {{
  // Remove any previous overlay (idempotent)
  document.querySelectorAll('.{_OVERLAY_CLASS}').forEach(el => el.remove());

  // ── Selector generator (inline) ─────────────────────────────────────────
  function generateSelector(el) {{
    // Priority 1: data-testid / data-cy / data-vqa-id
    for (const attr of ['data-testid', 'data-cy', 'data-vqa-id']) {{
      const val = el.getAttribute(attr);
      if (val) return `[${{attr}}="${{val}}"]`;
    }}
    // Priority 2: id (verify uniqueness)
    if (el.id) {{
      try {{
        const candidates = document.querySelectorAll('#' + CSS.escape(el.id));
        if (candidates.length === 1) return '#' + CSS.escape(el.id);
      }} catch(e) {{}}
    }}
    // Priority 3: tag + significant class
    const tag = el.tagName.toLowerCase();
    const sigClasses = Array.from(el.classList)
      .filter(c => !c.startsWith('ng-') && c.length > 2).slice(0, 3);
    if (sigClasses.length > 0) {{
      const sel = tag + '.' + sigClasses.join('.');
      try {{
        if (document.querySelectorAll(sel).length === 1) return sel;
      }} catch(e) {{}}
    }}
    // Priority 4: PrimeNG component class
    const primeClasses = Array.from(el.classList)
      .filter(c => c.startsWith('p-') && c.length > 3).slice(0, 2);
    if (primeClasses.length > 0) {{
      const sel = tag + '.' + primeClasses.join('.');
      try {{
        if (document.querySelectorAll(sel).length === 1) return sel;
      }} catch(e) {{}}
    }}
    // Priority 5: nth-child positional fallback
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

  // ── Find interactive elements ────────────────────────────────────────────
  // NOTE: `:not([readonly])` on <input> and <textarea> skips PrimeNG's
  // p-calendar / p-select display-input wrappers.  Those inputs are
  // *visible* and *clickable* but silently swallow `keyboard.type()`
  // because they proxy user input to a hidden panel — the planner then
  // types "value" into them, sees no DOM delta, and retries the same
  // mark forever until the AC-step budget runs out (observed with QA-358
  // "Fill contest name field" against vpromotions PrimeNG forms).
  const INTERACTIVE_SELECTOR = [
    'button:not([disabled]):not([aria-hidden="true"])',
    'a[href]:not([aria-hidden="true"])',
    'input:not([type="hidden"]):not([disabled]):not([readonly])',
    'select:not([disabled])',
    'textarea:not([disabled]):not([readonly])',
    '[role="button"]:not([disabled]):not([aria-hidden="true"])',
    '[role="tab"]:not([aria-hidden="true"])',
    '[role="checkbox"]',
    '[role="radio"]',
    '[role="switch"]',
    '[role="combobox"]:not([aria-hidden="true"])',
    '[role="option"]',
    '[role="menuitem"]',
    'th',
    'p-select:not([aria-hidden="true"])',
    'p-checkbox:not([disabled])',
    'p-button:not([disabled])',
  ].join(',');

  const elements = queryAllPiercing(INTERACTIVE_SELECTOR)
    .filter(el => {{
      // Must be visible in or near the viewport
      const rect = el.getBoundingClientRect();
      return rect.width > 0 && rect.height > 0 &&
             rect.top >= -50 && rect.left >= -50 &&
             rect.bottom <= (window.innerHeight + 200) &&
             rect.right <= (window.innerWidth + 200) &&
             window.getComputedStyle(el).visibility !== 'hidden' &&
             window.getComputedStyle(el).display !== 'none' &&
             window.getComputedStyle(el).opacity !== '0';
    }})
    .slice(0, {_MAX_SOM_ELEMENTS});

  // ── Create overlay container ─────────────────────────────────────────────
  const container = document.createElement('div');
  container.className = '{_OVERLAY_CLASS}';
  container.style.cssText = `
    position: fixed; top: 0; left: 0; width: 0; height: 0;
    z-index: 2147483647; pointer-events: none; overflow: visible;
  `;
  document.body.appendChild(container);

  // ── Track chip positions for anti-occlusion ──────────────────────────────
  // When multiple elements are stacked vertically (pagination, dense tables),
  // their number chips overlap.  Track placed chip rects and offset colliders.
  const placedChips = [];

  function findNonOverlappingTop(baseLeft, baseTop, chipW, chipH) {{
    let top = baseTop;
    let maxAttempts = 5;
    while (maxAttempts-- > 0) {{
      const collides = placedChips.some(c =>
        Math.abs(c.left - baseLeft) < chipW &&
        Math.abs(c.top - top) < chipH
      );
      if (!collides) break;
      top -= (chipH + 2);  // Shift upward by chip height + 2px gap
    }}
    return top;
  }}

  const results = [];

  elements.forEach((el, idx) => {{
    const id = idx + 1;
    const sel = generateSelector(el);
    const rect = el.getBoundingClientRect();

    // ── Calculate center coordinates (viewport-relative) ──────────────────
    // These are the coordinates passed to page.mouse.click(x, y).
    // Playwright's mouse.click uses viewport coordinates, matching
    // getBoundingClientRect() which returns viewport-relative positions.
    const centerX = Math.round(rect.left + rect.width / 2);
    const centerY = Math.round(rect.top + rect.height / 2);

    // ── Draw bounding box outline ─────────────────────────────────────────
    const box = document.createElement('div');
    box.style.cssText = `
      position: fixed;
      left: ${{rect.left}}px;
      top: ${{rect.top}}px;
      width: ${{rect.width}}px;
      height: ${{rect.height}}px;
      border: {_BOX_BORDER};
      border-radius: 3px;
      box-sizing: border-box;
      pointer-events: none;
    `;
    container.appendChild(box);

    // ── Draw number chip (anti-occlusion aware) ───────────────────────────
    const chipW = 20;
    const chipH = 16;
    const chipLeft = rect.left - 2;
    const chipBaseTop = rect.top - chipH - 2;
    const chipTop = findNonOverlappingTop(chipLeft, chipBaseTop, chipW, chipH);

    const chip = document.createElement('div');
    chip.style.cssText = `
      position: fixed;
      left: ${{chipLeft}}px;
      top: ${{chipTop}}px;
      background: {_LABEL_BG};
      color: {_LABEL_TEXT_COLOR};
      font: bold 11px/16px monospace;
      padding: 0 4px;
      border-radius: 3px 3px 3px 0;
      min-width: 18px;
      text-align: center;
      pointer-events: none;
      white-space: nowrap;
      z-index: ${{2147483647 - idx}};
    `;
    chip.textContent = String(id);
    container.appendChild(chip);

    // Track this chip's position for future collision checks
    placedChips.push({{ left: chipLeft, top: chipTop }});

    results.push({{
      id: id,
      selector: sel,
      center_x: centerX,
      center_y: centerY,
      width: Math.round(rect.width),
      height: Math.round(rect.height),
      tag: el.tagName.toLowerCase(),
      text: (el.innerText || el.getAttribute('aria-label') || '').substring(0, 50).trim(),
    }});
  }});

  return results;
}}
"""


# ── JavaScript: cleanup ──────────────────────────────────────────────────────

_JS_CLEANUP = f"""
() => {{
  document.querySelectorAll('.{_OVERLAY_CLASS}').forEach(el => el.remove());
}}
"""


# ── Public API ───────────────────────────────────────────────────────────────


async def draw_marks_and_snapshot(
    page: Any,  # playwright.async_api.Page
    *,
    cleanup: bool = True,
    jpeg_quality: int = 80,
) -> tuple[str, dict[str, dict]]:
    """
    Annotate the page with numbered boxes, screenshot it, return coordinate map.

    Workflow
    --------
    1. Inject JS overlay: draw numbered red boxes on all visible interactive elements.
    2. Capture a JPEG screenshot of the annotated page (base64-encoded).
    3. Build the coordinate map: ``{mark_id: {x, y, selector, tag, text}}``.
    4. Remove all injected DOM elements (default: yes).

    Args
    ----
    page : playwright.async_api.Page
        The live browser page.
    cleanup : bool
        If True (default), remove the overlay after the screenshot.
        Set to False in HITL mode so the user sees numbered boxes.
    jpeg_quality : int
        JPEG compression quality (0–100). Default 80 balances size vs readability.

    Returns
    -------
    tuple[str, dict[str, dict]]
        (screenshot_b64, mark_coordinate_map) where:
        - screenshot_b64: JPEG screenshot as base64 string (annotated)
        - mark_coordinate_map: mapping of mark_id to coordinates + metadata::

            {
                "1": {"x": 150, "y": 320, "selector": "button#submit", "tag": "button", "text": "Submit All"},
                "14": {"x": 400, "y": 55, "selector": "p-select.po-sorting", "tag": "p-select", "text": ""},
            }

    Raises
    ------
    RuntimeError
        If the page is closed or JS injection fails fatally.
    """
    if page.is_closed():
        raise RuntimeError("draw_marks_and_snapshot: page is already closed")

    # 1. Inject overlay and collect element data with coordinates
    try:
        raw_results: list[dict] = await page.evaluate(_JS_INJECT_OVERLAY)
    except Exception as e:
        logger.error("Vision SoM overlay injection failed: %s", e)
        raise RuntimeError(f"Vision SoM overlay injection failed: {e}") from e

    if not raw_results:
        logger.warning("Vision SoM: no interactive elements found — falling back to plain screenshot")
        screenshot_bytes = await page.screenshot(type="jpeg", quality=jpeg_quality)
        return base64.b64encode(screenshot_bytes).decode(), {}

    # 2. Build the coordinate map: mark_id → {x, y, selector, tag, text}
    mark_coordinate_map: dict[str, dict] = {}
    for item in raw_results:
        mark_id = item.get("id")
        if mark_id is None:
            continue
        mark_coordinate_map[str(mark_id)] = {
            "x": item["center_x"],
            "y": item["center_y"],
            "selector": item.get("selector", ""),
            "tag": item.get("tag", ""),
            "text": item.get("text", ""),
            "width": item.get("width", 0),
            "height": item.get("height", 0),
        }

    logger.info(
        "Vision SoM: annotated %d interactive elements with coordinates",
        len(mark_coordinate_map),
    )

    # 3. Capture annotated screenshot (JPEG for bandwidth efficiency)
    try:
        screenshot_bytes = await page.screenshot(type="jpeg", quality=jpeg_quality)
        screenshot_b64 = base64.b64encode(screenshot_bytes).decode()
    except Exception as e:
        logger.error("Vision SoM: screenshot capture failed: %s", e)
        if cleanup:
            await _cleanup_overlay(page)
        raise RuntimeError(f"Vision SoM screenshot failed: {e}") from e

    # 4. Cleanup overlay
    if cleanup:
        await _cleanup_overlay(page)

    logger.info(
        "Vision SoM: captured JPEG screenshot (%d KB) with %d marks",
        len(screenshot_bytes) // 1024,
        len(mark_coordinate_map),
    )

    return screenshot_b64, mark_coordinate_map


async def _cleanup_overlay(page: Any) -> None:
    """Remove the vision SoM overlay from the page. Best-effort — never raises."""
    try:
        await page.evaluate(_JS_CLEANUP)
    except Exception as e:
        logger.debug("Vision SoM cleanup error (non-fatal): %s", e)


def format_vision_mark_summary(mark_map: dict[str, dict]) -> str:
    """
    Format the mark coordinate map as a compact text summary for the LLM prompt.

    Uses a minified pipe-delimited format to minimize token count:
      [14] button "Sort By"
      [15] p-select (no text)
      [16] th "CLIENT"

    Empty text/label fields are dropped. Usage examples are omitted here
    since they are already in the system prompt's <available_actions> block.

    Args
    ----
    mark_map : dict[str, dict]
        The coordinate map returned by ``draw_marks_and_snapshot()``.

    Returns
    -------
    str
        Compact text block describing all numbered marks.
    """
    if not mark_map:
        return ""

    lines = [
        "<som_element_map>",
        "Numbered marks on screenshot. Use coordinate_action with mark_id to interact.",
    ]

    for mark_id in sorted(mark_map.keys(), key=lambda k: int(k) if k.isdigit() else 0):
        entry = mark_map[mark_id]
        tag = entry.get("tag", "?")
        text = (entry.get("text") or "").strip()
        # Compact format: [ID] tag "text" — drop empty text fields entirely
        if text:
            # Truncate long text to save tokens
            display_text = text[:40] + "…" if len(text) > 40 else text
            lines.append(f'[{mark_id}] {tag} "{display_text}"')
        else:
            lines.append(f"[{mark_id}] {tag}")

    lines.append("</som_element_map>")
    return "\n".join(lines)


class LocalObjectDetector:
    """Local element resolver that maps a semantic target description to coordinates using local DOM layout extraction."""

    @staticmethod
    async def resolve_target(page: Any, target: str) -> dict | None:
        """
        Evaluates a JS script to extract interactive elements, fuzzy matches the
        target description, and returns the best element's viewport coordinates and metadata.
        """
        if page.is_closed():
            return None

        # JS query to extract all interactive elements on the page
        js_query = """
        () => {
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
                'th',
                'p-select:not([aria-hidden="true"])',
                'p-checkbox:not([disabled])',
                'p-button:not([disabled])',
            ].join(',');

            function generateSelector(el) {
                for (const attr of ['data-testid', 'data-cy', 'data-vqa-id']) {
                    const val = el.getAttribute(attr);
                    if (val) return `[${attr}="${val}"]`;
                }
                if (el.id) {
                    try {
                        const candidates = document.querySelectorAll('#' + CSS.escape(el.id));
                        if (candidates.length === 1) return '#' + CSS.escape(el.id);
                    } catch(e) {}
                }
                const tag = el.tagName.toLowerCase();
                const sigClasses = Array.from(el.classList)
                    .filter(c => !c.startsWith('ng-') && c.length > 2).slice(0, 3);
                if (sigClasses.length > 0) {
                    const sel = tag + '.' + sigClasses.join('.');
                    try {
                        if (document.querySelectorAll(sel).length === 1) return sel;
                    } catch(e) {}
                }
                return tag;
            }

            function queryAllPiercing(selector, root = document) {
                let results = Array.from(root.querySelectorAll(selector));
                const all = root.querySelectorAll('*');
                for (const el of all) {
                    if (el.shadowRoot) {
                        results = results.concat(queryAllPiercing(selector, el.shadowRoot));
                    }
                }
                return results;
            }

            const els = queryAllPiercing(INTERACTIVE_SELECTOR);
            const results = [];

            for (const el of els) {
                const rect = el.getBoundingClientRect();
                if (rect.width === 0 || rect.height === 0) continue;

                const style = window.getComputedStyle(el);
                if (style.visibility === 'hidden' || style.display === 'none' || style.opacity === '0') {
                    continue;
                }

                const tag = el.tagName.toLowerCase();
                const role = el.getAttribute('role') || '';
                const text = el.innerText || '';
                const ariaLabel = el.getAttribute('aria-label') || '';
                const placeholder = el.getAttribute('placeholder') || '';
                const title = el.getAttribute('title') || '';
                const name = el.name || '';

                results.push({
                    tag,
                    role,
                    text: text.trim(),
                    ariaLabel: ariaLabel.trim(),
                    placeholder: placeholder.trim(),
                    title: title.trim(),
                    name: name.trim(),
                    x: Math.round(rect.left + rect.width / 2),
                    y: Math.round(rect.top + rect.height / 2),
                    width: Math.round(rect.width),
                    height: Math.round(rect.height),
                    selector: generateSelector(el),
                });
            }
            return results;
        }
        """

        try:
            elements = await page.evaluate(js_query)
        except Exception as e:
            logger.warning("LocalObjectDetector: evaluate failed: %s", e)
            return None

        if not elements:
            return None

        import re

        def compute_match_score(target_str: str, text_str: str, role_str: str) -> float:
            t = target_str.lower().strip()
            e = text_str.lower().strip()
            if not e:
                return 0.0

            score = 0.0
            if t == e:
                score += 10.0
            if t in e:
                score += 5.0
                if e.startswith(t):
                    score += 2.0
            elif e in t:
                score += 3.0

            # Word token matching
            t_words = set(re.findall(r'[a-z0-9]+', t))
            e_words = set(re.findall(r'[a-z0-9]+', e))
            if t_words and e_words:
                intersection = t_words.intersection(e_words)
                union = t_words.union(e_words)
                jaccard = len(intersection) / len(union)
                score += jaccard * 5.0

                if role_str:
                    r = role_str.lower().strip()
                    if r in t_words:
                        score += 1.0
            return score

        best_element = None
        best_score = -1.0

        for el in elements:
            score = 0.0
            # Score target against all textual fields
            texts_to_check = [
                (el["text"], 1.0),
                (el["ariaLabel"], 1.2),
                (el["placeholder"], 1.1),
                (el["title"], 1.0),
                (el["name"], 1.0),
            ]

            role_or_tag = el["role"] or el["tag"]
            for text, weight in texts_to_check:
                if text:
                    field_score = compute_match_score(target, text, role_or_tag) * weight
                    score = max(score, field_score)

            if score > best_score and score > 1.0:
                best_score = score
                best_element = el

        if best_element:
            logger.info(
                "LocalObjectDetector: resolved target '%s' to element <%s> '%s' at (%d, %d) with score %.2f",
                target,
                best_element["tag"],
                best_element["text"] or best_element["ariaLabel"] or "(no text)",
                best_element["x"],
                best_element["y"],
                best_score,
            )
            return {
                "x": best_element["x"],
                "y": best_element["y"],
                "selector": best_element["selector"],
                "tag": best_element["tag"],
                "text": best_element["text"] or best_element["ariaLabel"],
            }

        logger.warning("LocalObjectDetector: could not resolve target '%s'", target)
        return None

