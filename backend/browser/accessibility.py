"""
vQA — Accessibility Tree Extractor
====================================
Module: backend/browser/accessibility.py

Extracts the ARIA accessibility tree from a live Playwright page and
formats it as a structured text string for the multimodal LLM planner.

Why Accessibility Trees?
------------------------
The vQA see-think-act loop sends TWO signals to Claude 3.5 Sonnet:

  1. **Screenshot** (image)   — visual representation of the page
  2. **Accessibility tree** (text) — structural representation of
     every interactive element: roles, names, states, values

This dual-grounding approach is critical because:

  - Screenshots alone can be ambiguous (identical-looking buttons,
    text that looks like a label but is actually a link).
  - The a11y tree provides EXACT element roles and names that map
    directly to Playwright's ``get_by_role()`` locator — the most
    reliable locator strategy available.
  - Together, they give Claude the confidence to output precise
    JSON actions like ``{"role": "button", "name": "Submit All"}``.

ARIA Tree Structure
-------------------
Playwright's ``page.accessibility.snapshot()`` returns a dict like::

    {
        "role": "WebArea",
        "name": "",
        "children": [
            {
                "role": "navigation",
                "name": "Main Navigation",
                "children": [
                    {"role": "link", "name": "Dashboard"},
                    {"role": "link", "name": "Production Orders"},
                    {"role": "button", "name": "New Request +"}
                ]
            },
            {
                "role": "main",
                "children": [
                    {"role": "heading", "name": "Quick Order Form", "level": 1},
                    {"role": "textbox", "name": "Client Name", "value": "Bob"},
                    {"role": "button", "name": "Submit All"}
                ]
            }
        ]
    }

This module flattens that tree into a human-readable indented string
that fits cleanly into the LLM prompt.

Architecture Context
--------------------
Called by ``planner_node`` before each LLM call.  The result is stored
in ``VQAState.current_accessibility_tree`` and included in the planner's
multimodal message payload.

Dependencies
------------
  - ``playwright.async_api.Page`` — the live browser page
  - No other vQA modules — this is a pure utility

See Also
--------
  - ``backend/engine/planner.py`` — consumes the a11y tree
  - ``backend/browser/screenshot.py`` — captures the visual companion
"""

import logging
from typing import Any

from playwright.async_api import Page

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Maximum depth of the accessibility tree to extract.
#: Deeper trees add noise without useful signal for the LLM.
#: 8 levels covers: WebArea > nav/main > section > list > listitem > link
MAX_TREE_DEPTH: int = 8

#: ARIA roles that are purely structural and add noise to the LLM prompt.
#: These are filtered out to keep the tree focused on interactive elements.
SKIP_ROLES: set[str] = {
    "generic",  # Generic containers (divs)
    "none",  # Explicitly hidden from a11y
    "presentation",  # Decorative elements
    "StaticText",  # Raw text nodes (captured in parent's name)
    "InlineTextBox",  # Chrome-specific text layout node
}

#: ARIA roles that represent interactive elements the agent can act on.
#: Elements with these roles are always included in the tree output.
INTERACTIVE_ROLES: set[str] = {
    "button",
    "link",
    "textbox",
    "checkbox",
    "radio",
    "combobox",
    "listbox",
    "option",
    "menuitem",
    "tab",
    "switch",
    "slider",
    "spinbutton",
    "searchbox",
    "menuitemcheckbox",
    "menuitemradio",
}


# ---------------------------------------------------------------------------
# Tree formatting
# ---------------------------------------------------------------------------


def _format_node(
    node: dict[str, Any],
    depth: int = 0,
    max_depth: int = MAX_TREE_DEPTH,
) -> list[str]:
    """
    Recursively format an accessibility tree node into indented text lines.

    Each node is rendered as::

        [indent][role] "name" (state=value, ...)

    For example::

        [button] "Submit All"
        [textbox] "Client Name" value="Bob"
        [checkbox] "Remember me" checked=true

    Args
    ----
    node : dict[str, Any]
        A single accessibility tree node from Playwright's
        ``page.accessibility.snapshot()``.

    depth : int
        Current indentation depth (0 = root). Each level adds 2 spaces.

    max_depth : int
        Maximum depth to recurse into.  Nodes deeper than this are
        silently skipped to prevent prompt bloat.

    Returns
    -------
    list[str]
        Lines of formatted text representing the node and its children.

    Example
    -------
    >>> node = {"role": "button", "name": "Submit All"}
    >>> _format_node(node)
    ['[button] "Submit All"']
    """
    if depth > max_depth:
        return []

    role: str = node.get("role", "unknown")
    name: str = node.get("name", "")

    # Skip structural noise
    if role in SKIP_ROLES:
        # Still recurse into children — structural nodes may contain
        # interactive descendants
        lines: list[str] = []
        for child in node.get("children", []):
            lines.extend(_format_node(child, depth, max_depth))
        return lines

    # Build the node label
    indent: str = "  " * depth
    parts: list[str] = [f"{indent}[{role}]"]

    # Add name if present
    if name:
        # Truncate very long names (e.g. paragraphs of text inside links)
        display_name = name[:100] + "..." if len(name) > 100 else name
        parts.append(f'"{display_name}"')

    # Add informative state attributes
    state_attrs: list[str] = []
    if node.get("value"):
        state_attrs.append(f'value="{node["value"]}"')
    if node.get("checked") is not None:
        state_attrs.append(f"checked={str(node['checked']).lower()}")
    if node.get("selected") is not None:
        state_attrs.append(f"selected={str(node['selected']).lower()}")
    if node.get("expanded") is not None:
        state_attrs.append(f"expanded={str(node['expanded']).lower()}")
    if node.get("disabled"):
        state_attrs.append("disabled")
    if node.get("required"):
        state_attrs.append("required")
    if node.get("readonly"):
        state_attrs.append("readonly")
    if node.get("level"):
        state_attrs.append(f"level={node['level']}")

    if state_attrs:
        parts.append(f"({', '.join(state_attrs)})")

    # Compose the line
    lines = [" ".join(parts)]

    # Recurse into children
    for child in node.get("children", []):
        lines.extend(_format_node(child, depth + 1, max_depth))

    return lines


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def extract_accessibility_tree(
    page: Page,
    *,
    max_depth: int = MAX_TREE_DEPTH,
) -> str:
    """
    Extract and format the accessibility tree from a Playwright page.

    Calls ``page.accessibility.snapshot()`` and formats the result into
    an indented, human-readable text string suitable for inclusion in
    an LLM prompt.

    Args
    ----
    page : Page
        The active Playwright page to snapshot.

    max_depth : int
        Maximum depth to recurse into the tree.  Default is 8.

    Returns
    -------
    str
        The formatted accessibility tree as a multi-line string.
        Returns ``"(accessibility tree unavailable)"`` if extraction
        fails for any reason (page not loaded, permissions error, etc.).

    Example
    -------
    >>> tree = await extract_accessibility_tree(page)
    >>> print(tree[:200])
    [WebArea] "vSuite Dashboard"
      [navigation] "Main Navigation"
        [link] "Dashboard"
        [link] "Production Orders"
        [button] "New Request +"
      [main]
        [heading] "Quick Order Form" (level=1)
    """
    try:
        # Try page.aria_snapshot() first (Playwright 1.50+).
        # If not available, fall back to JS-based ARIA tree extraction.
        snapshot: str = ""

        if hasattr(page, "aria_snapshot"):
            try:
                snapshot = await page.aria_snapshot()
            except Exception:
                pass  # Fall through to JS fallback

        if not snapshot:
            # JS fallback: walk the DOM and extract a text representation
            # of the ARIA tree using standard web accessibility APIs.
            # ROLE_MAP normalizes HTML tag names → ARIA roles so the LLM
            # can always plan get_by_role("link") instead of get_by_role("a").
            snapshot = await page.evaluate("""() => {
                const lines = [];
                const SKIP = new Set(['script','style','noscript','head','meta','link']);
                const ROLE_MAP = {
                    'a': 'link', 'button': 'button', 'input': 'textbox',
                    'select': 'combobox', 'textarea': 'textbox', 'img': 'img',
                    'h1': 'heading', 'h2': 'heading', 'h3': 'heading'
                };

                function walk(el, depth) {
                    if (!el || SKIP.has(el.tagName?.toLowerCase())) return;

                    // Normalize tag name to ARIA role
                    const tagName = el.tagName?.toLowerCase();
                    let role = el.getAttribute('role') ||
                        ROLE_MAP[tagName] || tagName || 'unknown';
                    if (tagName === 'li' && (el.classList.contains('p-dropdown-item') || el.classList.contains('p-select-option') || el.classList.contains('p-menuitem'))) {
                        role = (role === 'li' || role === 'unknown') ? 'option' : role;
                    }
                    const name = el.getAttribute('aria-label') ||
                        el.getAttribute('placeholder') ||
                        el.getAttribute('title') ||
                        (el.innerText || '').trim().substring(0, 80);
                    const disabled = el.disabled || el.getAttribute('aria-disabled') === 'true';
                    const checked = el.checked !== undefined ? el.checked : null;

                    const indent = '  '.repeat(depth);
                    let line = `${indent}[${role}]`;
                    if (name) line += ` "${name}"`;
                    if (disabled) line += ' (disabled)';
                    if (checked !== null) line += ` (checked=${checked})`;
                    if (line.trim() !== `[${role}]`) lines.push(line);

                    // Standard children
                    for (const child of el.children) {
                        walk(child, depth + 1);
                    }
                    // Pierce shadow root
                    if (el.shadowRoot) {
                        for (const child of el.shadowRoot.children) {
                            walk(child, depth + 1);
                        }
                    }
                }

                walk(document.body, 0);
                return lines.slice(0, 500).join('\\n');
            }""")

        if not snapshot:
            return f"(accessibility tree unavailable — URL: {page.url})"

        logger.debug("Extracted accessibility tree: %d chars", len(snapshot))
        return _prune_snapshot(snapshot)

    except Exception as e:
        logger.warning(
            "Failed to extract accessibility tree: %s",
            str(e),
            exc_info=True,
        )
        return "(accessibility tree unavailable)"


def _prune_snapshot(text: str) -> str:
    """
    Strip token-expensive noise from an accessibility tree / DOM snapshot.

    Removes:
    - base64 data URIs  (data:image/...;base64,...)
    - SVG path commands (long M/L/C/Z coordinate sequences)
    - Excessive blank lines

    Keeps the text under ~3500 effective chars for prompt efficiency.
    """
    import re as _re

    # Strip base64 blobs (they appear when aria-label contains data URIs)
    text = _re.sub(r"data:[^;]+;base64,[A-Za-z0-9+/=]{20,}", "[base64-omitted]", text)
    # Strip SVG path data (long coordinate strings)
    text = _re.sub(r"\b[MLCQTASZHVmlcqtaszhv][\d\s.,\-MLCQTASZHVmlcqtaszhv]{40,}", "[svg-path]", text)
    # Collapse 3+ blank lines into 2
    text = _re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


async def extract_interactive_elements(
    page: Page,
    target_element_types: list[str] | None = None,
) -> list[dict[str, str]]:
    """
    Extract a concise list of interactive elements, with multi-stage pruning.

    Stage 1: Structural Pruning (Viewport + Display)
        Filters elements that are hidden (display: none, visibility: hidden)
        or completely outside the current viewport.

    Stage 2: Semantic Pruning (target_element_types)
        If target_element_types is provided, filters elements whose role
        is not in the list (while always keeping safety roles from config).

    Args
    ----
    page : Page
        The active Playwright page.
    target_element_types : list[str] | None
        Optional list of ARIA roles to focus on. If provided, elements
        whose role is not in this list (or the safety set) are pruned.

    Returns
    -------
    list[dict[str, str]]
        A flat list of interactive elements after multi-stage pruning.
    """
    from backend.config import settings

    # ── Configuration ─────────────────────────────────────────────────────
    viewport_pruning = settings.viewport_pruning_enabled
    semantic_pruning = settings.semantic_pruning_enabled
    always_keep = set(settings.always_keep_roles)

    # ── Stage 0: Element Collection ──────────────────────────────────────
    # JS walk to find elements and their visibility/viewport status
    try:
        raw_elements = await page.evaluate(
            """(opts) => {
            const targetRoles = opts.targetRoles;
            const alwaysKeep = new Set(opts.alwaysKeep);
            const viewportPruning = opts.viewportPruning;

            const INTERACTIVE = new Set([
                'button','a','input','select','textarea','details',
                'summary','[role="button"]','[role="link"]','[role="textbox"]',
                '[role="combobox"]','[role="tab"]','[role="checkbox"]',
                '[role="radio"]','[role="switch"]','[role="menuitem"]',
                '[role="option"]','[role="searchbox"]','[role="slider"]',
                '[role="gridcell"]','[role="columnheader"]','[role="rowheader"]',
                'li.p-dropdown-item', 'li.p-select-option', 'li.p-menuitem'
            ]);
            const ROLE_MAP = {
                'a': 'link', 'button': 'button', 'input': 'textbox',
                'select': 'combobox', 'textarea': 'textbox',
                'details': 'group', 'summary': 'button'
            };

            const results = [];

            function queryAllPiercing(selector, root = document) {
                let els = Array.from(root.querySelectorAll(selector));
                const all = root.querySelectorAll('*');
                for (const el of all) {
                    if (el.shadowRoot) {
                        els = els.concat(queryAllPiercing(selector, el.shadowRoot));
                    }
                }
                return els;
            }

            const selector = Array.from(INTERACTIVE).join(',');
            const els = queryAllPiercing(selector);

            const vWidth = window.innerWidth || document.documentElement.clientWidth;
            const vHeight = window.innerHeight || document.documentElement.clientHeight;

            for (const el of els) {
                // 1. Basic visibility check (display: none / hidden)
                const style = window.getComputedStyle(el);
                if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') {
                    continue;
                }

                // 2. Viewport check
                const rect = el.getBoundingClientRect();
                const isInViewport = (
                    rect.top < vHeight &&
                    rect.bottom > 0 &&
                    rect.left < vWidth &&
                    rect.right > 0
                );

                if (viewportPruning && !isInViewport) {
                    continue;
                }

                const tag = el.tagName.toLowerCase();
                let role = el.getAttribute('role') || ROLE_MAP[tag] || tag;
                if (tag === 'li' && (el.classList.contains('p-dropdown-item') || el.classList.contains('p-select-option') || el.classList.contains('p-menuitem'))) {
                    role = (role === 'li' || role === 'unknown') ? 'option' : role;
                }
                let name = el.getAttribute('aria-label')
                    || el.getAttribute('placeholder')
                    || el.getAttribute('title')
                    || (el.innerText || '').trim().substring(0, 100);

                // PrimeNG paginator buttons
                if (!name && tag === 'button') {
                    const cls = el.className || '';
                    if (cls.includes('p-paginator-next')) name = 'Next Page';
                    else if (cls.includes('p-paginator-prev')) name = 'Previous Page';
                    else if (cls.includes('p-paginator-first')) name = 'First Page';
                    else if (cls.includes('p-paginator-last')) name = 'Last Page';
                    else if (cls.includes('p-paginator-page')) {
                        name = 'Page ' + (el.innerText || '').trim();
                    }
                }

                if (!name && el.tagName === 'INPUT') {
                    const label = document.querySelector(`label[for="${el.id}"]`);
                    if (label) name = label.innerText.trim().substring(0, 100);
                }

                const disabled = el.disabled || el.getAttribute('aria-disabled') === 'true';
                const checked = el.type === 'checkbox' || el.type === 'radio'
                    ? (el.checked ? 'checked' : 'unchecked') : null;
                const state = disabled ? 'disabled'
                    : checked ? checked : 'enabled';

                results.push({ role, name: name || '(unnamed)', state, isInViewport });
            }
            return results;
        }""",
            {"targetRoles": target_element_types, "alwaysKeep": list(always_keep), "viewportPruning": viewport_pruning},
        )

        if not raw_elements:
            return []

        # ── Stage 2: Semantic Pruning (Python-side) ─────────────────────────
        elements = []
        target_roles = set(target_element_types) if target_element_types else set()

        for el in raw_elements:
            role = el["role"].lower()
            # Prune if semantic pruning enabled AND a target list exists
            # AND the role is NOT in the target list AND NOT in the safety set.
            if semantic_pruning and target_roles:
                if role not in target_roles and role not in always_keep:
                    continue

            elements.append(
                {
                    "role": role,
                    "name": el["name"][:100],
                    "state": el["state"],
                    "in_viewport": "yes" if el["isInViewport"] else "no",
                }
            )

        # Cap at 75 elements (increased from 50 because pruning is much tighter now)
        _ELEMENT_CAP = 75
        if len(elements) > _ELEMENT_CAP:
            logger.debug("ARIA cap reached (%d) — truncating.", _ELEMENT_CAP)
            return elements[:_ELEMENT_CAP]

        logger.info(
            "Extracted %d interactive elements (pruning: viewport=%s, semantic=%s)",
            len(elements),
            viewport_pruning,
            bool(target_roles) if semantic_pruning else "off",
        )
        return elements

    except Exception as e:
        logger.warning("Failed to extract interactive elements: %s", str(e))
        return []


async def extract_interactive_summary(
    page: Page,
    max_elements: int = 75,
    target_element_types: list[str] | None = None,
) -> str:
    """
    Return a compact, token-efficient string listing ONLY interactive elements.

    Unlike ``extract_accessibility_tree()``, this function:
    - Returns only actionable elements (buttons, links, inputs, etc.)
    - Never truncates mid-list (hard cap at max_elements instead)
    - Produces a consistent, compact format the LLM can parse reliably
    - Uses ``extract_interactive_elements()`` which already handles the
      multi-stage pruning (viewport + semantic).

    This is the PRIMARY signal passed to the planner LLM.

    Args
    ----
    page : Page
        The active Playwright page.
    max_elements : int
        Maximum number of interactive elements to include. Default 75.
    target_element_types : list[str] | None
        Optional list of ARIA roles to focus on for this step.

    Returns
    -------
    str
        Formatted multi-line string of interactive elements.
    """
    try:
        elements = await extract_interactive_elements(page, target_element_types)
        if not elements:
            # Fall back to first 2000 chars of raw tree if no interactive elements found
            raw = await extract_accessibility_tree(page)
            return f"INTERACTIVE ELEMENTS (fallback — raw tree):\n{_prune_snapshot(raw)[:1800]}"

        # Cap at max_elements to guarantee predictable prompt size
        capped = elements[:max_elements]
        overflow = len(elements) - len(capped)

        lines = [
            f"INTERACTIVE ELEMENTS ({len(elements)} found{', showing first ' + str(max_elements) if overflow > 0 else ''}):"
        ]
        for el in capped:
            role = el.get("role", "?")
            name = el.get("name", "")
            state = el.get("state", "enabled")
            in_v = el.get("in_viewport", "yes")
            name_part = f' "{name}"' if name else " (no name)"
            viewport_part = " [OFF-SCREEN]" if in_v == "no" else ""
            lines.append(f"[{role}]{name_part} ({state}){viewport_part}")

        if overflow > 0:
            lines.append(f"... ({overflow} more elements not shown — scroll or filter to see)")

        return "\n".join(lines)

    except Exception as e:
        logger.warning("Failed to extract interactive summary: %s", str(e))
        # Graceful fallback to raw tree
        try:
            raw = await extract_accessibility_tree(page)
            return _prune_snapshot(raw)[:2000]
        except Exception:
            return "(interactive elements unavailable)"
