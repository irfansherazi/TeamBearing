"""
vQA — Playwright Action Executor Node
=======================================
Module: backend/engine/executor.py

Implements the **ACT** phase of the see-think-act loop.

This node reads the ``planned_action`` JSON from the planner and
translates it into a live Playwright browser interaction.  After the
action completes (or fails), it:

  1. Captures a post-action screenshot and uploads it to S3
  2. Builds an ``ExecutionStep`` entry with full audit metadata
  3. Appends the entry to ``detailed_execution_log``

Action Dispatch Table
---------------------
The executor supports these action types (matching the planner's
output contract):

    ┌────────────────┬──────────────────────────────────────────────────┐
    │ action         │ Playwright call                                  │
    ├────────────────┼──────────────────────────────────────────────────┤
    │ click          │ page.get_by_role(role, name=name).click()       │
    │ fill           │ page.get_by_role(role, name=name).fill(value)   │
    │ select_option  │ page.get_by_role("combobox").select_option(val) │
    │ check          │ page.get_by_role("checkbox", name=name).check() │
    │ uncheck        │ page.get_by_role("checkbox").uncheck()          │
    │ navigate       │ page.goto(value)                                │
    │ wait           │ page.wait_for_timeout(ms) / networkidle         │
    │ verify         │ page.get_by_role(role, name=name).is_visible()  │
    │ scroll         │ page.mouse.wheel(0, ±300)                      │
    │ press_key      │ page.keyboard.press(value)                      │
    │ set_input_files│ page.locator(selector).set_input_files(path)    │
    │ done           │ no-op (signals AC step completion)              │
    └────────────────┴──────────────────────────────────────────────────┘

Locator Strategy Priority
--------------------------
The planner indicates the locator strategy, but the executor always
prefers this order for resilience:

  1. ``get_by_role(role, name=name)`` — most reliable, auto-waits
  2. ``get_by_text(name)``           — fallback for text-based matching
  3. ``get_by_label(name)``          — for form inputs with labels
  4. ``get_by_placeholder(name)``    — for placeholder-only inputs

All locators use Playwright's built-in auto-waiting (default 30s
timeout), which handles loading spinners and async UI updates
automatically.

Dependencies
------------
  - ``playwright.async_api``          — browser interaction
  - ``backend/browser/context.py``    — BrowserManager registry
  - ``backend/browser/screenshot.py`` — post-action capture + S3 upload
  - ``backend/config.py``             — S3 settings

See Also
--------
  - ``backend/engine/planner.py``   — produces planned_action
  - ``backend/engine/evaluator.py`` — evaluates the action result
  - ``backend/engine/state.py``     — ExecutionStep definition
"""

import base64
import difflib
import logging
import re as _re_executor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from playwright.async_api import Page
from playwright.async_api import TimeoutError as PlaywrightTimeout

from backend.browser.a11y_resolver import A11yLocatorResolver  # accessibility-tree-grounding Phase 2
from backend.browser.context import get_manager
from backend.browser.cv_resolver import CvFallbackResolver  # FEAT-037: CV Fallback Layer
from backend.browser.screenshot import capture_screenshot_b64  # FEAT-062
from backend.config import settings
from backend.engine.fixture_manager import FixtureManager
from backend.engine.recipe_runner import (
    RecipeConfigurationError,
    RecipeNotFoundError,
    RecipeParameterError,
    execute_recipe,
    fill_recipe,
    recipe_registry,
)
from backend.engine.state import ExecutionStep, VQAState
from backend.engine.state_tracker import get_tracker
from backend.engine.verifier import cv_fallback_state_change_check  # FEAT-037 Phase 3

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Asset Inventory — scan storage/test_files at load time
# ---------------------------------------------------------------------------
# Maps filename → absolute path for all test assets available for
# file upload simulation via set_input_files.

ASSET_INVENTORY: dict[str, str] = {}
_asset_dir = Path(__file__).parent.parent.parent.parent / "vsuitePlatform" / "playwright" / "storage" / "test_files"
if _asset_dir.exists():
    for _f in sorted(_asset_dir.iterdir()):
        if _f.is_file():
            ASSET_INVENTORY[_f.name] = str(_f.resolve())
    logger.info(
        "Asset Inventory: loaded %d test files from %s",
        len(ASSET_INVENTORY),
        _asset_dir,
    )
else:
    logger.warning(
        "Asset Inventory: directory not found: %s — set_input_files will be unavailable",
        _asset_dir,
    )


# ---------------------------------------------------------------------------
# Accessibility Tree Grounding — Phase 2 (accessibility-tree-grounding)
# ---------------------------------------------------------------------------
# Module-level singleton for A11yLocatorResolver.
# Used by _dispatch_action when settings.a11y_resolver_enabled is True.
# Two-flag shadow-mode: a11y_enrichment_enabled (Phase 3) populates the ARIA
# fields on TestPlanStep; a11y_resolver_enabled (Phase 2) consumes them here.

_A11Y_RESOLVER: A11yLocatorResolver = A11yLocatorResolver()


# ---------------------------------------------------------------------------
# Fix 1: Hard-block Browse/Upload/Choose File clicks
# ---------------------------------------------------------------------------
# These keywords in the target name indicate the LLM is trying to trigger
# a native OS file dialog — Playwright CANNOT interact with it.  The action
# is intercepted and returned as a structured failure with a correction hint.

_BROWSE_BUTTON_KEYWORDS = frozenset(
    [
        "browse",
        "upload",
        "choose file",
        "choose files",
        "select file",
        "select files",
        "add file",
        "add files",
        "attach file",
        "attach files",
        "import file",
    ]
)


def _is_browse_click(action: dict[str, Any]) -> bool:
    """
    Return True if the action is a click on a file-picker trigger button.

    The LLM sometimes ignores the FILE_UPLOAD_RULES prompt instruction and
    tries to click Browse/Upload buttons, which opens a native OS dialog
    that Playwright cannot interact with.  This check is a hard Python
    gate — no prompt can override it.

    Uses word-boundary matching so that status badges like "Needs Uploading"
    are NOT blocked — "upload" must appear as a standalone word, not embedded
    inside "uploading" or similar verb forms.
    """
    if action.get("action") != "click":
        return False
    name = (action.get("name") or "").lower().strip()
    value = (action.get("value") or "").lower().strip()
    selector = (action.get("selector") or "").lower().strip()
    # Word-boundary match: "upload" blocks "Upload Files" but NOT "Needs Uploading"
    # because in "uploading" the 'd' is followed by 'i' (word char) — no boundary.
    for kw in _BROWSE_BUTTON_KEYWORDS:
        pattern = r"\b" + _re_executor.escape(kw) + r"\b"
        if _re_executor.search(pattern, name) or _re_executor.search(pattern, value):
            return True
    # Check CSS selector patterns that target file inputs
    if "fileupload" in selector and "input" not in selector:
        return True
    return False


def _format_asset_list(max_items: int = 5, max_name_len: int = 45) -> str:
    """Return a compact, token-efficient list of available test files."""
    names = list(ASSET_INVENTORY.keys())[:max_items]
    truncated = [n[:max_name_len] + "…" if len(n) > max_name_len else n for n in names]
    suffix = f" (+{len(ASSET_INVENTORY) - max_items} more)" if len(ASSET_INVENTORY) > max_items else ""
    return str(truncated) + suffix


# ---------------------------------------------------------------------------
# Fix 3: Idempotency — spot/order detail panel already open
# ---------------------------------------------------------------------------
# Selectors that indicate the right-side detail panel is already visible.
# If the panel is open and the agent clicks a table row again, we short-
# circuit to success instead of wasting an action cycle.

# MIGRATION: Detail panel selectors now sourced from the active AppProfile.
# The list is resolved at first call time (lazy) to avoid circular imports.
_DETAIL_PANEL_SELECTORS_CACHE: list[str] | None = None


def _get_detail_panel_selectors() -> list[str]:
    """Return detail panel selectors from the active profile."""
    global _DETAIL_PANEL_SELECTORS_CACHE
    if _DETAIL_PANEL_SELECTORS_CACHE is None:
        try:
            from backend.profiles import get_active_profile

            sels = get_active_profile().detail_panel_selectors
            if sels:
                _DETAIL_PANEL_SELECTORS_CACHE = sels
        except Exception:
            pass
        if _DETAIL_PANEL_SELECTORS_CACHE is None:
            # Fallback: hardcoded vSuite selectors (backward compat)
            _DETAIL_PANEL_SELECTORS_CACHE = [
                "app-spot-detail",
                ".spot-detail-panel",
                "app-production-order-detail",
                ".detail-panel",
                ".slideout-panel.open",
                "app-quick-order",
            ]
    return _DETAIL_PANEL_SELECTORS_CACHE


# MIGRATION: Load profile-sourced selectors (overrides hardcoded list above)
try:
    from backend.profiles import get_active_profile as _gap_exec

    _exec_profile = _gap_exec()
    if _exec_profile.detail_panel_selectors:
        _DETAIL_PANEL_SELECTORS = _exec_profile.detail_panel_selectors
except Exception:
    pass  # Use hardcoded fallback above


async def _is_panel_already_open(page: Page) -> bool:
    """
    Return True if a details/slideout panel is already visible.

    Used to prevent redundant clicks on table rows that would just
    re-trigger an already-open panel — wasting action cycles and
    potentially causing state confusion.
    """
    for sel in _get_detail_panel_selectors():
        try:
            count = await page.locator(sel).count()
            if count > 0:
                visible = await page.locator(sel).first.is_visible()
                if visible:
                    return True
        except Exception:
            pass
    return False


# ---------------------------------------------------------------------------
# T1-a: Component-Aware Precondition Check
# ---------------------------------------------------------------------------
# Known "closed" container selectors in PrimeNG 19 / Angular 19 (vSuite).
# When a click target text is found inside one of these containers and the
# container is in its closed state, the element cannot be interacted with
# via a text-target click — the overlay has not been opened yet.
# The executor surfaces TARGET_INSIDE_CLOSED_CONTAINER so the planner
# emits the correct open-trigger action before retrying.
#
# The trigger_selector returned is derived by querying document.body for a
# close-container ancestor and extracting its CSS identity.  This gives the
# planner a concrete selector to click in order to open the overlay.
#
# TODO: extend CLOSED_CONTAINER_SELECTORS with confirmed PrimeNG 19 variants
# once QA-358 re-run (AC-INTEGRATION-1) surfaces edge cases.

_CLOSED_CONTAINER_SELECTORS: list[str] = [
    "p-select-overlay:not(.p-select-overlay-open)",
    "p-dropdown-panel[aria-hidden='true']",
    "select",  # native <select> — always closed until clicked
    "p-autocomplete[aria-expanded='false']",
]

# JS snippet to get a stable CSS identity for the closed container's trigger.
# Returns a selector string, or empty string if not derivable.
_TRIGGER_SELECTOR_JS = """
(containerEl) => {
    try {
        // Walk up from the container to find a meaningful trigger ancestor.
        // For PrimeNG p-select-overlay, the trigger is the sibling p-select element.
        let el = containerEl;
        while (el && el !== document.body) {
            // p-select: return a specific selector if available
            if (el.tagName && el.tagName.toLowerCase() === 'p-select') {
                const name = el.getAttribute('ng-reflect-name') || el.getAttribute('id') || '';
                return name ? `p-select[ng-reflect-name="${name}"]` : 'p-select';
            }
            if (el.tagName && el.tagName.toLowerCase() === 'p-autocomplete') {
                const name = el.getAttribute('ng-reflect-name') || el.getAttribute('id') || '';
                return name ? `p-autocomplete[ng-reflect-name="${name}"]` : 'p-autocomplete';
            }
            if (el.tagName && el.tagName.toLowerCase() === 'select') {
                const id = el.getAttribute('id') || el.getAttribute('name') || '';
                return id ? `select[name="${id}"]` : 'select';
            }
            el = el.parentElement;
        }
        // Fallback: return tag name of the container
        return containerEl.tagName ? containerEl.tagName.toLowerCase() : '';
    } catch(e) {
        return '';
    }
}
"""


async def _is_target_in_open_container(
    page: Page, target_text: str
) -> tuple[bool, str | None]:
    """
    Check if *target_text* is inside a known closed PrimeNG/Angular container.

    Returns
    -------
    (True, trigger_selector)
        The text is inside a closed container that must be opened first.
        *trigger_selector* is a non-empty CSS selector for the container's
        trigger element (the element the planner should click to open it).
    (False, None)
        The text is not inside any known closed container — proceed normally.

    This check runs before the click dispatch in _dispatch_action.  It is
    intentionally fast: a DOM query per selector, bail on first match.
    On any exception, it returns (False, None) so a check error never blocks
    a legitimate click.
    """
    for container_sel in _CLOSED_CONTAINER_SELECTORS:
        try:
            container_loc = page.locator(container_sel)
            count = await container_loc.count()
            if count == 0:
                continue
            # Container is present (closed) — does it contain target_text?
            target_in_container = container_loc.get_by_text(target_text)
            target_count = await target_in_container.count()
            if target_count == 0:
                continue
            # Match: target is inside this closed container.
            # Derive a trigger selector via JS evaluation on the first match.
            trigger_selector: str | None = None
            try:
                container_el = await page.query_selector(container_sel)
                if container_el is not None:
                    raw = await container_el.evaluate(_TRIGGER_SELECTOR_JS)
                    trigger_selector = raw.strip() if raw else None
            except Exception:
                trigger_selector = None
            if not trigger_selector:
                # Fallback: use the container selector itself as the hint
                trigger_selector = container_sel
            return True, trigger_selector
        except Exception:
            # Never let a precondition check block a legitimate click
            continue
    return False, None


# ---------------------------------------------------------------------------
# Custom exception for action pre-validation failures
# ---------------------------------------------------------------------------


class ActionValidationError(ValueError):
    """Raised when a planned action fails pre-validation checks.

    This exception is caught by _dispatch_action and returned as a
    structured failure dict so the evaluator feeds the error back
    to the planner for retry — instead of crashing the graph.
    """

    pass


# ---------------------------------------------------------------------------
# DOM stability helper
# ---------------------------------------------------------------------------


async def _wait_for_app_spinners(page: Page, timeout_ms: int = 10000) -> None:
    """
    Wait for application-specific loading indicators to disappear.

    Spinner selectors are sourced from the active AppProfile.
    Fallback: hardcoded PrimeNG/vSuite selectors for backward compatibility.

    Called automatically after every browser action to eliminate the need
    for the planner to explicitly plan wait steps for loading states.

    Args
    ----
    page : Page
        The active Playwright page.
    timeout_ms : int
        Maximum time to wait for each spinner selector (default 10s).
    """
    # MIGRATION: selectors now sourced from the active AppProfile.
    try:
        from backend.profiles import get_active_profile as _gap_spin

        _spinner_sels = _gap_spin().spinner_selectors
    except Exception:
        _spinner_sels = None

    SPINNER_SELECTORS = (
        _spinner_sels
        if _spinner_sels
        else [
            ".p-datatable-loading-overlay",
            ".p-datatable-loading-icon",
            ".vcreative-icon.loading",
            ".loading-overlay",
            ".ui-blockui",
            ".p-blockui",
        ]
    )
    for sel in SPINNER_SELECTORS:
        try:
            locator = page.locator(sel)
            # Only wait if the spinner is actually present
            if await locator.count() > 0:
                await page.wait_for_selector(sel, state="detached", timeout=timeout_ms)
                logger.debug("App spinner '%s' detached", sel)
        except Exception:
            pass  # Spinner not present or already gone — safe to continue


async def _wait_for_stable_dom(page: Page, timeout_ms: int = 8000) -> None:
    """
    Wait until the DOM stops mutating after a Playwright action.

    vSuite has permanent background polling (WebSocket heartbeat, prod-orders
    refresh interval) so ``networkidle`` NEVER fires — calling it wastes the
    entire ``timeout_ms`` budget (typically 8 s) on every click.  We removed
    it from the primary path in favour of two cheaper strategies:

    Strategy (revised — no networkidle):
    1. Angular micro-task fence: evaluate ``Promise.resolve()`` via
       ``setTimeout(resolve, 0)``.  By the time this resolves, Zone.js has
       processed all synchronous state updates triggered by the last click.
    2. DOM-length stability poll: 3 consecutive identical
       ``document.body.innerHTML.length`` reads at 200 ms intervals confirms
       the Angular change-detection cycle is complete.  Budget: 5 s (25×200).

    Args
    ----
    page : Page
        The active Playwright page.
    timeout_ms : int
        Legacy parameter retained for call-site compatibility.  Not used
        by the new strategy; the DOM poll cap is fixed at 5 s.
    """
    # ── Tier 1: Angular micro-task fence ───────────────────────────────
    # Schedule a macro-task via setTimeout(0); by the time it executes,
    # Angular's Zone.js has processed all synchronous change-detection
    # work triggered by the previous browser event.
    try:
        await page.evaluate("() => new Promise(resolve => setTimeout(resolve, 0))")
    except Exception:
        pass  # Page navigated or context closed — safe to continue

    # ── Tier 2: PrimeNG overlay animation settle ──────────────────────
    # PrimeNG dropdowns/panels animate in over 200–400 ms via CSS transitions.
    # innerHTML.length stabilises before the animation finishes, causing the
    # next action to fire while the overlay is still mid-transition.
    # We wait up to 500 ms for any open PrimeNG overlay portal to disappear
    # from the "animating" state before proceeding.
    try:
        await page.evaluate("""
            () => new Promise(resolve => {
                const sel = '.p-select-overlay,.p-dropdown-panel,.p-autocomplete-panel,.p-tieredmenu,.p-menu';
                const el = document.querySelector(sel);
                if (!el) { resolve(); return; }
                // If already stable (no transition running), resolve immediately
                const cs = window.getComputedStyle(el);
                if (cs.opacity === '1' && cs.visibility !== 'hidden') { resolve(); return; }
                const tid = setTimeout(resolve, 500);
                el.addEventListener('transitionend', () => { clearTimeout(tid); resolve(); }, {once: true});
            })
        """)
    except Exception:
        pass

    # ── Tier 3: DOM stability poll ───────────────────────────────────
    # 3 consecutive identical innerHTML.length reads = no mutation happening.
    prev_len = -1
    stable_count = 0
    for _ in range(25):  # 25 × 200 ms = 5 s max budget
        try:
            current_len = await page.evaluate("() => document.body.innerHTML.length")
        except Exception:
            break
        if current_len == prev_len:
            stable_count += 1
            if stable_count >= 3:
                return
        else:
            stable_count = 0
        prev_len = current_len
        await page.wait_for_timeout(200)


async def _resolve_locator(page: Page, action: dict[str, Any]):
    """
    Resolve a Playwright locator from the planned action JSON.

    Translates the LLM's locator strategy and element identifiers into
    a Playwright Locator object.

    Args
    ----
    page : Page
        The active Playwright page.

    action : dict
        The planned action JSON containing ``strategy``, ``role``,
        ``name``, and optionally ``value``.

    Returns
    -------
    playwright.async_api.Locator
        A Playwright locator that can be clicked, filled, etc.

    Raises
    ------
    ValueError
        If the locator strategy is unrecognised.

    Example
    -------
    >>> locator = await _resolve_locator(page, {
    ...     "strategy": "get_by_role",
    ...     "role": "button",
    ...     "name": "Submit All"
    ... })
    """
    strategy: str = action.get("strategy", "get_by_role")
    role: str = action.get("role", "")
    name: str = action.get("name", "")

    # ── container_selector scoping ────────────────────────────────
    # When provided, scope the locator to the given CSS ancestor.
    # This resolves STRICT_MODE_VIOLATION errors where a name (e.g. 'Client')
    # appears many times on the page but only once inside a specific container
    # (e.g. the sort popover).  Using a scoped base is always safer than .first.
    container_selector: str = action.get("container_selector", "") or ""
    base = page.locator(container_selector) if container_selector else page

    if strategy == "get_by_role":
        if not role:
            raise ValueError(
                "get_by_role requires a non-empty 'role' — LLM returned an empty role. "
                "Use get_by_text or get_by_label instead."
            )
        if not name:
            raise ValueError(
                f"FORBIDDEN: get_by_role('{role}') without 'name' — this resolves to ALL "
                f"'{role}' elements on the page and will crash with 'Role must not be empty' "
                f"or time out. Provide the element's visible text in 'name'."
            )
        return base.get_by_role(role, name=name)

    elif strategy == "get_by_text":
        # Support exact=True for precise text matching — prevents substring collisions
        # e.g. "Days" matching "/ Days", or "Start" matching "Start Date".
        exact: bool = bool(action.get("exact", False))
        return base.get_by_text(name, exact=exact)

    elif strategy == "get_by_label":
        return base.get_by_label(name)

    elif strategy == "get_by_placeholder":
        return base.get_by_placeholder(name)

    elif strategy == "css_selector":
        # Direct CSS selector (e.g. "th.po-col-clientCol", "p-select#header-sort-drop-down-duedaysCol")
        # Used by the blueprint for table header and dropdown-sort targets where
        # get_by_role / get_by_text are explicitly anti-patterns.
        selector = name or action.get("selector", "")
        if not selector:
            raise ValueError(
                "css_selector requires a non-empty selector in 'name' or 'selector'. "
                'Example: {"strategy": "css_selector", "name": "th.po-col-clientCol"}'
            )
        # For css_selector the selector itself is the full locator; container_selector
        # is applied as a scope if present.
        return base.locator(selector) if container_selector else page.locator(selector)

    elif strategy in ("window", "coordinate_action"):
        # ── FEAT-067: Graceful exclusion ──────────────────────────
        # These strategies do not resolve to locators in the traditional
        # sense. 'window' targets the global browser, and 'coordinate_action'
        # uses vision coordinates. Returning None allows callers (like
        # RAG validators) to gracefully ignore them.
        return None

    else:
        # Default fallback: try get_by_role if we have role info,
        # otherwise get_by_text
        if role and name:
            logger.warning(
                "Unknown strategy '%s', falling back to get_by_role(%s, name='%s')",
                strategy,
                role,
                name,
            )
            return page.get_by_role(role, name=name)
        elif name:
            logger.warning(
                "Unknown strategy '%s', falling back to get_by_text('%s')",
                strategy,
                name,
            )
            return page.get_by_text(name)
        else:
            raise ValueError(f"Cannot resolve locator: strategy='{strategy}', role='{role}', name='{name}'")


# ---------------------------------------------------------------------------
# Accessibility Tree Grounding — A11y-first locator helper (Phase 2)
# ---------------------------------------------------------------------------


async def _resolve_locator_a11y_first(
    page: Page,
    action: dict[str, Any],
    run_id: str = "unknown",
    state: dict[str, Any] | None = None,
) -> Any:
    """
    A11y-first wrapper around ``_resolve_locator``.

    When ``settings.a11y_resolver_enabled`` is ``True`` **and** the action
    carries ``_aria_role`` (injected by the executor loop from the current
    ``TestPlanStep``), delegates to ``_A11Y_RESOLVER.resolve()`` first.
    The resolver returns ``(locator, resolution_path)``.

    * On ``selector_only_legacy`` (``_aria_role`` is ``None``) — falls through
      to the original ``_resolve_locator`` call so the legacy path is
      bit-for-bit identical (``AC-VERIFY-9``).
    * On ``cv_fallback_required`` — returns ``None``; the caller's existing
      CV/SoM escalation path handles it.
    * On any a11y path (primary / normalized / selector_fallback / …) —
      returns the resolved locator directly.

    Phase 3 addition: writes ``state["last_resolution_path"]`` when ``state``
    is provided, so the recovery router's ``_classify_for_recovery`` can
    promote ``selector_fallback_ambiguous`` to ``A11Y_AMBIGUOUS`` recovery
    (Algorithm Decision 2 — accessibility-tree-grounding).

    When the flag is off (default ``False``) or ``_aria_role`` is absent,
    this function is a transparent pass-through to ``_resolve_locator``.

    Returns
    -------
    playwright.async_api.Locator | None
        Same contract as ``_resolve_locator``.
    """
    aria_role: str | None = action.get("_aria_role")

    if settings.a11y_resolver_enabled and aria_role is not None:
        aria_name: str | None = action.get("_aria_name")
        locator, resolution_path = await _A11Y_RESOLVER.resolve(
            page,
            aria_role=aria_role,
            aria_name=aria_name,
            action=action,
            run_id=run_id,
        )
        logger.debug(
            "A11Y_FIRST: run_id=%s aria_role=%s aria_name=%r resolution_path=%s",
            run_id,
            aria_role,
            aria_name,
            resolution_path,
        )
        # Phase 3: propagate resolution_path into state for recovery classifier
        if state is not None:
            state["last_resolution_path"] = resolution_path
        if resolution_path == "cv_fallback_required":
            return None  # Caller's existing CV escalation handles this
        return locator

    # Flag off or no ARIA fields — legacy path, unchanged behavior
    return await _resolve_locator(page, action)


# ---------------------------------------------------------------------------
# Action dispatchers
# ---------------------------------------------------------------------------


async def _dismiss_overlays(page: Page, run_id: str = "unknown") -> None:
    """
    Attempt to proactively dismiss open overlays by pressing Escape.
    """
    try:
        from backend.engine.state_tracker import get_tracker

        _tracker = get_tracker(run_id)
        if _tracker and _tracker.has_open_overlay():
            _constraint = _tracker.get_overlay_constraint()
            if not _constraint.get("is_functional", False):
                logger.info("[%s] _dismiss_overlays: overlay detected, pressing Escape", run_id)
                await page.keyboard.press("Escape")
                await page.wait_for_timeout(300)
            try:
                await _tracker.refresh(page)
            except Exception:
                pass
    except Exception as e:
        logger.warning("[%s] _dismiss_overlays failed: %s", run_id, str(e)[:100])


async def _extract_page_text(page: "Page") -> str:  # type: ignore[name-defined]
    """
    Extract visible text from the page for verify action text-matching.

    Bug G fix: `document.body.innerText` misses text rendered inside
    PrimeNG `p-datatable` tables and Angular virtual-scroll components
    because the rows are rendered inside Angular component boundaries that
    `innerText` on `document.body` does not traverse.

    Strategy:
      1. Capture `document.body.innerText` (fast, works for most UI elements).
      2. If that result is short (< 80 chars), ALSO query table-specific
         selectors via a single JS call that collects text from:
           - `tbody tr td`       (nested HTML tables in PrimeNG)
           - `[role='row']`      (ARIA row elements)
           - `.p-datatable-tbody` (PrimeNG datatable body container)
      3. Combine both sources (deduplication via join).

    Always returns a string; never raises.
    """
    _TABLE_TEXT_JS = """
        () => {
            const parts = [];
            // Standard <tbody> cells nested inside PrimeNG
            const cells = document.querySelectorAll('tbody tr td');
            if (cells.length) {
                const cellText = Array.from(cells)
                    .map(c => (c.innerText || c.textContent || '').trim())
                    .filter(Boolean)
                    .join(' ');
                if (cellText) parts.push(cellText);
            }
            // ARIA row elements (PrimeNG virtual scroll renders these)
            const rows = document.querySelectorAll("[role='row']");
            if (rows.length) {
                const rowText = Array.from(rows)
                    .map(r => (r.innerText || r.textContent || '').trim())
                    .filter(Boolean)
                    .join(' ');
                if (rowText) parts.push(rowText);
            }
            // PrimeNG datatable body container
            const dtBody = document.querySelector('.p-datatable-tbody');
            if (dtBody) {
                const dtText = (dtBody.innerText || dtBody.textContent || '').trim();
                if (dtText) parts.push(dtText);
            }
            return parts.join(' ');
        }
    """
    body_text = ""
    try:
        body_text = await page.evaluate("() => document.body.innerText")
    except Exception:
        pass

    # If body text is long enough, skip the table fallback for performance.
    # Threshold: 80 chars covers a typical loading-state body ("Loading...\n").
    if len(body_text) >= 80:
        return body_text

    # Body text is empty or very sparse — attempt table-specific fallback.
    table_text = ""
    try:
        table_text = await page.evaluate(_TABLE_TEXT_JS)
    except Exception:
        pass

    if table_text:
        return f"{body_text} {table_text}".strip()
    return body_text


async def _check_angular_readiness(page: Page, action: dict[str, Any], run_id: str) -> dict[str, Any] | None:
    """
    Query the Angular bridge to verify component readiness before an action.
    Returns a failure dict if the component is blocked, or None if ready.
    """
    strategy = action.get("strategy")
    if strategy != "css_selector":
        return None  # Bridge currently requires CSS selectors for precise targeting

    selector = action.get("name") or action.get("selector")
    if not selector:
        return None

    try:
        manager = get_manager(run_id)
        # Use a strict 800ms timeout for the bridge probe
        import asyncio
        state = await asyncio.wait_for(
            manager.query_angular(selector, "getComponentState"),
            timeout=0.8
        )

        if not state:
            return None # Bridge couldn't find component or not Angular, proceed with Playwright defaults

        if isinstance(state, dict) and state.get("error"):
            return None

        disabled = state.get("disabled")
        readonly = state.get("readonly")

        if disabled:
            return {
                "success": False,
                "error_message": f"Action blocked: Component '{selector}' is disabled at the Angular level.",
                "actual_url": page.url,
                "dom_failure_diagnosis": "ANGULAR_DISABLED: The component is disabled in Angular state.",
            }
        if readonly and action.get("action") == "fill":
            return {
                "success": False,
                "error_message": f"Action blocked: Component '{selector}' is read-only at the Angular level.",
                "actual_url": page.url,
                "dom_failure_diagnosis": "ANGULAR_READONLY: The component is read-only in Angular state.",
            }
    except Exception as e:
        logger.debug("[%s] Angular readiness check skipped: %s", run_id, e)
    
    return None


async def _dispatch_action(
    page: Page,
    action: dict[str, Any],
    target_url: str = "",
    state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Execute the planned action on the Playwright page.
    """
    if state is None:
        state = {}
    action_type: str = action.get("action", "")
    strategy: str = action.get("strategy", "")
    mark_id = action.get("mark_id")

    # ── Normalize click/fill actions with coordinate_action strategy or mark_id ──
    if action_type in ("click", "fill") and (strategy == "coordinate_action" or mark_id is not None):
        if action_type == "fill" and not action.get("text_to_fill") and action.get("value"):
            action["text_to_fill"] = action.get("value")
        action_type = "coordinate_action"
        action["action"] = "coordinate_action"
        action["strategy"] = "coordinate_action"
        strategy = "coordinate_action"

    value: str = action.get("value", "") or ""
    run_id: str = action.get("_run_id", "unknown")

    # ── Phase 2: Fail-Fast Angular Probes (TASK-091) ──────────────
    if action_type in ("click", "fill", "check", "uncheck", "select_option"):
        failure = await _check_angular_readiness(page, action, run_id)
        if failure:
            return failure

    # ── FIX 4: Proactive Overlay Dismissal (TASK-008) ─────────────
    # PROBLEM: Oscillation loops occur when an overlay (modal, dropdown) blocks
    # the target element, but the planner doesn't realize it needs to dismiss
    # the overlay first.
    # SOLUTION: If an overlay is open and the target is OUTSIDE it, proactively
    # press Escape to clear the blocker before attempting the action.
    if action_type != "press_key" or (value != "Escape" and value != "Esc"):
        _tracker = get_tracker(run_id)
        if _tracker and _tracker.has_open_overlay():
            _constraint = _tracker.get_overlay_constraint()
            if _constraint.get("active"):
                overlay_selector = _constraint.get("selector", "")
                target_container = action.get("container_selector", "") or ""

                # If target is inside the overlay, do not dismiss.
                # "Inside" means target_container contains overlay_selector.
                is_inside = (
                    overlay_selector and overlay_selector in target_container
                    if target_container and overlay_selector
                    else False
                )

                is_functional = _constraint.get("is_functional", False)

                if not is_inside and not is_functional:
                    logger.info(
                        "[%s] Proactive Dismissal: overlay open (%s) but target is outside (%s). "
                        "Pressing Escape to dismiss.",
                        run_id,
                        overlay_selector,
                        target_container,
                    )
                    await page.keyboard.press("Escape")
                    await page.wait_for_timeout(300)
                    # Refresh tracker after dismissal so downstream logic knows it's gone
                    try:
                        await _tracker.refresh(page)
                    except Exception:
                        pass

    # ── Pre-validation: catch invalid actions before Playwright call ───
    # This prevents crashes from empty locators, missing names, and
    # invalid strategies.  Errors are returned as structured failures
    # for the evaluator to feed back to the planner.
    strategy: str = action.get("strategy", "")
    role: str = action.get("role", "")
    name: str = action.get("name", "")
    LOCATOR_ACTIONS = {
        "click",
        "fill",
        "check",
        "uncheck",
        "select_option",
        "verify",
        "fill_and_submit",
        "click_and_wait",
        "select_and_verify",
    }

    # ── FIX 1: Hard-block Browse/Upload clicks ────────────────────────
    # This is a PYTHON CONSTRAINT — the LLM cannot override it via prompt.
    # If the planner outputs click("Browse"), we intercept here and tell
    # it to use set_input_files instead.  Zero tolerance.
    if _is_browse_click(action):
        fallback_file = next(
            (k for k in ASSET_INVENTORY if "audio" in k.lower() or ".mp3" in k.lower()),
            next(iter(ASSET_INVENTORY), "test_audio.mp3"),
        )
        logger.warning(
            "BLOCKED: LLM tried to click a Browse/Upload button '%s' — redirecting to set_input_files instruction",
            name,
        )
        return {
            "success": False,
            "error_message": (
                f"ActionValidationError: BLOCKED — clicking '{name}' triggers a native OS "
                f"file dialog that Playwright CANNOT interact with. You MUST use the "
                f"set_input_files action instead. "
                f'Correct usage: {{"action": "set_input_files", '
                f'"selector": "p-fileupload input[type=\'file\']", '
                f'"value": "{fallback_file}"}}. '
                f"Available files: {_format_asset_list()}"
            ),
            "actual_url": page.url,
            "dom_failure_diagnosis": (
                "HARD_BLOCK_BROWSE: The executor intercepted a click on a "
                "file upload trigger button.  This is a hard Python constraint — "
                "use set_input_files action with a CSS selector targeting "
                f"input[type='file'] and a filename from the asset inventory. "
                f"Safe default: '{fallback_file}'."
            ),
        }

    # ── FIX 3: Idempotency — panel already open ───────────────────────
    # If the agent clicks a table row (to open a detail panel) but the
    # panel is ALREADY visible, skip the click and return success.
    # This prevents the infinite loop where the agent keeps clicking
    # the same row expecting a state change.
    if action_type == "click" and name:
        name.lower()
        # Heuristic: table row clicks typically target client names,
        # spot titles, or order IDs — not buttons or links.
        row_click_signals = [
            role in ("", "cell", "row", "gridcell", "link") and strategy in ("get_by_text", "get_by_role", ""),
        ]
        if any(row_click_signals):
            try:
                panel_open = await _is_panel_already_open(page)
                if panel_open:
                    logger.info(
                        "IDEMPOTENCY: panel already open — skipping click on '%s'",
                        name,
                    )
                    return {
                        "success": True,
                        "error_message": None,
                        "actual_url": page.url,
                        "last_executor_fallback": (f"IDEMPOTENCY_SKIP: panel already open, skipped click on '{name}'"),
                    }
            except Exception:
                pass  # If panel check fails, proceed with click normally

    if action_type in LOCATOR_ACTIONS and strategy:
        if strategy == "get_by_role":
            if not role:
                return {
                    "success": False,
                    "error_message": (
                        f"ActionValidationError: get_by_role requires a non-empty 'role'. "
                        f"You provided: strategy='get_by_role', role='', name='{name}'. "
                        f'Correct syntax: {{"strategy": "get_by_role", "role": "button", '
                        f'"name": "Submit"}}'
                    ),
                    "actual_url": page.url,
                    "dom_failure_diagnosis": "VALIDATION_BLOCKED: empty role in get_by_role",
                }
            if not name and role != "dialog":  # dialog roles are valid without name
                return {
                    "success": False,
                    "error_message": (
                        f"ActionValidationError: get_by_role('{role}') without 'name' will "
                        f"resolve to ALL '{role}' elements and crash. Provide the element's "
                        f'visible text in \'name\'. Example: {{"strategy": "get_by_role", '
                        f'"role": "{role}", "name": "<visible text>"}}'
                    ),
                    "actual_url": page.url,
                    "dom_failure_diagnosis": f"VALIDATION_BLOCKED: nameless get_by_role('{role}')",
                }
        elif strategy in ("get_by_text", "get_by_label", "get_by_placeholder"):
            if not name:
                return {
                    "success": False,
                    "error_message": (
                        f"ActionValidationError: {strategy} requires a non-empty 'name'. "
                        f"You provided an empty name. Provide the element's visible text."
                    ),
                    "actual_url": page.url,
                    "dom_failure_diagnosis": f"VALIDATION_BLOCKED: empty name in {strategy}",
                }
        elif strategy == "css_selector":
            selector = name or action.get("selector", "")
            if not selector:
                return {
                    "success": False,
                    "error_message": (
                        "ActionValidationError: css_selector requires a selector in 'name'. "
                        "Provide a valid CSS selector."
                    ),
                    "actual_url": page.url,
                    "dom_failure_diagnosis": "VALIDATION_BLOCKED: empty css_selector",
                }

    try:
        # ── NATIVE_ACTION (TASK-091: PrimeNG Macros) ──────────────────
        if action_type == "native_action":
            macro = action.get("macro")
            selector = action.get("selector") or action.get("name")
            if not macro or not selector:
                return {
                    "success": False,
                    "error_message": "native_action requires 'macro' and 'selector'.",
                    "actual_url": page.url,
                }
            
            manager = get_manager(run_id)
            args = action.get("args", [])
            if not isinstance(args, list):
                args = [args]
                
            # Mapping macro aliases to bridge methods
            macro_map = {
                "p-select": "pSelect",
                "p-calendar": "pCalendar",
                "p-table-sort": "pTableSort",
            }
            bridge_meth = macro_map.get(macro, macro)

            try:
                res = await manager.query_angular(selector, bridge_meth, *args)
                if res is None:
                    return {
                        "success": False,
                        "error_message": f"Native macro '{macro}' failed: No result from bridge. Check if Angular is hydrated and selector '{selector}' is correct.",
                        "actual_url": page.url,
                        "dom_failure_diagnosis": "ANGULAR_BRIDGE_MISSING: The bridge returned None. Is 'ng' global available?",
                    }
                if isinstance(res, dict) and res.get("error"):
                    return {
                        "success": False,
                        "error_message": f"Native macro '{macro}' error: {res.get('error')}",
                        "actual_url": page.url,
                        "dom_failure_diagnosis": f"MACRO_ERROR: {res.get('error')}",
                    }
                
                return {
                    "success": True,
                    "error_message": None,
                    "actual_url": page.url,
                    "macro_result": res,
                    "last_executor_fallback": f"NATIVE_MACRO: Executed {macro} on {selector}",
                }
            except Exception as e:
                return {
                    "success": False,
                    "error_message": f"Native macro '{macro}' crashed: {str(e)}",
                    "actual_url": page.url,
                }

        # ── CLICK ─────────────────────────────────────────────────────
        executor_fallback_used = ""  # Tracks which fallback strategy succeeded
        if action_type == "click":
            # Guard: nameless get_by_role('button') resolves to every button and times out.
            # Promote to a get_by_text fallback immediately using the planned name.
            strategy: str = action.get("strategy", "get_by_role")
            name: str = action.get("name", "")
            role: str = action.get("role", "")
            if strategy == "get_by_role" and role == "button" and not name:
                raise ValueError(
                    "FORBIDDEN: get_by_role('button') without a name will time out. "
                    "Provide the button's visible text in 'name'."
                )

            locator = await _resolve_locator_a11y_first(page, action, run_id=run_id, state=state)
            force = bool(action.get("force", False))

            # ── T1-a: Component-Aware Precondition Check ──────────────────
            # Before attempting the click, verify the target text is not
            # inside a closed PrimeNG / Angular container (e.g. a closed
            # p-select overlay whose 40+ pre-rendered options match the text).
            # If it is, surface TARGET_INSIDE_CLOSED_CONTAINER immediately so
            # the planner can emit the open-trigger action first — instead of
            # cascading into a strict-mode stack trace, CV fallback, and HITL.
            if name:
                try:
                    _inside_closed, _trigger_sel = await _is_target_in_open_container(page, name)
                    if _inside_closed:
                        logger.warning(
                            "[executor] TARGET_INSIDE_CLOSED_CONTAINER: '%s' found inside closed "
                            "container — trigger selector: %s",
                            name,
                            _trigger_sel,
                        )
                        return {
                            "success": False,
                            "error_message": (
                                f"TARGET_INSIDE_CLOSED_CONTAINER: open {_trigger_sel} first, "
                                f"then click '{name}'. The target text is inside a closed "
                                f"PrimeNG/Angular overlay that has not been opened yet."
                            ),
                            "actual_url": page.url,
                            "dom_failure_diagnosis": (
                                f"TARGET_INSIDE_CLOSED_CONTAINER: '{name}' found inside a closed "
                                f"container. Open trigger '{_trigger_sel}' to expose the options."
                            ),
                        }
                except Exception:
                    pass  # Non-fatal — proceed with click if gate check fails
            # ── End T1-a ──────────────────────────────────────────────────

            # Scroll the target element into view before clicking.
            # PrimeNG sidepanel buttons and dialog footers are often
            # below the visible fold inside a scrollable container.
            try:
                await locator.scroll_into_view_if_needed(timeout=3000)
            except Exception:
                pass  # Non-fatal — proceed with click regardless

            try:
                await locator.click(timeout=15000, force=force)
            except Exception as click_err:
                err_str = str(click_err)

                # ── Strict mode violation: smart visible-filter disambiguation ──
                # Web apps routinely duplicate nav elements (desktop + mobile
                # menus, header + footer links). Strategy:
                #   Stage 1 — filter to visible elements only
                #   Stage 2 — if exactly 1 visible: click it (unambiguous)
                #   Stage 3 — if multiple visible + non-critical role (link /
                #              menuitem / tab): warn + .first on visible set
                #   Stage 4 — critical role (button / textbox): surface
                #              STRICT_MODE_VIOLATION to Planner for ARIA chaining
                if "strict mode violation" in err_str and name:
                    # Stage 1: filter the locator to visible elements only
                    try:
                        base_locator = await _resolve_locator(page, action)
                        visible_locator = base_locator.filter(has=page.locator(":visible"))
                        visible_count = await visible_locator.count()
                    except Exception:
                        visible_count = 0
                        visible_locator = None

                    # Stage 2: exactly 1 visible element → unambiguous, click it
                    if visible_count == 1 and visible_locator is not None:
                        logger.info(
                            "[executor] Strict mode on '%s' — filtered to 1 visible element, clicking",
                            name,
                        )
                        await visible_locator.first.click(timeout=10000)
                        return {
                            "success": True,
                            "error_message": None,
                            "actual_url": page.url,
                            "last_executor_fallback": f"visible-filter resolved strict mode for '{name}'",
                        }

                    # Stage 2.5: 0 visible but N total — elements exist but are scrolled
                    # off-screen. Try scroll_into_view_if_needed() on the .first match
                    # so the viewport reveals the element, then click it.
                    # This handles inline-table action links (e.g. "Add Voice") whose
                    # column is off-screen to the right on narrow viewports.
                    #
                    # T1-b SHORT-CIRCUIT: When total_count > 5, the elements are almost
                    # certainly pre-rendered Angular/PrimeNG options inside a CLOSED
                    # container (e.g. 41 <p-select> options for "Contest"). Scroll is
                    # futile — the overlay is not in the viewport because it has not been
                    # opened yet. Surface STRICT_MODE_AMBIGUOUS immediately with a
                    # strategy hint so the planner can emit the correct open-trigger
                    # action. This reclaims ~10 s per failure (3 s × 3 scroll attempts +
                    # fallback timeout) vs the old path.
                    elif visible_count == 0:
                        try:
                            base_loc = await _resolve_locator(page, action)
                            total_count_check = await base_loc.count()
                            if total_count_check > 5:
                                # T1-b: short-circuit — high element count indicates a
                                # closed/pre-rendered Angular container, not an off-screen
                                # scroll target. Skip scroll_into_view_if_needed entirely.
                                logger.warning(
                                    "[executor] STRICT_MODE_AMBIGUOUS: '%s' matched %d total / 0 visible "
                                    "— high count indicates closed pre-rendered container; "
                                    "skipping futile scroll, surfacing to Planner",
                                    name,
                                    total_count_check,
                                )
                                return {
                                    "success": False,
                                    "error_message": (
                                        f"STRICT_MODE_AMBIGUOUS: locator '{name}' matched "
                                        f"{total_count_check} elements (0 visible). "
                                        f"High match count indicates a closed pre-rendered container "
                                        f"(e.g. p-select / p-dropdown). Open the container trigger "
                                        f"first, then click the option. "
                                        f"Strategy: use container_selector to scope the action, "
                                        f"or use get_by_role='option' within the open overlay."
                                    ),
                                    "actual_url": page.url,
                                    "dom_failure_diagnosis": (
                                        f"STRICT_MODE_AMBIGUOUS: '{name}' matched {total_count_check} "
                                        f"total / 0 visible — closed pre-rendered container."
                                    ),
                                }
                            elif total_count_check > 0:
                                logger.info(
                                    "[executor] Strict mode on '%s': %d total / 0 visible — "
                                    "trying scroll_into_view_if_needed on .first",
                                    name,
                                    total_count_check,
                                )
                                first_el = base_loc.first
                                await first_el.scroll_into_view_if_needed(timeout=3000)
                                await page.wait_for_timeout(300)  # let layout settle
                                await first_el.click(timeout=8000)
                                return {
                                    "success": True,
                                    "error_message": None,
                                    "actual_url": page.url,
                                    "last_executor_fallback": f"scroll_into_view_if_needed resolved off-screen strict mode for '{name}'",
                                }
                            else:
                                raise RuntimeError(f"locator '{name}' returned 0 elements")
                        except Exception as scroll_err:
                            try:
                                total_count = await (await _resolve_locator(page, action)).count()
                            except Exception:
                                total_count = "?"
                            logger.warning(
                                "[executor] STRICT_MODE_VIOLATION: '%s' matched %s total / 0 visible "
                                "— scroll fallback also failed: %s",
                                name,
                                total_count,
                                str(scroll_err)[:100],
                            )
                            return {
                                "success": False,
                                "error_message": (
                                    f"STRICT_MODE_VIOLATION: locator '{name}' matched {total_count} elements "
                                    f"(0 visible — all off-screen). scroll_into_view_if_needed also failed: "
                                    f"{str(scroll_err)[:120]}. "
                                    f"Use evaluate() to scroll the container, or use vqa_id from the "
                                    f"INTERACTIVE ELEMENTS list for exact targeting."
                                ),
                                "actual_url": page.url,
                                "dom_failure_diagnosis": (
                                    f"STRICT_MODE_VIOLATION_OFF_SCREEN: '{name}' matched {total_count} "
                                    f"total / 0 visible. Scroll failed."
                                ),
                            }

                    # Stage 2.7: multiple visible matches — try exact=True before giving up.
                    # This resolves cases like get_by_text("Days") matching "/ Days" and "Days"
                    # because Playwright's default is substring matching. Exact matching
                    # eliminates the substring collision without requiring a selector change.
                    elif strategy == "get_by_text" and visible_count >= 2:
                        try:
                            exact_action = dict(action, exact=True)
                            exact_locator = await _resolve_locator(page, exact_action)
                            exact_visible = exact_locator.filter(has=page.locator(":visible"))
                            exact_visible_count = await exact_visible.count()
                            if exact_visible_count == 1:
                                logger.info(
                                    "[executor] Strict mode on '%s': exact=True reduced to 1 visible — clicking",
                                    name,
                                )
                                await exact_visible.first.click(timeout=10000)
                                return {
                                    "success": True,
                                    "error_message": None,
                                    "actual_url": page.url,
                                    "last_executor_fallback": f"exact=True resolved strict mode for '{name}'",
                                }
                            else:
                                raise RuntimeError(f"exact=True still matched {exact_visible_count} visible elements")
                        except Exception as exact_err:
                            try:
                                total_count = await (await _resolve_locator(page, action)).count()
                            except Exception:
                                total_count = "?"
                            logger.warning(
                                "[executor] STRICT_MODE_VIOLATION: '%s' matched %s total / %s visible — "
                                "exact=True fallback failed (%s) — surfacing to Planner",
                                name,
                                total_count,
                                visible_count,
                                str(exact_err)[:80],
                            )
                            return {
                                "success": False,
                                "error_message": (
                                    f"STRICT_MODE_VIOLATION: locator '{name}' matched {total_count} elements "
                                    f"({visible_count} visible). exact=True also failed. "
                                    f"Use container_selector to scope, or vqa_id for exact targeting. "
                                    f'Example: add "container_selector": ".sort-panel" or ".po-sorting-dropdown-panel".'
                                ),
                                "actual_url": page.url,
                                "dom_failure_diagnosis": (
                                    f"STRICT_MODE_VIOLATION: '{name}' matched {total_count} total / "
                                    f"{visible_count} visible. exact fallback failed."
                                ),
                            }

                    # Stage 3+4: multiple visible, non-text strategy — surface to Planner.
                    else:
                        try:
                            total_count = await (await _resolve_locator(page, action)).count()
                        except Exception:
                            total_count = "?"
                        logger.warning(
                            "[executor] STRICT_MODE_VIOLATION: '%s' matched %s total / %s visible — "
                            "surfacing to Planner for ARIA-chain disambiguation",
                            name,
                            total_count,
                            visible_count,
                        )
                        return {
                            "success": False,
                            "error_message": (
                                f"STRICT_MODE_VIOLATION: locator '{name}' matched {total_count} elements "
                                f"({visible_count} visible). "
                                f"Use container_selector to scope the locator to a specific ancestor, "
                                f"OR use vqa_id from the INTERACTIVE ELEMENTS list for exact targeting. "
                                f'Example fix: add "container_selector": ".sort-panel" to scope this click '
                                f"to the sort popover only."
                            ),
                            "actual_url": page.url,
                            "dom_failure_diagnosis": (
                                f"STRICT_MODE_VIOLATION: '{name}' matched {total_count} total / "
                                f"{visible_count} visible. Use container_selector or vqa_id."
                            ),
                        }

                if force:
                    raise  # Already used force — nothing more to try

                # ── Tier 2: force=True (bypass Angular overlay) ───────
                try:
                    logger.warning(
                        "click failed (%s) — attempting proactive dismissal + force=True",
                        err_str[:60],
                    )
                    # TASK-013: Attempt to clear blocking overlays before force-click
                    if "intercepted" in err_str.lower():
                        await _dismiss_overlays(page, run_id)

                    await locator.click(timeout=8000, force=True)
                    executor_fallback_used = f"force=True on {strategy}('{name}')"
                except Exception as force_err:
                    # ── Tier 3: get_by_text fallback — NO .first auto-mutator ──
                    # The .first fallback has been REMOVED.  If get_by_text hits
                    # a strict mode violation here it raises and the error flows
                    # to the Failure Diary, forcing the Planner to use
                    # container_selector or vqa_id for precise disambiguation.
                    if name and strategy == "get_by_role":
                        logger.warning(
                            "force click also failed (%s) — trying "
                            "get_by_text('%s') as text-match fallback (strict mode will raise)",
                            str(force_err)[:60],
                            name,
                        )
                        await page.get_by_text(name, exact=False).click(timeout=8000)
                        executor_fallback_used = f"get_by_text('{name}') after role/force failed"
                    else:
                        raise

        # ── FILL — apply fixture suffix, then clear and type the value ───
        elif action_type == "fill":
            locator = await _resolve_locator_a11y_first(page, action, run_id=run_id, state=state)
            try:
                await locator.scroll_into_view_if_needed(timeout=2000)
            except Exception:
                pass

            # ── Objective 3: Hard fixture-suffix enforcement ───────────────
            # Stamp the value BEFORE passing to Playwright so each run
            # writes unique data — prevents repeated-run state collisions.
            # Skips emails, passwords, search bars, dates, short codes, and
            # picker/filter step types (GHOST_LOGIN, PERSONA_SWITCH,
            # ACCOUNT_SWITCH) whose fills target existing-record lookups.
            run_id_for_fixture = action.get("_run_id", "")
            if run_id_for_fixture and value:
                fm = FixtureManager(run_id_for_fixture)
                field_name_for_stamp = action.get("name", "") or action.get("role", "") or action.get("label", "")
                step_type_for_stamp = action.get("_step_type", "") or ""
                stamped_value = fm.stamp(
                    str(value),
                    field_name=field_name_for_stamp,
                    step_type=step_type_for_stamp,
                )
                if stamped_value != str(value):
                    logger.info(
                        "[executor] FixtureManager: stamped fill '%s' → '%s' (field: '%s')",
                        str(value)[:40],
                        stamped_value[:50],
                        field_name_for_stamp[:30],
                    )
                value = stamped_value
            # ───────────────────────────────────────────────

            # ── PrimeNG overlay/dialog pre-wait ─────────────────────────────
            # Before fill(), wait for any open dialog/sidebar/overlay to finish
            # its CSS open-animation so the target input becomes interactable.
            # Probes a priority-ordered list of PrimeNG overlay selectors, stops
            # on the first match present in the DOM, waits up to 3s for visible,
            # then adds a 300ms CSS-transition settle. Works for any ticket type.
            #   p-dialog         — Save Folder, rename, Add Client, edit modals
            #   p-sidebar        — slide-out settings/detail panels
            #   p-dynamic-dialog — programmatic PrimeNG dialogs
            #   p-overlaypanel   — pop-over forms (date pickers, mini-editors)
            #   .p-dialog-mask   — generic PrimeNG modal backdrop
            #   p-overlay-content — lightweight inline overlay boxes
            _OVERLAY_PROBES = [
                "p-dialog",
                "p-sidebar",
                "p-dynamic-dialog",
                "p-overlaypanel",
                ".p-dialog-mask",
                "p-overlay-content",
            ]
            try:
                _overlay_settled = False
                for _probe_sel in _OVERLAY_PROBES:
                    _probe_cnt = await page.locator(_probe_sel).count()
                    if _probe_cnt > 0:
                        try:
                            await page.locator(_probe_sel).first.wait_for(state="visible", timeout=3000)
                        except Exception:
                            pass  # detected but not yet visible in 3s — proceed anyway
                        await page.wait_for_timeout(300)  # CSS transition settle
                        _overlay_settled = True
                        break
                # Fallback: check generic ARIA dialog role if no PrimeNG overlay found
                if not _overlay_settled:
                    _aria_dlg = await page.locator("[role='dialog']:visible,[role='alertdialog']:visible").count()
                    if _aria_dlg > 0:
                        await page.wait_for_timeout(300)
            except Exception:
                pass  # All overlay checks are best-effort — never block the fill

            try:
                await locator.fill(value, timeout=15000)
            except Exception as _fill_err:
                _fill_msg = str(_fill_err)
                # ── Smart fallback for PrimeNG form wrappers ──────────────────
                # Angular/PrimeNG wraps <input> elements inside custom components
                # like <p-inputtext>, <p-inputnumber>, <mat-form-field>, etc.
                # When the LLM targets get_by_label("Part") or
                # get_by_role("textbox", name="Part"), Playwright may resolve to
                # the <label>, <span>, or wrapper <div> instead of the actual
                # <input> inside it.
                #
                # Fallback strategy:
                #   1. Detect the "Element is not an <input>" error
                #   2. Look for a child <input> or <textarea> inside the locator
                #   3. If found, re-fill on the child element
                #   4. If not found, surface the actual element tag to the LLM
                if "Element is not an" in _fill_msg or "not an <input>" in _fill_msg:
                    logger.info("[executor] fill() hit non-input element — attempting child <input> fallback")
                    _child_input = locator.locator("input, textarea").first
                    try:
                        _child_count = await _child_input.count()
                    except Exception:
                        _child_count = 0

                    if _child_count > 0:
                        logger.info("[executor] Found child <input> inside wrapper — retargeting fill")
                        await _child_input.fill(value, timeout=15000)
                    else:
                        # No child input found — try sibling/adjacent input
                        # (PrimeNG sometimes puts the input as a sibling, not child)
                        _sibling_input = locator.locator(".. >> input, .. >> textarea").first
                        try:
                            _sib_count = await _sibling_input.count()
                        except Exception:
                            _sib_count = 0

                        if _sib_count > 0:
                            logger.info("[executor] Found sibling <input> near wrapper — retargeting fill")
                            await _sibling_input.fill(value, timeout=15000)
                        else:
                            # Get the actual element tag for better error feedback
                            _actual_tag = "unknown"
                            try:
                                _actual_tag = await locator.evaluate("el => el.tagName.toLowerCase()")
                            except Exception:
                                pass
                            raise Exception(
                                f"fill failed: Matched element is <{_actual_tag}> (not fillable). "
                                f"No child <input>/<textarea> found inside it. "
                                f"Try using 'css_selector' strategy with "
                                f"'input[formControlName=...]' or target the input directly "
                                f"by its placeholder text."
                            )
                else:
                    # Re-raise non-input errors (timeouts, etc.) for normal handling
                    raise

            # Post-fill validation: verify the value was actually written.
            # Angular ControlValueAccessor can silently reject fills on
            # custom form components — detect this early rather than wasting
            # a full verifier LLM call to discover the field is still empty.
            try:
                actual = await locator.input_value()
                if actual and actual.strip() != str(value).strip():
                    return {
                        "success": False,
                        "error_message": (
                            f"fill('{value}') did not take — field still contains '{actual}'. "
                            f"The field may be a custom Angular component. Try clicking it first, "
                            f"or use press_key to trigger change events."
                        ),
                        "actual_url": page.url,
                        "dom_failure_diagnosis": (
                            f"DOM_FILL_REJECTED: fill('{value}') was accepted by Playwright "
                            f"but field value is '{actual}' — Angular CVA likely intercepted it."
                        ),
                    }
            except Exception:
                pass  # input_value() not available on all element types — safe to skip

        # ── SELECT — select an option from a dropdown ─────────────────
        elif action_type == "select_option":
            locator = await _resolve_locator(page, action)
            await locator.select_option(value, timeout=15000)

        # ── CHECK / UNCHECK ───────────────────────────────────────────
        elif action_type == "check":
            locator = await _resolve_locator_a11y_first(page, action, run_id=run_id, state=state)
            try:
                await locator.scroll_into_view_if_needed(timeout=2000)
            except Exception:
                pass
            await locator.check(timeout=15000)

        elif action_type == "uncheck":
            locator = await _resolve_locator_a11y_first(page, action, run_id=run_id, state=state)
            try:
                await locator.scroll_into_view_if_needed(timeout=2000)
            except Exception:
                pass
            await locator.uncheck(timeout=15000)

        # ── NAVIGATE — go to a URL ────────────────────────────────────
        elif action_type == "navigate":
            url = value or action.get("name", "")
            # Safety guard: if the URL is empty, vague, or not a real HTTP URL,
            # substitute target_url to prevent ERR_NAME_NOT_RESOLVED crashes.
            if not url or not url.startswith("http"):
                logger.warning(
                    "Navigate action has invalid/empty URL '%s' — substituting target_url '%s'",
                    url,
                    target_url,
                )
                url = target_url

            # ── Refresh hard-block: count consecutive refresh-type actions ────
            # navigate + F5 are often used interchangeably as refresh strategies.
            # After 2 consecutive in either form, block further refreshes.
            _nav_history = state.get("detailed_execution_log", [])
            _consecutive_nav_refreshes = 0
            for _nr in reversed(_nav_history):
                _nrat = _nr.get("action_type", "")
                _nrpv = (_nr.get("action_payload", {}) or {}).get("value", "") or ""
                if _nrat == "press_key" and _nrpv in ("F5", "Meta+r", "Control+r") or _nrat == "navigate":
                    _consecutive_nav_refreshes += 1
                else:
                    break
            if _consecutive_nav_refreshes >= 2:
                logger.warning(
                    "[%s] REFRESH HARD-BLOCKED (navigate): %d consecutive refresh actions",
                    run_id,
                    _consecutive_nav_refreshes,
                )
                return {
                    "success": False,
                    "error_message": (
                        f"REFRESH_HARD_BLOCKED (Python constraint): You have used navigate/"
                        f"refresh {_consecutive_nav_refreshes} consecutive times without "
                        f"progress. Navigating again will NOT change the result. "
                        f"Use action='done' if the step is satisfied, or use action='verify' "
                        f"to check the specific element directly."
                    ),
                    "actual_url": page.url,
                }

            await page.goto(url, wait_until="networkidle", timeout=30000)

            # ── FEAT-060-P2C: SPA Hydration Fast-Path ─────────────────
            # After navigation, wait for Angular/PrimeNG to reach a stable
            # state via event-driven detection instead of a fixed delay.
            # Falls back to 2s fixed wait if Angular stability doesn't fire.
            from backend.browser.spa_hydration import get_spa_hydration
            _spa = get_spa_hydration()
            _hydration_result = await _spa.wait_for_stable(page)
            logger.debug(
                "navigate: SPA hydration via '%s' in %dms",
                _hydration_result.strategy_used,
                _hydration_result.elapsed_ms,
            )

        # ── WAIT — wait for a timeout or DOM stability ──────────────────
        elif action_type == "wait":
            if str(value) in ("networkidle", "domstable"):
                # vSuite has permanent background polling — networkidle never fires.
                # Redirect to _wait_for_stable_dom (Angular microtask fence + DOM poll).
                logger.info(
                    "wait('%s') → using _wait_for_stable_dom instead (vSuite compatibility)",
                    value,
                )
                await _wait_for_stable_dom(page)
            else:
                # Interpret value as milliseconds — LLM may send int or str
                try:
                    ms = int(value) if value else 2000
                except (ValueError, TypeError):
                    ms = 2000
                await page.wait_for_timeout(ms)

        # ── WAIT_FOR_RESPONSE — wait for an HTTP request to complete ───
        # Use this for steps that involve saving/submitting data where the
        # verifier cannot confirm success via screenshot (e.g. API calls).
        elif action_type == "wait_for_response":
            url_pattern = str(value or name or "")
            if url_pattern:
                try:
                    resp = await page.wait_for_response(
                        lambda r, _pat=url_pattern: _pat in r.url and r.status < 400,
                        timeout=10000,
                    )
                    return {
                        "success": True,
                        "error_message": None,
                        "actual_url": page.url,
                        "last_executor_fallback": f"wait_for_response({url_pattern}) → {resp.status}",
                    }
                except Exception as e:
                    return {
                        "success": False,
                        "error_message": f"wait_for_response('{url_pattern}'): {str(e)[:150]}",
                        "actual_url": page.url,
                        "dom_failure_diagnosis": (
                            f"NETWORK_TIMEOUT: No matching response for '{url_pattern}' "
                            f"within 10s. Check if the URL pattern is correct."
                        ),
                    }
            else:
                await page.wait_for_timeout(2000)

        # ── VERIFY — check live DOM, then fall back to transient cache ─
        elif action_type == "verify":
            locator = await _resolve_locator(page, action)
            element_name: str = action.get("name", "")
            is_visible = await locator.is_visible()

            if not is_visible:
                import re as _re

                def _norm(s: str) -> str:
                    s = s.lower()
                    s = _re.sub(r"[^\w\s]", " ", s)
                    return " ".join(s.split())

                # ── Tier 2: Element exists in DOM but is off-screen ──────
                # is_visible() returns False when element is scrolled off.
                # count() > 0 checks DOM presence regardless of scroll position.
                try:
                    dom_count = await locator.count()
                except Exception:
                    dom_count = 0

                if dom_count > 0:
                    logger.info(
                        "verify '%s' — off-screen but in DOM (count=%d) → PASS",
                        element_name,
                        dom_count,
                    )
                    # Fall through to success path below
                else:
                    # ── Tier 3: Full page text search ────────────────────
                    # Bug G fix: use _extract_page_text() instead of the
                    # bare `document.body.innerText` call. PrimeNG p-datatable
                    # tables render in Angular component boundaries that
                    # body.innerText misses — the fallback queries tbody tr td,
                    # [role='row'], and .p-datatable-tbody in addition to the body.
                    page_text = await _extract_page_text(page)

                    norm_name = _norm(element_name)
                    norm_page = _norm(page_text)
                    name_words = set(norm_name.split())
                    page_words = set(norm_page.split())
                    found_in_page = bool(name_words and name_words.issubset(page_words))

                    if found_in_page:
                        logger.info(
                            "verify '%s' — found in full page text → PASS",
                            element_name,
                        )
                        # Fall through to success path below
                    else:
                        # ── Tier 4: Transient text cache (toasters/alerts) ─
                        transient_norm = _norm(action.get("_transient") or "")
                        name_norm = _norm(element_name)
                        name_words2 = set(name_norm.split())
                        transient_words = set(transient_norm.split())
                        words_found = name_words2 and name_words2.issubset(transient_words)

                        if words_found:
                            logger.info(
                                "verify '%s' — found in transient cache → PASS",
                                element_name,
                            )
                            # Fall through to success path below
                        else:
                            return {
                                "success": False,
                                "error_message": (
                                    f"Verification failed: '{element_name}' not visible, "
                                    f"not in DOM, not in page text, not in transient cache."
                                ),
                                "actual_url": page.url,
                            }

        # ── SCROLL ────────────────────────────────────────────────────
        # HARD-STOP guardrail: if 3+ consecutive scrolls detected in
        # the execution history, BLOCK this scroll and return a failure
        # that forces the evaluator to route back to the planner.
        # This is a PYTHON CONSTRAINT — the LLM cannot override it.
        # ── EVALUATE — run arbitrary JS expression in page context ───────
        # Used by the healing tiers to scroll off-screen elements into view,
        # e.g. {"action": "evaluate", "expression": "window.scrollBy(500, 0)"}
        elif action_type == "evaluate":
            expression = action.get("expression") or value or ""
            if not expression:
                return {
                    "success": False,
                    "error_message": "evaluate: missing 'expression' field",
                    "actual_url": page.url,
                }
            try:
                result = await page.evaluate(f"() => {{ {expression} }}")
                logger.info("[%s] evaluate: executed expression, result=%s", run_id, str(result)[:80])
                await page.wait_for_timeout(300)
            except Exception as eval_err:
                return {
                    "success": False,
                    "error_message": f"evaluate: JS error: {str(eval_err)[:200]}",
                    "actual_url": page.url,
                }

        elif action_type == "scroll":
            # Count consecutive scrolls from the execution log
            action_history = state.get("detailed_execution_log", [])
            consecutive_scrolls = 0
            for step in reversed(action_history):
                if step.get("action_type") == "scroll":
                    consecutive_scrolls += 1
                else:
                    break

            if consecutive_scrolls >= 3:
                logger.warning(
                    "[%s] SCROLL HARD-BLOCKED: %d consecutive scrolls. "
                    "Forcing strategy change — table_search or pagination.",
                    run_id,
                    consecutive_scrolls,
                )
                return {
                    "success": False,
                    "error_message": (
                        f"SCROLL HARD-BLOCKED (Python constraint): You have "
                        f"scrolled {consecutive_scrolls} consecutive times "
                        f"without finding the target. Scrolling will NOT "
                        f"reveal more data in a paginated PrimeNG table. "
                        f"You MUST change strategy immediately:\n"
                        f"  1. Use action='table_search' with the text you "
                        f"     are looking for to filter the table.\n"
                        f"  2. OR click pagination buttons ('Next Page', '>') "
                        f"     to navigate to the next page of results.\n"
                        f"  3. NEVER scroll again until you have tried "
                        f"     table_search or pagination first."
                    ),
                    "actual_url": page.url,
                    "consecutive_scrolls": 0,  # Reset for future use
                }

            # Execute the scroll (under threshold)
            direction = -300 if value == "up" else 300
            await page.mouse.wheel(0, direction)
            await page.wait_for_timeout(200)

        # ── PRESS KEY ─────────────────────────────────────────────────
        elif action_type == "press_key":
            key = value or "Enter"

            # ── Refresh hard-block: cap consecutive F5/reload presses ────────
            # Mirrors the scroll guardrail. F5 presses succeed (no Playwright
            # error) so the circuit breaker never fires for them. After 2
            # consecutive refreshes on the same AC step without any other action
            # in between, the agent is stuck and refreshing will not help.
            if key in ("F5", "F5", "Meta+r", "Control+r"):
                _refresh_history = state.get("detailed_execution_log", [])
                _consecutive_refreshes = 0
                for _rs in reversed(_refresh_history):
                    _rat = _rs.get("action_type", "")
                    _rpv = (_rs.get("action_payload", {}) or {}).get("value", "") or ""
                    if _rat == "press_key" and _rpv in ("F5", "Meta+r", "Control+r") or _rat == "navigate":
                        _consecutive_refreshes += 1
                    else:
                        break
                if _consecutive_refreshes >= 2:
                    logger.warning(
                        "[%s] REFRESH HARD-BLOCKED: %d consecutive refresh actions — forcing strategy change",
                        run_id,
                        _consecutive_refreshes,
                    )
                    return {
                        "success": False,
                        "error_message": (
                            f"REFRESH_HARD_BLOCKED (Python constraint): You have refreshed "
                            f"the page {_consecutive_refreshes} consecutive times without "
                            f"making progress. Refreshing will NOT change the result. "
                            f"You MUST take a DIFFERENT action:\n"
                            f"  1. Use action='done' if the AC step is already satisfied "
                            f"     based on what you last saw.\n"
                            f"  2. Use action='verify' with the specific element selector "
                            f"     to check the current page state.\n"
                            f"  3. Navigate to the target page URL directly and verify "
                            f"     the element once — do NOT refresh again."
                        ),
                        "actual_url": page.url,
                    }

            await page.keyboard.press(key)

        # ── SET INPUT FILES — bypass native file dialog ────────────────
        # Uses Playwright's setInputFiles to directly set file paths on
        # hidden <input type="file"> elements. NEVER clicks Browse buttons.
        elif action_type == "set_input_files":
            selector = action.get("selector", "") or action.get("name", "")
            file_value = str(action.get("value", "")).strip()

            if not file_value:
                return {
                    "success": False,
                    "error_message": (
                        f"set_input_files requires 'value' (filename). Available files: {list(ASSET_INVENTORY.keys())}"
                    ),
                    "actual_url": page.url,
                }

            # Resolve the file path from the asset inventory
            file_path = ASSET_INVENTORY.get(file_value)
            if not file_path:
                # Try case-insensitive match
                for inv_name, inv_path in ASSET_INVENTORY.items():
                    if inv_name.lower() == file_value.lower():
                        file_path = inv_path
                        break

            if not file_path:
                # Check if it's an absolute path that exists
                candidate = Path(file_value)
                if candidate.exists():
                    file_path = str(candidate.resolve())
                else:
                    return {
                        "success": False,
                        "error_message": (
                            f"File not found: '{file_value}'. Available test files: {_format_asset_list()}"
                        ),
                        "actual_url": page.url,
                    }

            # Default to generic input[type="file"] if no selector provided
            target_selector = selector or 'input[type="file"]'
            locator = page.locator(target_selector)

            try:
                await locator.set_input_files(file_path, timeout=10000)
                logger.info(
                    "set_input_files: uploaded '%s' via selector '%s'",
                    file_value,
                    target_selector,
                )
            except Exception as e:
                return {
                    "success": False,
                    "error_message": (
                        f"set_input_files failed: {str(e)[:150]}. "
                        f"Selector used: '{target_selector}'. "
                        f"Try 'p-fileupload input[type=\"file\"]' or "
                        f"'input[type=\"file\"]' instead."
                    ),
                    "actual_url": page.url,
                }

        # ── VERIFY_TABLE_SORT — programmatic column sort assertion ─────
        # The LLM cannot reliably parse dates or numbers from DOM text.
        # This handler does it in Python so the LLM never has to.
        elif action_type == "verify_table_sort":
            column_name: str = (action.get("column") or action.get("column_name") or action.get("name") or "").strip()
            sort_order: str = (action.get("order") or action.get("sort_order") or "ascending").lower().strip()

            if not column_name:
                return {
                    "success": False,
                    "error_message": (
                        "verify_table_sort requires 'column' (e.g., 'Due / Days'). "
                        'Example: {"action": "verify_table_sort", '
                        '"column": "Due / Days", "order": "ascending"}'
                    ),
                    "actual_url": page.url,
                    "dom_failure_diagnosis": "VALIDATION_BLOCKED: missing column name for verify_table_sort",
                }

            if sort_order not in ("ascending", "descending", "asc", "desc"):
                sort_order = "ascending"
            ascending = sort_order in ("ascending", "asc")

            # Extract all visible cell values for the named column via JS
            cell_texts: list[str] = await page.evaluate(
                """
                ([colName]) => {
                    // Find the column index by matching the header text
                    const headers = Array.from(
                        document.querySelectorAll(
                            '.p-datatable-thead th, thead th'
                        )
                    );
                    let colIndex = -1;
                    for (let i = 0; i < headers.length; i++) {
                        const text = (headers[i].innerText || '').trim();
                        if (text.toLowerCase().includes(colName.toLowerCase())) {
                            colIndex = i;
                            break;
                        }
                    }
                    if (colIndex === -1) return [];

                    // Extract cell text at that column index from each body row
                    const rows = document.querySelectorAll(
                        '.p-datatable-tbody tr, tbody tr'
                    );
                    const values = [];
                    for (const row of rows) {
                        const cells = row.querySelectorAll('td');
                        if (cells[colIndex]) {
                            const txt = (cells[colIndex].innerText || '').trim();
                            if (txt) values.push(txt);
                        }
                    }
                    return values;
                }
                """,
                [column_name],
            )

            if not cell_texts:
                return {
                    "success": False,
                    "error_message": (
                        f"verify_table_sort: column '{column_name}' not found in the "
                        f"current p-table, or the table has no visible rows. "
                        f"Check the exact column header text (case-insensitive match)."
                    ),
                    "actual_url": page.url,
                    "dom_failure_diagnosis": (
                        f"DOM_COLUMN_NOT_FOUND: No column matching '{column_name}' in visible p-table headers."
                    ),
                }

            # ── Type detection + parsing ──────────────────────────────────
            import re as _re
            from datetime import datetime as _dt

            # Date pattern: MM/DD/YYYY, MM-DD-YYYY, YYYY-MM-DD, or "X days"
            _DATE_PATTERNS = [
                (r"^(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})$", "%m/%d/%Y"),  # MM/DD/YYYY
                (r"^(\d{4})[/\-](\d{2})[/\-](\d{2})$", "%Y/%m/%d"),  # ISO
            ]
            _NUMBER_RE = _re.compile(r"^[\$\€\£]?[\d,]+\.?\d*$")
            _DAYS_RE = _re.compile(r"^(-?\d+)\s*(?:days?|d)$", _re.IGNORECASE)

            def _parse_cell(txt: str):
                """Return a comparable value for sorting; type is detected automatically."""
                txt = txt.strip()
                # "N days" or "-N days"
                m = _DAYS_RE.match(txt)
                if m:
                    return ("num", float(m.group(1)))
                # Pure number / currency
                if _NUMBER_RE.match(txt):
                    return ("num", float(txt.replace(",", "").lstrip("$€£")))
                # Date
                for pat, fmt in _DATE_PATTERNS:
                    if _re.match(pat, txt):
                        normalized = txt.replace("-", "/")
                        try:
                            return ("date", _dt.strptime(normalized, "%m/%d/%Y"))
                        except ValueError:
                            try:
                                return ("date", _dt.strptime(normalized, "%Y/%m/%d"))
                            except ValueError:
                                pass
                # Fallback: string
                return ("str", txt.lower())

            parsed = [_parse_cell(t) for t in cell_texts]

            # ── Sort verification ─────────────────────────────────────────
            out_of_order_pair: tuple | None = None
            for i in range(len(parsed) - 1):
                a_type, a_val = parsed[i]
                b_type, b_val = parsed[i + 1]
                if a_type != b_type:
                    # Mixed types — skip this pair, treat as sorted
                    continue
                try:
                    if ascending:
                        if a_val > b_val:
                            out_of_order_pair = (cell_texts[i], cell_texts[i + 1])
                            break
                    else:
                        if a_val < b_val:
                            out_of_order_pair = (cell_texts[i], cell_texts[i + 1])
                            break
                except TypeError:
                    pass  # Incomparable types — skip

            if out_of_order_pair is None:
                logger.info(
                    "verify_table_sort: column '%s' is correctly sorted %s (%d cells checked)",
                    column_name,
                    sort_order,
                    len(parsed),
                )
                return {
                    "success": True,
                    "error_message": None,
                    "actual_url": page.url,
                    "last_executor_fallback": (
                        f"verify_table_sort: '{column_name}' confirmed {sort_order} "
                        f"({len(parsed)} cells, type={parsed[0][0] if parsed else 'unknown'})"
                    ),
                }
            else:
                a_raw, b_raw = out_of_order_pair
                logger.warning(
                    "verify_table_sort FAIL: column '%s' NOT sorted %s — '%s' came before '%s'",
                    column_name,
                    sort_order,
                    a_raw,
                    b_raw,
                )
                return {
                    "success": False,
                    "error_message": (
                        f"verify_table_sort FAILED: Column '{column_name}' is NOT sorted "
                        f"{sort_order}. Found '{a_raw}' before '{b_raw}' — "
                        f"these two adjacent values are out of order. "
                        f"Click the '{column_name}' column header to re-sort, then "
                        f"use verify_table_sort again to confirm."
                    ),
                    "actual_url": page.url,
                    "dom_failure_diagnosis": (
                        f"TABLE_SORT_ORDER_WRONG: '{column_name}' not {sort_order}. "
                        f"Out-of-order pair: '{a_raw}' vs '{b_raw}'."
                    ),
                }

        # ── RECIPE — atomic multi-step component interaction ──────────
        # The planner emits {"action":"recipe","recipe_name":"...",
        # "recipe_params":{...}} when it detects a known compound PrimeNG
        # component pattern.  The recipe runner executes all sub-steps
        # atomically with built-in cleanup-on-failure and a single
        # post-recipe verification.
        elif action_type == "recipe":
            r_name: str = action.get("recipe_name", "")
            r_params: dict = action.get("recipe_params") or {}
            r_run_id: str = action.get("_run_id", "")

            # ── Anti-Amnesia Hard Gate: block view-switching recipes ──────
            # When the LLM panics after a step failure it spams the
            # compact_view_navigate / list_view_navigate recipe even though
            # the UI is already in the target view. These python-level gates
            # detect the current view state via known UI landmarks and
            # return a structured RECIPE_BLOCKED error that forces the LLM
            # to move on instead of looping.

            # Hard Gate: Prevent spamming Compact View recipe
            if r_name == "compact_view_navigate":
                try:
                    _sort_btn_visible = await page.locator("button#sort-btn").is_visible()
                except Exception:
                    _sort_btn_visible = False
                if _sort_btn_visible:
                    logger.info(
                        "[executor] RECIPE_BLOCKED: compact_view_navigate — "
                        "already in Compact View (Sort By button visible)"
                    )
                    return {
                        "success": False,
                        "error_message": (
                            "RECIPE_BLOCKED: You are ALREADY in Compact View "
                            "(Sort By button is visible). DO NOT call this recipe "
                            "again. Proceed immediately with your sorting actions."
                        ),
                        "actual_url": page.url,
                        "dom_failure_diagnosis": "ALREADY_IN_COMPACT_VIEW",
                    }

            # Hard Gate: Prevent spamming List View recipe
            if r_name == "list_view_navigate":
                try:
                    _col_header_visible = await page.locator("th.po-col-clientCol").is_visible()
                except Exception:
                    _col_header_visible = False
                if _col_header_visible:
                    logger.info(
                        "[executor] RECIPE_BLOCKED: list_view_navigate — already in List View (column headers visible)"
                    )
                    return {
                        "success": False,
                        "error_message": (
                            "RECIPE_BLOCKED: You are ALREADY in List View "
                            "(Column headers are visible). DO NOT call this recipe "
                            "again. Proceed immediately with your sorting actions."
                        ),
                        "actual_url": page.url,
                        "dom_failure_diagnosis": "ALREADY_IN_LIST_VIEW",
                    }

            if not r_name:
                return {
                    "success": False,
                    "error_message": (
                        "action='recipe' was emitted without 'recipe_name'. "
                        "Include the exact recipe name from knowledge/blueprints/*.yaml."
                    ),
                    "actual_url": page.url,
                }

            try:
                recipe = recipe_registry.get(r_name)
            except RecipeNotFoundError as e:
                return {
                    "success": False,
                    "error_message": str(e),
                    "actual_url": page.url,
                    "dom_failure_diagnosis": (
                        f"RECIPE_NOT_FOUND: '{r_name}' is not in knowledge/blueprints/. "
                        f"Check the recipe name or write a new YAML blueprint."
                    ),
                }

            try:
                filled = fill_recipe(recipe, r_params)
            except (RecipeParameterError, RecipeConfigurationError) as e:
                return {
                    "success": False,
                    "error_message": str(e),
                    "actual_url": page.url,
                    "dom_failure_diagnosis": f"RECIPE_CONFIG_ERROR: {str(e)[:200]}",
                }

            # Execute atomically — returns its own complete result dict.
            # Bypasses the remainder of _dispatch_action success path
            # (transient capture / spinner wait are not needed for recipes).
            return await execute_recipe(
                page=page,
                recipe=recipe,
                filled_steps=filled,
                params=r_params,
                run_id=r_run_id,
                _resolve_locator_fn=_resolve_locator,
            )

        # ─── PRIMENG_DROPDOWN — atomic trigger → portal → option macro ────────
        # Replaces the broken two-tick pattern (click trigger at tick N,
        # click option at tick N+1) that reliably fails because the planner
        # re-clicks the trigger on the second tick, closing the menu.
        #
        # Three-step atomic sequence:
        #   1. Click the trigger (CSS trigger_selector OR vision trigger_mark_id)
        #   2. Wait for the portal overlay (portal_class) to become visible
        #   3. Click the exact text inside the portal (get_by_text scoped to portal)
        #
        # ⛔ NEVER uses :has-text() — PrimeNG portals use nested <span>s that
        #    break CSS pseudo-class attribute selectors.  get_by_text + scope = safe.
        elif action_type == "primeng_dropdown":
            trigger_sel: str = action.get("trigger_selector", "") or ""
            trigger_mid = action.get("trigger_mark_id")  # Vision-mode mark ID
            target_txt: str = action.get("target_text", "") or ""
            portal_cls: str = action.get("portal_class", "") or ""

            # In vision mode, trigger_mark_id replaces trigger_selector
            has_trigger = bool(trigger_sel) or trigger_mid is not None
            if not has_trigger or not target_txt or not portal_cls:
                return {
                    "success": False,
                    "error_message": (
                        "primeng_dropdown missing required fields. "
                        f"trigger_selector='{trigger_sel}', trigger_mark_id={trigger_mid}, "
                        f"target_text='{target_txt}', portal_class='{portal_cls}'. "
                        "Requires (trigger_selector OR trigger_mark_id) + target_text + portal_class."
                    ),
                    "actual_url": page.url,
                    "dom_failure_diagnosis": "PRIMENG_DROPDOWN_MISSING_FIELDS",
                }

            try:
                # ── Smart Portal Detection ───────────────────────────────────
                # Before clicking the trigger, check if the portal overlay is
                # ALREADY visible.  If it is, the trigger click would CLOSE it
                # (PrimeNG toggles on click), causing a timeout when we later
                # wait for the portal to appear.  Skip straight to Step 3.
                portal_locator = page.locator(portal_cls)
                try:
                    _is_already_open = await portal_locator.first.is_visible()
                except Exception:
                    _is_already_open = False

                if _is_already_open:
                    logger.info(
                        "[primeng_dropdown] Portal '%s' is already open. Skipping trigger click to avoid toggle-close.",
                        portal_cls,
                    )
                    _portal_found = True
                else:
                    # Step 1: Click the trigger
                    # ── Vision-mode: use coordinate click from mark_coordinate_map ──
                    if trigger_mid is not None:
                        _mark_map = state.get("mark_coordinate_map", {})
                        _trigger_coords = _mark_map.get(str(trigger_mid))
                        if _trigger_coords:
                            _tx, _ty = _trigger_coords["x"], _trigger_coords["y"]
                            # Humanize: move → hover pause → click with delay → animation wait
                            await page.mouse.move(_tx, _ty)
                            await page.wait_for_timeout(150)  # Let Angular register hover/focus
                            await page.mouse.click(_tx, _ty, delay=100)
                            await page.wait_for_timeout(250)  # Let portal animation start
                            logger.info(
                                "[primeng_dropdown] Vision trigger click (humanized): mark_id=%d → (%d, %d)",
                                trigger_mid,
                                _tx,
                                _ty,
                            )
                        elif trigger_sel:
                            # Fallback: mark_id not found but trigger_selector provided
                            logger.warning(
                                "[primeng_dropdown] mark_id %d not found in coordinate map — "
                                "falling back to trigger_selector '%s'",
                                trigger_mid,
                                trigger_sel,
                            )
                            await page.locator(trigger_sel).click(timeout=10000)
                        else:
                            return {
                                "success": False,
                                "error_message": (
                                    f"primeng_dropdown: trigger_mark_id {trigger_mid} not found in "
                                    f"coordinate map and no trigger_selector fallback provided."
                                ),
                                "actual_url": page.url,
                                "dom_failure_diagnosis": "PRIMENG_DROPDOWN_MARK_NOT_FOUND",
                            }
                    else:
                        # ── DOM-mode: use CSS trigger_selector ──────────────────────
                        # ── Selector alias auto-heal ───────────────────────────────────
                        # PrimeNG 19 sets `inputId` on the INNER <input>, NOT the host
                        # <p-select> element.  So "p-select#header-sort-drop-down-X"
                        # is INVALID CSS — the id only exists on the inner <input>.
                        import re as _re

                        _INPUTID_PATTERN = _re.compile(r"^p-select#header-sort-drop-down-(.+)$", _re.IGNORECASE)
                        _m = _INPUTID_PATTERN.match(trigger_sel)
                        if _m:
                            col_id = _m.group(1)
                            corrected_sel = f"th.po-col-{col_id} p-select"
                            logger.warning(
                                "[primeng_dropdown] Selector alias correction: "
                                "'%s' → '%s' (inputId targets inner <input>, not host <p-select>)",
                                trigger_sel,
                                corrected_sel,
                            )
                            trigger_sel = corrected_sel

                        trigger_locator = page.locator(trigger_sel)
                        try:
                            await trigger_locator.scroll_into_view_if_needed(timeout=3000)
                        except Exception:
                            pass

                        # ── Chevron-biased click ──────────────────────────────────────
                        # PrimeNG <p-select> places the clickable chevron icon on the
                        # far right.  Clicking the center often hits the label text,
                        # which doesn't open the menu.  Target the icon first; if not
                        # found, bias the click to the right edge of the element.
                        chevron_locator = trigger_locator.locator(
                            ".p-select-dropdown, .p-dropdown-trigger, .pi-chevron-down"
                        ).first
                        try:
                            if await chevron_locator.is_visible(timeout=1000):
                                await chevron_locator.click(delay=100)
                                logger.info("[primeng_dropdown] Clicked chevron icon specifically.")
                            else:
                                # Fallback: click the far-right edge where the arrow usually lives
                                box = await trigger_locator.bounding_box()
                                if box:
                                    click_x = box["width"] - 10
                                    click_y = box["height"] / 2
                                    await trigger_locator.click(
                                        position={"x": click_x, "y": click_y},
                                        delay=100,
                                    )
                                    logger.info("[primeng_dropdown] Clicked right-edge of trigger.")
                                else:
                                    await trigger_locator.click(delay=100)
                                    logger.info("[primeng_dropdown] Clicked trigger (center fallback).")
                        except Exception:
                            # Ultimate fallback: plain click
                            await trigger_locator.click(delay=100)
                            logger.info("[primeng_dropdown] Clicked trigger (exception fallback): '%s'", trigger_sel)

                    # Step 2: Wait for portal overlay to attach and become visible
                    # Try the specific portal_class first, then fall back to generic
                    # PrimeNG overlay selectors (p-select-overlay, p-popover, etc.)
                    portal_locator = page.locator(portal_cls)
                    _portal_found = False
                    try:
                        await portal_locator.wait_for(state="visible", timeout=3000)
                        _portal_found = True
                    except Exception:
                        # ── Fuzzy portal fallback ──────────────────────────────────
                        # PrimeNG uses several overlay classes depending on the
                        # component type (p-select, p-popover, sort-panel, etc.).
                        # If the LLM guessed the wrong portal_class, try generic ones.
                        _GENERIC_PORTAL_SELECTORS = (
                            ".p-connected-overlay-visible, "
                            ".p-popover, "
                            ".p-select-overlay, "
                            ".p-overlay-visible, "
                            ".p-datepicker-panel"
                        )
                        logger.warning(
                            "[primeng_dropdown] Specific portal '%s' not found — "
                            "attempting generic PrimeNG overlay fallback: %s",
                            portal_cls,
                            _GENERIC_PORTAL_SELECTORS,
                        )
                        try:
                            portal_locator = page.locator(_GENERIC_PORTAL_SELECTORS).first
                            await portal_locator.wait_for(state="visible", timeout=2000)
                            _portal_found = True
                            logger.info(
                                "[primeng_dropdown] Generic fallback succeeded — found a visible PrimeNG overlay"
                            )
                        except Exception as fallback_err:
                            logger.warning(
                                "[primeng_dropdown] Generic fallback also failed: %s",
                                str(fallback_err)[:100],
                            )

                    if not _portal_found:
                        return {
                            "success": False,
                            "error_message": (
                                f"primeng_dropdown: portal '{portal_cls}' did not become visible "
                                f"within 3s after clicking trigger, and generic PrimeNG overlay "
                                f"fallback also failed. "
                                f"Check that portal_class matches the actual overlay element class."
                            ),
                            "actual_url": page.url,
                            "dom_failure_diagnosis": (
                                f"PRIMENG_PORTAL_NOT_VISIBLE: '{portal_cls}' never appeared. "
                                f"Generic fallback selectors also found nothing visible."
                            ),
                        }

                # Step 3: Click the exact option inside the portal.
                # Strictly scoped to <li>, [role="option"], or .p-select-option
                # to prevent clicking random <span> text nodes that match the text
                # but aren't actual selectable options.
                option_locator = (
                    portal_locator.locator('li, [role="option"], .p-select-option').filter(has_text=target_txt).first
                )

                try:
                    await option_locator.wait_for(state="visible", timeout=3000)
                    await option_locator.click(delay=100)
                    logger.info(
                        "[primeng_dropdown] Option selected (strict li/role=option): '%s' inside portal '%s'",
                        target_txt,
                        portal_cls,
                    )
                except Exception:
                    # Fallback: if strict scoping found nothing, try broader get_by_text.
                    # Enumerate available options first — if target_txt doesn't appear in any
                    # option, log all available texts immediately so the agent can correct it
                    # instead of wasting retries on a non-existent option label.
                    try:
                        _all_items = portal_locator.locator('li, [role="option"], .p-select-option')
                        _item_count = await _all_items.count()
                        _available_texts = []
                        for _idx in range(min(_item_count, 20)):
                            try:
                                _available_texts.append(await _all_items.nth(_idx).inner_text())
                            except Exception:
                                pass
                        if _available_texts:
                            logger.warning(
                                "[primeng_dropdown] '%s' not found in portal '%s'. Available option texts: %s",
                                target_txt,
                                portal_cls,
                                _available_texts,
                            )
                    except Exception:
                        pass

                    fallback_opt = portal_locator.get_by_text(target_txt, exact=True)
                    fb_count = await fallback_opt.count()
                    if fb_count == 0:
                        fallback_opt = portal_locator.get_by_text(target_txt, exact=False)
                        fb_count2 = await fallback_opt.count()
                        if fb_count2 == 0:
                            # Fuzzy matching fallback
                            if _available_texts:
                                matches = difflib.get_close_matches(target_txt, _available_texts, n=1, cutoff=0.6)
                                if matches:
                                    best_match = matches[0]
                                    fallback_opt = portal_locator.get_by_text(best_match, exact=True)
                                    await fallback_opt.first.click(timeout=5000)
                                    logger.info(
                                        "[primeng_dropdown] Option auto-corrected (fuzzy match): '%s' -> '%s'",
                                        target_txt,
                                        best_match,
                                    )
                                    return {
                                        "success": True,
                                        "error_message": None,
                                        "actual_url": page.url,
                                        "last_executor_fallback": f"Dropdown selection (fuzzy match) success: {best_match}",
                                    }

                            # Option not found — return a descriptive error with available options
                            _avail_str = (
                                ", ".join(f"'{t}'" for t in _available_texts) if _available_texts else "unknown"
                            )
                            raise RuntimeError(
                                f"OPTION_NOT_FOUND: '{target_txt}' not found in portal '{portal_cls}'. "
                                f"Available options: [{_avail_str}]. "
                                f"Check that target_text exactly matches one of the listed options."
                            )
                    await fallback_opt.first.click(timeout=5000)
                    logger.info(
                        "[primeng_dropdown] Option selected (get_by_text fallback): '%s'",
                        target_txt,
                    )

            except Exception as dd_err:
                return {
                    "success": False,
                    "error_message": (
                        f"primeng_dropdown failed: {str(dd_err)[:300]}. "
                        f"trigger='{trigger_sel}', trigger_mark_id={trigger_mid}, "
                        f"portal='{portal_cls}', option='{target_txt}'."
                    ),
                    "actual_url": page.url,
                    "dom_failure_diagnosis": (f"PRIMENG_DROPDOWN_ERROR: {str(dd_err)[:300]}"),
                }

        # ── SEMANTIC_CLICK / SEMANTIC_FILL — split-execution coordinate resolver ──
        elif action_type in ("semantic_click", "semantic_fill"):
            target = action.get("target")
            value = action.get("value", "") or ""

            if not target:
                return {
                    "success": False,
                    "error_message": f"action='{action_type}' requires 'target' description.",
                    "actual_url": page.url,
                    "dom_failure_diagnosis": "SEMANTIC_ACTION_NO_TARGET",
                }

            from backend.browser.vision_utils import LocalObjectDetector

            # Resolve target locally
            coords = await LocalObjectDetector.resolve_target(page, target)

            if not coords:
                logger.warning(
                    "[executor] Local coordinate resolution failed for target '%s'. Falling back.",
                    target
                )

                # Standard locator fallback
                try:
                    inferred_role = None
                    target_lower = target.lower()
                    if "button" in target_lower:
                        inferred_role = "button"
                    elif "link" in target_lower:
                        inferred_role = "link"
                    elif "input" in target_lower or "textbox" in target_lower:
                        inferred_role = "textbox"

                    clean_name = target
                    for stopword in ("button", "link", "input", "textbox"):
                        clean_name = clean_name.replace(stopword, "").replace(stopword.capitalize(), "")
                    clean_name = clean_name.strip()

                    if inferred_role:
                        locator = page.get_by_role(inferred_role, name=clean_name)
                    else:
                        locator = page.get_by_text(target)

                    await locator.scroll_into_view_if_needed(timeout=2000)
                    if action_type == "semantic_fill":
                        await locator.fill(value, timeout=5000)
                    else:
                        await locator.click(timeout=5000)

                    logger.info(
                        "[executor] Standard locator fallback succeeded for target '%s'",
                        target
                    )
                    return {
                        "success": True,
                        "error_message": None,
                        "actual_url": page.url,
                        "last_executor_fallback": f"Standard locator fallback: {target}",
                    }
                except Exception as fallback_err:
                    return {
                        "success": False,
                        "error_message": (
                            f"semantic action failed: local resolution for target '{target}' failed, "
                            f"and standard locator fallback also failed: {fallback_err}"
                        ),
                        "actual_url": page.url,
                        "dom_failure_diagnosis": f"SEMANTIC_RESOLUTION_FAILED: target={target}",
                    }

            x, y = coords["x"], coords["y"]
            css_fallback = coords.get("selector", "")
            tag = coords.get("tag", "?")
            text = coords.get("text", "")

            try:
                await page.mouse.move(x, y)
                await page.wait_for_timeout(150)
                await page.mouse.click(x, y, delay=100)
                await page.wait_for_timeout(250)
                logger.info(
                    "[executor] Coordinate click resolved locally for target '%s' -> (%d, %d) [<%s> '%s']",
                    target,
                    x,
                    y,
                    tag,
                    text,
                )

                if action_type == "semantic_fill":
                    await page.wait_for_timeout(200)
                    await page.keyboard.press("Control+a")
                    await page.keyboard.type(value, delay=30)
                    logger.info(
                        "[executor] Typed '%s' into resolved target '%s'",
                        value,
                        target,
                    )
            except Exception as coord_err:
                if css_fallback:
                    logger.warning(
                        "[executor] Local coordinate click failed: %s. Trying CSS fallback: '%s'",
                        coord_err,
                        css_fallback,
                    )
                    try:
                        fallback_locator = page.locator(css_fallback)
                        if action_type == "semantic_fill":
                            await fallback_locator.fill(value, timeout=5000)
                        else:
                            await fallback_locator.click(timeout=5000)
                        logger.info(
                            "[executor] CSS fallback succeeded: '%s'",
                            css_fallback,
                        )
                    except Exception as fallback_err:
                        return {
                            "success": False,
                            "error_message": (
                                f"semantic action failed: coordinate click failed at ({x},{y}), "
                                f"and CSS fallback ('{css_fallback}') also failed: {fallback_err}"
                            ),
                            "actual_url": page.url,
                            "dom_failure_diagnosis": f"SEMANTIC_CLICK_FAILED: target={target}",
                        }
                else:
                    return {
                        "success": False,
                        "error_message": f"semantic action failed: coordinate click failed at ({x},{y}). No fallback.",
                        "actual_url": page.url,
                        "dom_failure_diagnosis": f"SEMANTIC_CLICK_FAILED: target={target}",
                    }

        # ── COORDINATE_ACTION — vision-mode coordinate-based click/fill ───
        # The LLM passes a mark_id from the annotated screenshot.
        # The executor resolves it to (x, y) pixel coordinates and
        # executes a raw page.mouse.click().  Optional text_to_fill
        # triggers keyboard typing after the click (for input fields).
        #
        # Coordinate Drift Fallback: if the coordinate click doesn't
        # produce the expected result, the CSS selector from the same
        # map entry can be used as a secondary Playwright locator.
        elif action_type == "coordinate_action":
            mark_id = action.get("mark_id")
            text_to_fill = action.get("text_to_fill", "") or ""

            if mark_id is None:
                return {
                    "success": False,
                    "error_message": (
                        "coordinate_action requires 'mark_id' — the numbered box ID from the annotated screenshot."
                    ),
                    "actual_url": page.url,
                    "dom_failure_diagnosis": "COORDINATE_ACTION_NO_MARK_ID",
                }

            _mark_map = state.get("mark_coordinate_map", {})
            coords = _mark_map.get(str(mark_id))

            if not coords:
                return {
                    "success": False,
                    "error_message": (
                        f"coordinate_action: mark_id {mark_id} not found in the coordinate map. "
                        f"Available mark IDs: {list(_mark_map.keys())[:20]}. "
                        f"The mark IDs from the screenshot may have changed — request a new screenshot."
                    ),
                    "actual_url": page.url,
                    "dom_failure_diagnosis": f"COORDINATE_MARK_NOT_FOUND: mark_id={mark_id}",
                }

            x, y = coords["x"], coords["y"]
            css_fallback = coords.get("selector", "")
            tag = coords.get("tag", "?")
            text = coords.get("text", "")

            # Guard: reject clicks whose coordinates are outside the visible viewport.
            # Negative Y means the SoM mark was placed on an element that is scrolled
            # off-screen (e.g. a column that overflows the viewport to the right maps
            # to a negative screen-space Y after projection). A click at those coords
            # silently lands on the browser chrome or nowhere — the element is not hit.
            viewport = page.viewport_size
            if viewport and (y <= 0 or y >= viewport["height"] or x <= 0 or x >= viewport["width"]):
                logger.warning(
                    "[coordinate_action] mark_id=%d at (%d, %d) is outside the visible viewport %s — "
                    "element is scrolled off-screen. Rejecting coordinate click.",
                    mark_id,
                    x,
                    y,
                    viewport,
                )
                return {
                    "success": False,
                    "error_message": (
                        f"coordinate_action: mark_id={mark_id} at ({x}, {y}) is outside the visible "
                        f"viewport {viewport}. The element is scrolled off-screen. "
                        f"Use get_by_text or get_by_role to locate it instead of a coordinate click."
                    ),
                    "actual_url": page.url,
                    "dom_failure_diagnosis": (
                        f"COORDINATE_OFF_VIEWPORT: mark_id={mark_id} at ({x},{y}), viewport={viewport}"
                    ),
                }

            try:
                # Primary: humanized coordinate click at the exact center of the marked element
                # Move first to trigger Angular hover/focus states, then click with delay
                await page.mouse.move(x, y)
                await page.wait_for_timeout(150)  # Let Angular register the hover
                await page.mouse.click(x, y, delay=100)  # Slight delay between mousedown/mouseup
                await page.wait_for_timeout(250)  # Let Angular process the click + animations
                logger.info(
                    "[coordinate_action] Clicked mark_id=%d at (%d, %d) — <%s> '%s'",
                    mark_id,
                    x,
                    y,
                    tag,
                    text[:40],
                )

                # Optional: type text after clicking (for input fields).
                #
                # Uses ``keyboard.type()`` — NOT ``locator.fill()`` — because
                # the click has already focused the correct visible search
                # input (e.g. select2 focuses ``.select2-search__field`` after
                # you click the container, and the underlying form field with
                # the stable id is a *different* element from the one you
                # visually clicked). ``locator.fill(css_from_map)`` would
                # write into the form-value store instead of the search box
                # and the dropdown UI would never update — observed on
                # QA-358 ghost login where ``#ghost_id`` is select2's hidden
                # backing input, filling it succeeds silently while the
                # dropdown stays empty.
                #
                # Readonly p-calendar/p-select display inputs are already
                # excluded from the SoM mark list (``vision_utils.py:148``
                # ``:not([readonly])``), so keyboard-typing here should not
                # hit the silent-swallow scenario Bug 1b was defending
                # against — the mark would never exist in the first place.
                if text_to_fill:
                    await page.wait_for_timeout(200)
                    await page.keyboard.press("Control+a")
                    await page.keyboard.type(text_to_fill, delay=30)
                    logger.info(
                        "[coordinate_action] Typed '%s' into mark_id=%d",
                        text_to_fill[:40],
                        mark_id,
                    )

            except Exception as coord_err:
                # ── Coordinate Drift Fallback ─────────────────────────────────
                # If the coordinate click failed (element shifted, page scrolled),
                # try the CSS selector from the same coordinate map entry.
                if css_fallback:
                    logger.warning(
                        "[coordinate_action] Coordinate click failed at (%d, %d): %s — "
                        "falling back to CSS selector '%s'",
                        x,
                        y,
                        str(coord_err)[:100],
                        css_fallback,
                    )
                    try:
                        fallback_locator = page.locator(css_fallback)
                        await fallback_locator.click(timeout=5000)
                        logger.info(
                            "[coordinate_action] CSS fallback succeeded: '%s'",
                            css_fallback,
                        )
                        if text_to_fill:
                            await page.keyboard.press("Control+a")
                            await page.keyboard.type(text_to_fill, delay=30)
                    except Exception as fallback_err:
                        return {
                            "success": False,
                            "error_message": (
                                f"coordinate_action: both coordinate click ({x},{y}) and "
                                f"CSS fallback ('{css_fallback}') failed. "
                                f"Coordinate error: {str(coord_err)[:100]}. "
                                f"CSS error: {str(fallback_err)[:100]}."
                            ),
                            "actual_url": page.url,
                            "dom_failure_diagnosis": (
                                f"COORDINATE_DRIFT: mark_id={mark_id} at ({x},{y}) missed, "
                                f"CSS fallback '{css_fallback}' also failed."
                            ),
                        }
                else:
                    return {
                        "success": False,
                        "error_message": (
                            f"coordinate_action: click failed at ({x},{y}) for mark_id={mark_id}: "
                            f"{str(coord_err)[:200]}. No CSS fallback available."
                        ),
                        "actual_url": page.url,
                        "dom_failure_diagnosis": (f"COORDINATE_CLICK_FAILED: mark_id={mark_id} at ({x},{y})"),
                    }

        # ── FEAT-007: FILL_AND_SUBMIT ─────────────────────────────────
        # Atomic fill + submit in one action.  Fills a field, then either
        # presses Enter or clicks a submit button.  On submit failure,
        # returns a partial-success diagnostic so the planner can handle
        # the submit step separately.
        elif action_type == "fill_and_submit":
            locator = await _resolve_locator(page, action)
            try:
                await locator.scroll_into_view_if_needed(timeout=2000)
            except Exception:
                pass

            # ── Phase 1: Fill (reuses existing fill logic) ────────────
            run_id_for_fixture = action.get("_run_id", "")
            if run_id_for_fixture and value:
                fm = FixtureManager(run_id_for_fixture)
                field_name_for_stamp = action.get("name", "") or action.get("role", "") or action.get("label", "")
                step_type_for_stamp = action.get("_step_type", "") or ""
                stamped_value = fm.stamp(
                    str(value),
                    field_name=field_name_for_stamp,
                    step_type=step_type_for_stamp,
                )
                if stamped_value != str(value):
                    logger.info(
                        "[executor] fill_and_submit: stamped '%s' → '%s'",
                        str(value)[:40],
                        stamped_value[:50],
                    )
                value = stamped_value

            try:
                await locator.fill(value, timeout=15000)
            except Exception as _fill_err:
                _fill_msg = str(_fill_err)
                # Child-input fallback (same as regular fill)
                if "Element is not an" in _fill_msg or "not an <input>" in _fill_msg:
                    _child_input = locator.locator("input, textarea").first
                    try:
                        _child_count = await _child_input.count()
                    except Exception:
                        _child_count = 0
                    if _child_count > 0:
                        await _child_input.fill(value, timeout=15000)
                    else:
                        raise
                else:
                    raise

            logger.info(
                "[executor] fill_and_submit: fill phase complete for '%s'",
                action.get("name", "?"),
            )

            # ── Phase 2: Submit ────────────────────────────────────────
            submit_strategy = action.get("submit_strategy", "enter")
            submit_name = action.get("submit_name", "")
            _submit_failed = False
            _submit_error = ""

            try:
                if submit_strategy == "enter":
                    await page.keyboard.press("Enter")
                    logger.info("[executor] fill_and_submit: pressed Enter")
                elif submit_strategy == "click_button":
                    if not submit_name:
                        _submit_failed = True
                        _submit_error = (
                            "submit_strategy='click_button' but submit_name is empty. "
                            "Provide the button's visible text."
                        )
                    else:
                        # Try get_by_role(button) first, fall back to get_by_text
                        try:
                            submit_btn = page.get_by_role("button", name=submit_name)
                            await submit_btn.click(timeout=10000)
                        except Exception:
                            submit_btn = page.get_by_text(submit_name)
                            await submit_btn.click(timeout=8000)
                        logger.info(
                            "[executor] fill_and_submit: clicked submit button '%s'",
                            submit_name,
                        )
                else:
                    _submit_failed = True
                    _submit_error = f"Unknown submit_strategy '{submit_strategy}'. Use 'enter' or 'click_button'."
            except Exception as _submit_err:
                _submit_failed = True
                _submit_error = f"Submit failed: {str(_submit_err)[:200]}"
                logger.warning(
                    "[executor] fill_and_submit: submit phase failed: %s",
                    _submit_error[:100],
                )

            # Graceful fallback: fill succeeded, submit may have failed
            if _submit_failed:
                return {
                    "success": True,  # Fill DID succeed
                    "error_message": (
                        f"COMPOSITE_PARTIAL_SUCCESS: fill('{value[:40]}') succeeded but "
                        f"submit failed: {_submit_error}. The field value is set correctly. "
                        f"Use a separate press_key('Enter') or click action to submit."
                    ),
                    "actual_url": page.url,
                    "last_executor_fallback": "fill_and_submit: fill OK, submit FAILED",
                }

        # ── FEAT-007: CLICK_AND_WAIT ──────────────────────────────────
        # Atomic click + wait-for-element in one action.  Clicks the
        # target element, then waits up to 10s for a specified selector
        # or text to appear.  On wait timeout, returns click-success
        # with a diagnostic noting the wait target was not found.
        elif action_type == "click_and_wait":
            locator = await _resolve_locator(page, action)
            force = bool(action.get("force", False))

            try:
                await locator.scroll_into_view_if_needed(timeout=3000)
            except Exception:
                pass

            # ── Phase 1: Click ────────────────────────────────────────
            await locator.click(timeout=15000, force=force)
            logger.info(
                "[executor] click_and_wait: click phase complete for '%s'",
                action.get("name", "?"),
            )

            # ── Phase 2: Wait for target ──────────────────────────────
            wait_selector = action.get("wait_for_selector", "") or ""
            wait_text = action.get("wait_for_text", "") or ""
            _wait_succeeded = False
            _wait_error = ""

            try:
                if wait_selector:
                    await page.wait_for_selector(
                        wait_selector,
                        state="visible",
                        timeout=10000,
                    )
                    _wait_succeeded = True
                    logger.info(
                        "[executor] click_and_wait: selector '%s' visible",
                        wait_selector,
                    )
                elif wait_text:
                    # Poll for text in DOM (up to 10s, 500ms intervals)
                    for _poll in range(20):
                        try:
                            _page_text = await page.evaluate("() => document.body.innerText")
                            if wait_text.lower() in _page_text.lower():
                                _wait_succeeded = True
                                logger.info(
                                    "[executor] click_and_wait: text '%s' found in DOM",
                                    wait_text[:50],
                                )
                                break
                        except Exception:
                            pass
                        await page.wait_for_timeout(500)
                    if not _wait_succeeded:
                        _wait_error = f"Text '{wait_text}' not found in DOM within 10s."
            except Exception as _wait_err:
                _wait_error = f"Wait failed: {str(_wait_err)[:200]}"
                logger.warning(
                    "[executor] click_and_wait: wait phase failed: %s",
                    _wait_error[:100],
                )

            # Graceful fallback: click succeeded, wait may have failed
            if not _wait_succeeded:
                return {
                    "success": True,  # Click DID succeed
                    "error_message": (
                        f"COMPOSITE_PARTIAL_SUCCESS: click('{action.get('name', '?')}') "
                        f"succeeded but the wait target was not found: {_wait_error}. "
                        f"Use a separate verify or wait action to confirm the result."
                    ),
                    "actual_url": page.url,
                    "last_executor_fallback": "click_and_wait: click OK, wait FAILED",
                }

        # ── FEAT-007: SELECT_AND_VERIFY ───────────────────────────────
        # Atomic select + verify in one action.  Selects a dropdown
        # option, then verifies the result by checking the dropdown's
        # visible label or page content.  On verify failure, returns
        # select-success with a diagnostic.
        elif action_type == "select_and_verify":
            locator = await _resolve_locator(page, action)

            # ── Phase 1: Select the option ────────────────────────────
            await locator.select_option(value, timeout=15000)
            logger.info(
                "[executor] select_and_verify: selected '%s' in '%s'",
                value,
                action.get("name", "?"),
            )

            # ── Phase 2: Verify the selection ─────────────────────────
            verify_text = action.get("verify_text", "") or ""
            _verify_succeeded = False
            _verify_error = ""

            if verify_text:
                await page.wait_for_timeout(500)  # Let Angular digest the change

                try:
                    # Strategy 1: Check the dropdown's current visible text
                    try:
                        dropdown_text = await locator.evaluate(
                            "el => el.selectedOptions ? el.selectedOptions[0]?.text || el.value : el.innerText"
                        )
                        if verify_text.lower() in (dropdown_text or "").lower():
                            _verify_succeeded = True
                            logger.info(
                                "[executor] select_and_verify: verified via dropdown text '%s'",
                                dropdown_text[:50],
                            )
                    except Exception:
                        pass

                    # Strategy 2: Check full page text
                    if not _verify_succeeded:
                        try:
                            _page_text = await page.evaluate("() => document.body.innerText")
                            if verify_text.lower() in _page_text.lower():
                                _verify_succeeded = True
                                logger.info(
                                    "[executor] select_and_verify: verified via page text",
                                )
                        except Exception:
                            pass

                    if not _verify_succeeded:
                        _verify_error = f"Text '{verify_text}' not found in dropdown label or page."
                except Exception as _verify_err:
                    _verify_error = f"Verify failed: {str(_verify_err)[:200]}"
                    logger.warning(
                        "[executor] select_and_verify: verify phase failed: %s",
                        _verify_error[:100],
                    )
            else:
                # No verify_text — treat as pure select (always succeeds)
                _verify_succeeded = True

            # Graceful fallback: select succeeded, verify may have failed
            if not _verify_succeeded:
                return {
                    "success": True,  # Select DID succeed
                    "error_message": (
                        f"COMPOSITE_PARTIAL_SUCCESS: select_option('{value}') succeeded "
                        f"but verification failed: {_verify_error}. "
                        f"Use a separate verify action to confirm the result."
                    ),
                    "actual_url": page.url,
                    "last_executor_fallback": "select_and_verify: select OK, verify FAILED",
                }

        # ── DONE — no-op, signals AC step completion ──────────────────
        elif action_type == "done":
            pass  # Evaluator handles this signal

        # ── UNKNOWN ───────────────────────────────────────────────────
        else:
            return {
                "success": False,
                "error_message": f"Unknown action type: '{action_type}'",
                "actual_url": page.url,
            }

        # ── Transient content capture (click / press_key) ─────────────
        # Use wait_for_selector to grab toast/alert text in one fast call.
        # Timeout 1.5s — if nothing appears we move on immediately.
        if action_type in ("click", "press_key", "fill_and_submit", "click_and_wait"):
            TRANSIENT_SELECTORS = (
                '[role="alert"],[role="status"],.toast,.toaster,.notification,'
                '.alert,.snackbar,.banner,[class*="toast"],[class*="alert"],'
                '[class*="notification"],[class*="snack"]'
            )
            captured = ""
            try:
                await page.wait_for_selector(TRANSIENT_SELECTORS, timeout=800, state="visible")
                captured = await page.evaluate(
                    f"""() => {{
                        const el = document.querySelector('{TRANSIENT_SELECTORS}');
                        return el ? el.innerText.trim() : '';
                    }}"""
                )
            except Exception:
                # Nothing appeared — not an error, just no transient element
                captured = ""
        else:
            captured = ""

        # ── Post-action: network-based timing (Phase 4 hardening) ──────
        # Replaces the legacy _wait_for_vsuite_spinners (10s) +
        # _wait_for_stable_dom (8s) with the network_sync module:
        #   1. wait_for_spinners_cleared (3s cap) — visual-readiness
        #   2. wait_for_data_settled (networkidle + DOM fallback) — data-readiness
        # Average post-action wait drops from ~5-8s to ~1-2s.
        #
        # DEFENSIVE DESIGN: Network sync is AUXILIARY — a timeout or error
        # here must NEVER crash a successful Playwright action.  The action
        # result (success=True) is the ground truth; sync is best-effort.
        if action_type in (
            "click",
            "press_key",
            "fill",
            "select_option",
            "set_input_files",
            "navigate",
            "fill_and_submit",
            "click_and_wait",
            "select_and_verify",
        ):
            _rid = state.get("run_id", "") if isinstance(state, dict) else ""
            try:
                from backend.browser.network_sync import (
                    wait_for_data_settled,
                    wait_for_spinners_cleared,
                )

                await wait_for_spinners_cleared(page, timeout_ms=3000, run_id=_rid)
                if action_type in ("click", "press_key", "navigate"):
                    await wait_for_data_settled(page, timeout_ms=5000, run_id=_rid)
            except Exception as _sync_err:
                logger.warning(
                    "[%s] Network sync failed after '%s' action (non-fatal, continuing): %s",
                    _rid,
                    action_type,
                    _sync_err,
                )

        # ─── Predictive State Verification (TASK-095) ─────────────────────
        state_expectation = action.get("state_expectation")
        if state_expectation:
            await page.wait_for_timeout(500)
            from backend.engine.verifier import PredictiveVerifier, PredictiveVerificationError
            is_valid = await PredictiveVerifier.verify_expectation(page, state_expectation)
            if not is_valid:
                logger.info(f"Predictive verification mismatch: expected '{state_expectation}' but post-action state check failed. Short-circuiting to self-healing.")
                raise PredictiveVerificationError(
                    f"Predictive verification mismatch: expected '{state_expectation}' but post-action state check failed."
                )

        return_extra = {"transient_page_text": captured} if captured else {}

        return {
            "success": True,
            "error_message": None,
            "actual_url": page.url,
            "last_executor_fallback": executor_fallback_used,
            **return_extra,
        }

    except PlaywrightTimeout as e:
        # ── DOM interrogation on timeout ──────────────────────────────────
        # Categorize WHY the timeout happened so the evaluator gives the LLM
        # a principled retry signal instead of "Timeout 15000ms exceeded".
        error_msg = f"Timeout ({action_type}): {str(e)[:200]}"
        dom_diag = ""
        target_name = action.get("name", "") or action.get("value", "")
        if target_name and page:
            try:
                counts = await page.evaluate(f"""() => {{
                    const name = {repr(str(target_name))};
                    const all = Array.from(document.querySelectorAll('*'));
                    const matching = all.filter(el =>
                        (el.textContent || '').trim().includes(name) ||
                        (el.getAttribute('aria-label') || '').includes(name) ||
                        (el.getAttribute('placeholder') || '').includes(name)
                    );
                    const visible = matching.filter(el => {{
                        const r = el.getBoundingClientRect();
                        return r.width > 0 && r.height > 0;
                    }});
                    return {{ total: matching.length, visible: visible.length }};
                }}""")
                total = counts.get("total", 0)
                visible = counts.get("visible", 0)
                if total == 0:
                    dom_diag = (
                        f"DOM_ABSENT: '{target_name}' not found anywhere in the DOM. "
                        f"The selector is wrong or the element has not rendered yet. "
                        f"Add a wait action or use a different locator strategy."
                    )
                elif visible == 0:
                    dom_diag = (
                        f"DOM_HIDDEN: '{target_name}' is in the DOM ({total}\u00d7) "
                        f"but has zero visible bounding box \u2014 it is in a closed dropdown, "
                        f"off-screen, or behind an overlay. Click a parent element to reveal it."
                    )
                else:
                    dom_diag = (
                        f"DOM_PRESENT_VISIBLE: '{target_name}' is visible ({visible}\u00d7). "
                        f"Possible causes: strict mode (multiple matches), Angular overlay, "
                        f"or element not yet interactive. Try .first, force=true, or exact=True."
                    )
            except Exception:
                pass  # DOM interrogation is best-effort

        return {
            "success": False,
            "error_message": error_msg,
            "actual_url": page.url,
            "dom_failure_diagnosis": dom_diag,
        }

    except Exception as e:
        return {
            "success": False,
            "error_message": f"{type(e).__name__}: {str(e)[:200]}",
            "actual_url": page.url,
            "dom_failure_diagnosis": (
                f"EXCEPTION_{type(e).__name__}: {str(e)[:150]} \u2014 "
                f"This is likely a locator syntax error or unsupported action."
            ),
        }


# ---------------------------------------------------------------------------
# Auth State Machine
# ---------------------------------------------------------------------------

# Keywords that indicate the current AC step is itself a login/auth step.
# If matched, the auth gate allows execution even without a JWT.
_AUTH_STEP_KEYWORDS = [
    "login",
    "log in",
    "sign in",
    "authenticate",
    "navigate to",
    "enter email",
    "enter password",
    "enter credentials",
    "enter invalid",
    "invalid email",
    "invalid password",
    "wrong email",
    "wrong password",
    "incorrect email",
    "incorrect password",
    "failed login",
    "login failure",
    "invalid credentials",
]


def _sub_action_looks_like_auth(sub_action: dict | None) -> bool:
    """
    Return True when the pending action is filling a login field or
    clicking a login button — indicates the auth flow is IN PROGRESS
    and the auth gate should not preempt it. Product-agnostic:
    matches any locator whose name/text names an email/password/login
    control, regardless of framework (vSuite PrimeNG login, vpromotions
    SSO login, etc.).
    """
    if not isinstance(sub_action, dict):
        return False
    # Compare against locator hints the planner emits.
    hints: list[str] = []
    for field in ("locator_value", "target_name", "name", "text", "container_selector"):
        val = sub_action.get(field)
        if isinstance(val, str) and val.strip():
            hints.append(val.lower())
    # ARIA fields also carry the semantic name.
    aria_name = sub_action.get("_aria_name") or sub_action.get("aria_name")
    if isinstance(aria_name, str) and aria_name.strip():
        hints.append(aria_name.lower())
    if not hints:
        return False
    haystack = " ".join(hints)
    # Explicit auth-widget name tokens. Deliberately narrow — matches
    # login form fields and submit buttons only.
    auth_tokens = (
        "email", "e-mail", "username", "user name", "user-name",
        "password", "passwd", "pass word",
        "login", "log in", "log-in", "sign in", "sign-in", "signin",
    )
    return any(tok in haystack for tok in auth_tokens)


async def _check_auth_state(page, state: dict, sub_action: dict | None = None) -> dict | None:
    """
    Pre-dispatch authentication state machine.

    Reads the vSuite JWT from localStorage and checks if the URL indicates
    an unauthenticated state (login / auth page). If the session has expired
    and the current AC step is NOT a login step, returns a structured failure
    dict that routes the run to human_takeover rather than dispatching the
    planned browser action blindly.

    Args
    ----
    page : playwright.async_api.Page
        The live Playwright page.
    state : dict
        Current VQAState — used to read the current AC step text.

    Returns
    -------
    dict | None
        A failure result dict if the auth gate is tripped, or None if auth
        is confirmed and execution should proceed normally.
    """
    run_id = state.get("run_id", "?")
    ac_steps = state.get("jira_ticket", {}).get("acceptance_criteria_steps", [])
    ac_idx = state.get("ac_step_index", 0)
    current_step = ac_steps[ac_idx].lower() if ac_idx < len(ac_steps) else ""

    # Skip the auth check entirely in failed login testing mode.
    # The agent is intentionally unauthenticated — blocking on missing JWT
    # would prevent the AC steps from testing the login failure experience.
    if state.get("expect_login_failure", False):
        return None

    # Skip the auth check for GHOST_LOGIN structured steps.
    # ghost_login_node is the authority for authentication in these flows — the
    # browser will be on the login page (unauthenticated) until ghost_login_node
    # runs. Blocking here causes an AUTH_GATE_BLOCKED loop.
    _gl_test_plan = state.get("test_plan") or {}
    _gl_plan_steps = (
        list(_gl_test_plan.steps)
        if hasattr(_gl_test_plan, "steps")
        else (_gl_test_plan.get("steps") or [])
    )
    _gl_struct_idx = state.get("structured_step_index", ac_idx)
    if _gl_struct_idx < len(_gl_plan_steps):
        _gl_step = _gl_plan_steps[_gl_struct_idx]
        _gl_step_type = (
            _gl_step.get("step_type")
            if isinstance(_gl_step, dict)
            else getattr(_gl_step, "step_type", "")
        )
        if _gl_step_type == "GHOST_LOGIN":
            return None

    # Skip the auth check for steps that are themselves authentication steps.
    if any(kw in current_step for kw in _AUTH_STEP_KEYWORDS):
        return None

    # Skip if the pending action is filling a login form field or clicking a
    # login button. When the AC parser did NOT generate explicit auth steps
    # (e.g. plan starts with "Navigate to PRF home page" but the browser is
    # actually at the SSO login page), the planner will still correctly try
    # to fill email/password/login — do not preempt that flow with an
    # AUTH_GATE_BLOCKED. Product-agnostic.
    if _sub_action_looks_like_auth(sub_action):
        logger.debug(
            "[%s] Auth gate skipped — pending action targets a login control",
            run_id,
        )
        return None

    try:
        current_url = page.url.lower()
        is_login_url = any(p in current_url for p in ("/login", "/auth", "/sign-in", "/signin"))

        jwt = await page.evaluate("() => localStorage.getItem('vc2JWT') || ''")
        cookies = await page.context.cookies()
        has_auth_cookie = any(
            any(k in c.get("name", "").lower() for k in ["ssojwt", "vc2jwt", "vcreative_session", "ppo_session"])
            for c in cookies
        )
        is_authenticated = bool((jwt and jwt.strip()) or has_auth_cookie)

        if is_login_url and not is_authenticated:
            _msg = (
                f"AUTH_GATE_BLOCKED: Browser is on '{page.url}' and vc2JWT is missing. "
                f"The session has expired or login was not completed before AC steps began. "
                f"Human intervention required to re-authenticate."
            )
            logger.error("[%s] [AUTH_GATE] %s", run_id, _msg)
            return {
                "success": False,
                "error_message": _msg,
                "actual_url": page.url,
                "dom_failure_diagnosis": (
                    "AUTH_GATE_BLOCKED: Session expired mid-run. "
                    "The agent is on the login page without credentials. "
                    "Re-login required before continuing AC steps."
                ),
            }
    except Exception as _auth_err:
        # Auth check failure is non-fatal — log and proceed.
        logger.debug("[%s] Auth state check failed (non-fatal): %s", run_id, _auth_err)

    return None


# ---------------------------------------------------------------------------
# LangGraph node function
# ---------------------------------------------------------------------------


async def executor_node(state: VQAState) -> dict:
    """
    LangGraph node: ACT phase of the see-think-act loop.

    Reads ``planned_action`` from the state, executes it via Playwright,
    captures a post-action screenshot, and appends an ``ExecutionStep``
    to the audit log.

    Supports both single-action and batched-action modes.  When the
    planner returns a JSON array (batched actions), the executor processes
    each action sequentially in a single node invocation — eliminating
    LLM round-trips for synchronous form fills, login flows, etc.

    Args
    ----
    state : VQAState
        The current LangGraph state.  Must contain:
        - ``run_id``: for browser manager lookup
        - ``planned_action``: the JSON action from the planner
          If ``planned_action`` contains a ``_batch`` key, it is treated
          as a list of actions to execute sequentially.

    Returns
    -------
    dict
        Partial state update containing:
        - ``detailed_execution_log``: list with new ExecutionStep(s)
        - ``screenshots``: list with new S3 URL(s) (if captured)
        - ``current_page_url``: updated browser URL
        - ``current_screenshot_b64``: updated screenshot for next planner pass
        - ``last_error``: error message if any action failed, empty if success
    """
    run_id: str = state["run_id"]
    action: dict = state.get("planned_action", {})

    # ── SoM box_id resolution ────────────────────────────────────────
    # If the planner used Set-of-Marks mode, it may emit {"box_id": N}
    # actions. Resolve them to concrete {"strategy": "css_selector", "name": ...}
    # actions using the element map stored in state by the planner.
    _som_map: dict = state.get("som_element_map", {})
    if _som_map and isinstance(action, dict):
        try:
            from backend.browser.set_of_marks import resolve_box_id as _rbid

            if action.get("_batch"):
                action = {**action, "_batch": [_rbid(a, _som_map) for a in action["_batch"]]}
            else:
                action = _rbid(action, _som_map)
        except (ValueError, Exception) as _som_resolve_err:
            logger.warning("[%s] SoM box_id resolution failed: %s", run_id, _som_resolve_err)
            # Continue with original action — executor will fail with a normal error

    # ── Detect batch mode ────────────────────────────────────────────
    batch_actions: list[dict] | None = action.get("_batch") if isinstance(action, dict) else None
    is_batch = bool(batch_actions)
    actions_to_run: list[dict] = batch_actions if is_batch else [action]

    # ── Get the live browser page ─────────────────────────────────────
    # Multi-actor support: if the Supervisor-Worker graph has set an
    # active_actor, resolve the Page from the BrowserManager's actor
    # registry.  Falls through to manager.page for the legacy graph
    # (active_actor is "" by default).
    manager = get_manager(run_id)
    active_actor: str = state.get("active_actor", "")
    if active_actor and hasattr(manager, "_actor_registry"):
        if active_actor in manager._actor_registry:
            _, page = manager._actor_registry[active_actor]
            logger.debug(
                "[%s] Executor: using actor registry page for '%s'",
                run_id,
                active_actor,
            )
        else:
            page = manager.page
            logger.warning(
                "[%s] Executor: active_actor='%s' not in registry — falling back to primary page",
                run_id,
                active_actor,
            )
    else:
        page = manager.page
    if page is None:
        raise RuntimeError(f"[{run_id}] Browser page is None")

    # ── Hardware-level Force Wait (FEAT-049 / TASK-054) ────────────────
    # Prevents "staccato" execution on problematic PrimeNG components that
    # re-render DOM multiple times during loading.
    if state.get("_force_wait_before_next_action", False):
        wait_ms = state.get("_force_wait_ms", 1500)
        logger.info("[%s] Hardware-level force wait: pausing for %d ms", run_id, wait_ms)
        await page.wait_for_timeout(wait_ms)

    # ── State Snapshot Verification (Before Action) ────────────────────
    _tracker = get_tracker(run_id)
    _dom_snapshot_before = state.get("dom_snapshot_before", "")
    if _tracker and page and not page.is_closed():
        try:
            # We don't want to refresh if we already have a valid one,
            # but to be safe and accurate, let's just format the current tracker state.
            # Usually tracker state is updated at the end of the previous action.
            # But let's refresh to ensure it's perfectly accurate before action.
            await _tracker.refresh(page)
            _dom_snapshot_before = _tracker.format_for_prompt()
        except Exception as _tracker_err:
            logger.debug("[%s] PageStateTracker pre-action refresh failed: %s", run_id, _tracker_err)

    # ── Pre-action state capture (Interaction Verification) ──────────
    # Capture URL, ARIA snapshot, and element count before the action
    # so the verifier can perform state-change detection (TASK-054).
    import json as _json_exec
    pre_state = {
        "url": page.url,
        "aria_snapshot": None,
        "element_count": None,
    }
    if page and not page.is_closed():
        try:
            _raw_aria = await page.accessibility.snapshot()
            pre_state["aria_snapshot"] = _json_exec.dumps(_raw_aria, sort_keys=True) if _raw_aria else ""
            pre_state["element_count"] = await page.evaluate("document.querySelectorAll('*').length")
        except Exception as _snap_err:
            logger.debug("[%s] Pre-action state capture failed: %s", run_id, _snap_err)

    # Accumulate results across all actions in the batch
    all_steps: list[ExecutionStep] = []
    navigation_history: list[str] = list(state.get("navigation_history", []))
    final_screenshot_b64: str = state.get("current_screenshot_b64", "")
    final_url: str = state.get("current_page_url", "")
    final_error: str = ""
    final_transient: str = state.get("transient_page_text", "")

    base_step_index: int = len(state.get("detailed_execution_log", []))
    _last_recipe_result: dict = {}  # Tracks the last recipe dispatch result for idempotent-skip detection

    for sub_idx, sub_action in enumerate(actions_to_run):
        sub_action_type: str = sub_action.get("action", "unknown")
        step_index: int = base_step_index + sub_idx

        if is_batch:
            logger.info(
                "[%s] Batch step %d/%d (global step %d): %s → %s",
                run_id,
                sub_idx + 1,
                len(actions_to_run),
                step_index,
                sub_action_type,
                sub_action.get("name", sub_action.get("value", "?")),
            )
        else:
            logger.info(
                "[%s] Executing step %d: %s → %s",
                run_id,
                step_index,
                sub_action_type,
                sub_action.get("name", sub_action.get("value", "?")),
            )

        timestamp: str = datetime.now(timezone.utc).isoformat()

        # ── Hard Circuit Breaker: identical-action deduplication ──────────────
        # Build a normalized key that uniquely identifies this (action, selector)
        # combination. If the same key is attempted more than _CIRCUIT_BREAKER_MAX
        # times on the same AC step without a Verifier SUCCESS, we halt with a
        # structured failure instead of looping indefinitely.
        #
        # The repeat budget is generous enough to allow the legitimate pattern of:
        #   attempt 1 → verifier NOT_YET → attempt 2 → NOT_YET → attempt 3 → TRIP
        # This prevents the 106-click loop and p-menu oscillation failures.
        _CIRCUIT_BREAKER_MAX = 3
        _cb_a = sub_action.get("action", "")
        _cb_s = sub_action.get("strategy", "")
        _cb_r = sub_action.get("role", "")
        _cb_n = sub_action.get("name", "") or sub_action.get("value", "")
        _cb_sel = sub_action.get("selector", "")
        _cb_recipe = sub_action.get("recipe_name", "")
        _cb_container = sub_action.get("container_selector", "")

        # TASK-021: Add mark_id, trigger_mark_id, and target_text for coordinate_action/primeng_dropdown
        _cb_mark = sub_action.get("mark_id", "")
        _cb_trigger_mark = sub_action.get("trigger_mark_id", "")
        _cb_target_text = sub_action.get("target_text", "")

        # For coordinate_action with text_to_fill, use the mark's RESOLVED CSS
        # selector in the CB key instead of the volatile mark_id. Mark IDs
        # renumber every screenshot, so the same DOM element can appear as
        # mark 12 → 13 → 15 across iterations — with mark_id in the key, the
        # CB never accumulates. Using the selector-from-map catches the
        # "planner cycles through different readonly inputs" loop observed
        # on QA-358 (Fill contest name field).
        _cb_fill = sub_action.get("text_to_fill", "") or ""
        _cb_resolved_sel = ""
        if _cb_a == "coordinate_action" and _cb_mark != "" and _cb_fill:
            _mm = state.get("mark_coordinate_map", {}) or {}
            _cb_resolved_sel = (_mm.get(str(_cb_mark)) or {}).get("selector", "")
        _cb_mark_or_sel = _cb_resolved_sel or _cb_mark

        _selector_key = f"{_cb_a}|{_cb_s}|{_cb_r}|{_cb_n}|{_cb_sel}|{_cb_recipe}|{_cb_container}|{_cb_mark_or_sel}|{_cb_trigger_mark}|{_cb_target_text}"

        _cb_key = f"{state.get('ac_step_index', 0)}::{_selector_key}"

        # Read the current repeat count but do NOT increment yet.
        # We only count failures (success=False) — successful dispatches of the
        # same selector are the legitimate "click → wait for verifier → click again"
        # pattern and must NOT burn the circuit breaker budget.
        # See post-dispatch block where we conditionally increment / reset.
        repeat_counts: dict = dict(state.get("action_repeat_counts", {}))
        current_repeat = repeat_counts.get(_cb_key, 0)

        if current_repeat > _CIRCUIT_BREAKER_MAX and _cb_a not in ("done", "wait", "navigate", "screenshot"):
            _cb_msg = (
                f"CIRCUIT_BREAKER_TRIPPED: action='{_cb_a}' selector='{_selector_key}' "
                f"attempted {current_repeat}× on AC step "
                f"{state.get('ac_step_index', 0) + 1} without Verifier SUCCESS. "
                f"Hard Python gate — the planner MUST choose a DIFFERENT action. "
                f"(key: {_cb_key})"
            )
            logger.error("[%s] %s", run_id, _cb_msg)
            cb_step = ExecutionStep(
                step_index=step_index,
                ac_step_index=state.get("ac_step_index", 0),
                timestamp=timestamp,
                action_type=sub_action_type,
                action_payload=sub_action,
                locator_strategy=_cb_s,
                locator_value=_selector_key,
                data_input=None,
                screenshot_url="",
                accessibility_tree_snippet="",
                success=False,
                error_message=_cb_msg,
                self_heal_attempt=state.get("retry_count", 0),
                llm_reasoning="CIRCUIT_BREAKER_TRIPPED",
                llm_observation=state.get("llm_observation", "") if sub_idx == 0 else "",
                llm_thought=state.get("llm_thought", "") if sub_idx == 0 else "",
            )
            all_steps.append(cb_step)
            final_error = _cb_msg
            # Skip remaining batch items (already handled by following break)
            break

        # Pull step_type from the current test-plan step so FixtureManager
        # can skip stamping fills that target picker/filter inputs (e.g.
        # ghost-panel user filter, persona/account switch dropdowns).
        _current_step_type = ""
        _current_aria_role: str | None = None
        _current_aria_name: str | None = None
        _current_aria_disambiguators: list[str] | None = None
        try:
            _tp = state.get("test_plan") or {}
            _tp_steps = (
                _tp.get("steps") if isinstance(_tp, dict) else getattr(_tp, "steps", [])
            ) or []
            _ac_idx = state.get("ac_step_index", 0)
            if 0 <= _ac_idx < len(_tp_steps):
                _cur = _tp_steps[_ac_idx]
                _current_step_type = (
                    _cur.get("step_type") if isinstance(_cur, dict) else getattr(_cur, "step_type", "")
                ) or ""
                # A11y grounding fields (accessibility-tree-grounding Phase 2)
                # Injected by ac_aria_enricher post-login (Phase 3); None on legacy steps.
                _current_aria_role = (
                    _cur.get("aria_role") if isinstance(_cur, dict) else getattr(_cur, "aria_role", None)
                )
                _current_aria_name = (
                    _cur.get("aria_name") if isinstance(_cur, dict) else getattr(_cur, "aria_name", None)
                )
                _current_aria_disambiguators = (
                    _cur.get("aria_disambiguators") if isinstance(_cur, dict) else getattr(_cur, "aria_disambiguators", None)
                )
        except Exception:
            _current_step_type = ""

        action_with_transient = {
            **sub_action,
            "_transient": state.get("transient_page_text", ""),
            "_run_id": run_id,  # Obj 3: FixtureManager uses this to stamp fill values
            "_step_type": _current_step_type,  # Obj 3: FixtureManager skips picker/filter step types
            # A11y grounding (accessibility-tree-grounding Phase 2):
            # Propagate the TestPlanStep's ARIA fields into the action dict so
            # _resolve_locator_a11y_first can access them without needing the full step.
            "_aria_role": _current_aria_role,
            "_aria_name": _current_aria_name,
            "_aria_disambiguators": _current_aria_disambiguators,
        }

        # ── Auth State Gate (per sub-action) ────────────────────────────────
        # Only check on the FIRST sub-action in a batch (index 0) to avoid
        # N localStorage reads per batch. Sub-actions after the first share
        # the same page / session state.
        if sub_idx == 0:
            _auth_failure = await _check_auth_state(page, state, sub_action=sub_action)
            if _auth_failure is not None:
                timestamp: str = datetime.now(timezone.utc).isoformat()
                auth_step = ExecutionStep(
                    step_index=step_index,
                    ac_step_index=state.get("ac_step_index", 0),
                    timestamp=timestamp,
                    action_type="AUTH_GATE_CHECK",
                    action_payload=sub_action,
                    locator_strategy="",
                    locator_value="",
                    data_input=None,
                    screenshot_url="",
                    accessibility_tree_snippet="",
                    success=False,
                    error_message=_auth_failure["error_message"],
                    self_heal_attempt=state.get("retry_count", 0),
                    llm_reasoning="AUTH_GATE_BLOCKED",
                    llm_observation="",
                    llm_thought="",
                )
                all_steps.append(auth_step)
                final_error = _auth_failure["error_message"]
                break

        # ── DONE GUARDRAIL — Python hard gate, cannot be bypassed by prompt ─
        # Intercept the 'done' action BEFORE Playwright dispatch.  The LLM
        # frequently hallucinates completion when AC steps are still failing or
        # skipped.  Prompt rules alone are insufficient — this is the one place
        # where Python has access to both the action AND the full state.
        #
        # Logic: a 'done' signal is only valid when every AC step that should
        # have been completed (indices 0 .. ac_step_index - 1) is present in
        # ac_steps_completed.  If any are missing we short-circuit with a
        # structured error that routes back to the planner with an explicit list
        # of every unsatisfied step.  The LLM is forced to address them.
        if sub_action.get("action") == "done":
            _ac_steps_all: list = state.get("jira_ticket", {}).get("acceptance_criteria_steps", [])
            _ac_index_now: int = state.get("ac_step_index", 0)
            _completed_set: set = set(state.get("ac_steps_completed", []))

            # All steps BEFORE the current one must be in completed.
            _unsatisfied = [i for i in range(_ac_index_now) if i not in _completed_set]

            # On the last AC step, bypass the guard: prior failures are already
            # recorded; the evaluator's coverage-gap check will flag them in the
            # report.  Blocking here would loop forever with no way to finish.
            _is_last_step = _ac_index_now >= len(_ac_steps_all) - 1 if _ac_steps_all else False
            if _unsatisfied and _is_last_step:
                logger.warning(
                    "[%s] DONE GUARDRAIL: on last step (%d), allowing done with %d "
                    "incomplete prior step(s) %s — coverage gap will be reported",
                    run_id,
                    _ac_index_now + 1,
                    len(_unsatisfied),
                    [i + 1 for i in _unsatisfied],
                )
                _unsatisfied = []

            if _unsatisfied:
                _detail_lines = []
                for _i in _unsatisfied:
                    _step_text = _ac_steps_all[_i][:80] if _i < len(_ac_steps_all) else f"Step {_i + 1}"
                    _detail_lines.append(f"  • Step {_i + 1}: {_step_text}")
                _guard_msg = (
                    "SYSTEM GUARDRAIL BLOCKED: You cannot call 'done'. "
                    "The following AC steps are NOT satisfied and must be fixed first:\n"
                    + "\n".join(_detail_lines)
                    + "\nYou MUST resolve every listed step before emitting 'done'."
                )
                logger.error(
                    "[%s] DONE GUARDRAIL: blocked 'done' on AC step %d — unsatisfied steps: %s",
                    run_id,
                    _ac_index_now + 1,
                    [i + 1 for i in _unsatisfied],
                )
                # Return a structured failure so the evaluator routes back to planner
                result = {
                    "success": False,
                    "error_message": _guard_msg,
                    "actual_url": page.url,
                    "dom_failure_diagnosis": (
                        f"DONE_GUARDRAIL_BLOCKED: {len(_unsatisfied)} step(s) unresolved — "
                        f"{[i + 1 for i in _unsatisfied]}"
                    ),
                }
                success = False
                error_msg = _guard_msg
                new_repeat = repeat_counts.get(_cb_key, 0) + 1
                repeat_counts[_cb_key] = new_repeat

                done_guard_step = ExecutionStep(
                    step_index=step_index,
                    ac_step_index=state.get("ac_step_index", 0),
                    timestamp=timestamp,
                    action_type="done",
                    action_payload=sub_action,
                    locator_strategy="",
                    locator_value="",
                    data_input=None,
                    screenshot_url="",
                    accessibility_tree_snippet="",
                    success=False,
                    error_message=_guard_msg,
                    self_heal_attempt=state.get("retry_count", 0),
                    llm_reasoning="DONE_GUARDRAIL_BLOCKED",
                    llm_observation=state.get("llm_observation", "") if sub_idx == 0 else "",
                    llm_thought=state.get("llm_thought", "") if sub_idx == 0 else "",
                )
                all_steps.append(done_guard_step)
                final_error = _guard_msg
                break  # Skip remaining batch items; evaluator will re-route to planner

        result: dict = await _dispatch_action(
            page,
            action_with_transient,
            target_url=state.get("target_url", ""),
            state=state,
        )

        # Track recipe dispatch results for the idempotent-skip fast path below.
        if sub_action.get("action") == "recipe":
            _last_recipe_result = result

        # ── FEAT-037: CV Fallback Layer ───────────────────────────────────
        # After _dispatch_action returns failure for a click/coordinate_action,
        # attempt executor-side recovery via vision LLM before HITL escalation.
        # Activates only when:
        #   1. cv_fallback_enabled config flag is True
        #   2. Action type is click or coordinate_action (not fill/navigate/etc.)
        #   3. ac_step_action_fail_count >= CV_FALLBACK_MIN_DOM_FAILURES threshold
        #   4. This exact AC step has not already had a CV attempt
        _dispatch_success = result["success"]
        if not _dispatch_success and settings.cv_fallback_enabled:
            try:
                _cv_resolver = CvFallbackResolver()
                _cv_state_view = {
                    "ac_step_action_fail_count": state.get("ac_step_action_fail_count", 0),
                    "ac_step_index": state.get("ac_step_index", 0),
                    "cv_fallback_results": state.get("cv_fallback_results", []),
                }
                if _cv_resolver.should_activate(
                    _cv_state_view,
                    sub_action,
                    enabled=settings.cv_fallback_enabled,
                    min_dom_failures=settings.cv_fallback_min_dom_failures,
                ):
                    logger.info(
                        "[%s] CV_FALLBACK_ACTIVATED: step_idx=%d fail_count=%d — invoking vision LLM for target=%r",
                        run_id,
                        state.get("ac_step_index", 0),
                        state.get("ac_step_action_fail_count", 0),
                        sub_action.get("name", sub_action.get("value", "?")),
                    )
                    # Use existing mark_coordinate_map if planner already captured one
                    _existing_map = state.get("mark_coordinate_map", {}) or None
                    _target_desc = sub_action.get("name") or sub_action.get("value") or sub_action.get("reasoning", "")
                    _cv_mark_id, _cv_map, _cv_cost = await _cv_resolver.resolve(
                        page,
                        _target_desc,
                        existing_mark_map=_existing_map,
                        visual_context=state.get("visual_context"),
                    )
                    _cv_step_idx = state.get("ac_step_index", 0)
                    if _cv_mark_id is not None:
                        _cv_coords = _cv_map[str(_cv_mark_id)]
                        _cv_x, _cv_y = _cv_coords["x"], _cv_coords["y"]
                        try:
                            # Capture pre-click state for post-click verification (Phase 3)
                            # FEAT-062: Include screenshot for visual delta check
                            _cv_pre_screenshot = await capture_screenshot_b64(page, full_page=False)
                            _cv_pre_state = {
                                "url": page.url,
                                "aria_snapshot": None,  # Populated by state_change_check
                                "element_count": None,  # Populated by state_change_check
                            }
                            await page.mouse.click(_cv_x, _cv_y)
                            logger.info(
                                "[%s] CV_FALLBACK_CLICK: mark_id=%d fired at (%d, %d)",
                                run_id,
                                _cv_mark_id,
                                _cv_x,
                                _cv_y,
                            )
                            # Phase 3: Verify DOM state actually changed after CV click
                            _cv_change_result = await cv_fallback_state_change_check(
                                page,
                                _cv_pre_state,
                                screenshot_b64_before=_cv_pre_screenshot,
                                run_id=run_id,
                            )
                            if _cv_change_result["has_changed"]:
                                logger.info(
                                    "[%s] CV_FALLBACK_CLICK: state change detected — marking CV_CLICK_SUCCESS",
                                    run_id,
                                )
                                # Override result to success — verifier confirmed state change
                                result = {
                                    "success": True,
                                    "error_message": None,
                                    "actual_url": page.url,
                                    "last_executor_fallback": (
                                        f"CV_FALLBACK: mark_id={_cv_mark_id} at ({_cv_x},{_cv_y})"
                                    ),
                                    "cv_fallback": True,
                                    "cv_mark_id": _cv_mark_id,
                                    "cv_coords": {"x": _cv_x, "y": _cv_y},
                                }
                                _cv_entry = {
                                    "step_idx": _cv_step_idx,
                                    "mark_id": _cv_mark_id,
                                    "x": _cv_x,
                                    "y": _cv_y,
                                    "success": True,
                                    "cost_estimate": _cv_cost,
                                }
                            else:
                                logger.warning(
                                    "[%s] CV_FALLBACK_CLICK: no DOM state change detected after "
                                    "coordinate click at (%d, %d) — marking CV_CLICK_FAILED",
                                    run_id,
                                    _cv_x,
                                    _cv_y,
                                )
                                _cv_entry = {
                                    "step_idx": _cv_step_idx,
                                    "mark_id": _cv_mark_id,
                                    "x": _cv_x,
                                    "y": _cv_y,
                                    "success": False,
                                    "cost_estimate": _cv_cost,
                                }
                                # Augment result with CV_CLICK_FAILED context for HITL
                                _orig_err = result.get("error_message", "")
                                result = {
                                    **result,
                                    "success": False,
                                    "error_message": (
                                        f"{_orig_err} | CV_CLICK_FAILED: coordinate click at "
                                        f"({_cv_x},{_cv_y}) fired (mark_id={_cv_mark_id}) but "
                                        f"no DOM state change was detected within 2 s. "
                                        f"Escalating to HITL with CV_CLICK_FAILED context."
                                    ),
                                }
                        except Exception as _cv_click_err:
                            logger.warning(
                                "[%s] CV_FALLBACK_CLICK: coordinate click failed at (%d, %d): %s",
                                run_id,
                                _cv_x,
                                _cv_y,
                                _cv_click_err,
                            )
                            _cv_entry = {
                                "step_idx": _cv_step_idx,
                                "mark_id": _cv_mark_id,
                                "x": _cv_x,
                                "y": _cv_y,
                                "success": False,
                                "cost_estimate": _cv_cost,
                            }
                    else:
                        # ── T2-c: Diagnostic Routing for mark_id=None ────────────
                        # Vision saw marks but none matched the target.
                        # Instead of silently augmenting the error and proceeding
                        # to HITL, build a structured diagnostic so the planner can
                        # inject a recovery fragment on the next turn:
                        #   "Vision saw N marks; none matched '<target>'. Options:
                        #    (a) open a parent container  (b) scroll  (c) try synonyms"
                        # This prevents the planner from blindly retrying the same
                        # failed get_by_text strategy.
                        _cv_diagnostic = _build_cv_vision_diagnostic(
                            target_text=_target_desc,
                            mark_map=_cv_map,
                        )
                        logger.warning(
                            "[%s] CV_FALLBACK_RESOLUTION_FAILED: mark_id=null for target=%r "
                            "(saw %d marks) — storing cv_vision_diagnostic for planner recovery",
                            run_id,
                            _target_desc[:60],
                            _cv_diagnostic["n_marks"],
                        )
                        _cv_entry = {
                            "step_idx": _cv_step_idx,
                            "mark_id": None,
                            "x": None,
                            "y": None,
                            "success": False,
                            "cost_estimate": _cv_cost,
                            "cv_vision_no_match": True,
                        }
                        # Augment the original error with CV context for HITL
                        _orig_err = result.get("error_message", "")
                        result = {
                            **result,
                            "cv_vision_no_match": True,
                            "error_message": (
                                f"{_orig_err} | CV_FALLBACK_RESOLUTION_FAILED: "
                                f"vision saw {_cv_diagnostic['n_marks']} marks; "
                                f"none matched '{_target_desc[:60]}'. "
                                "Planner will receive diagnostic fragment on next turn."
                            ),
                        }
                        # Store diagnostic in state for the planner to read
                        state = {
                            **state,
                            "cv_vision_diagnostic": _cv_diagnostic,
                        }
                    # Append CV result to state (LangGraph reducer will merge)
                    state = {
                        **state,
                        "cv_fallback_results": [_cv_entry],
                        "cv_fallback_invocations": state.get("cv_fallback_invocations", 0) + 1,
                    }
            except Exception as _cv_err:
                logger.error(
                    "[%s] CV_FALLBACK: unexpected error (non-fatal, continuing): %s",
                    run_id,
                    _cv_err,
                )
        # ── End CV Fallback ───────────────────────────────────────────────

        success: bool = result["success"]
        error_msg: str | None = result.get("error_message")

        if success:
            logger.info("[%s] Step %d succeeded", run_id, step_index)
            # TASK-021: coordinate_action and press_key ALWAYS increment repeat_counts
            # to catch "successful" but unproductive loops (like pressing Escape infinitely).
            if _cb_a in ("coordinate_action", "press_key"):
                new_repeat = repeat_counts.get(_cb_key, 0) + 1
                repeat_counts[_cb_key] = new_repeat
                logger.debug(
                    "[%s] Circuit breaker (Success-Loop): key='%s' fail_count=%d (max=%d)",
                    run_id,
                    _cb_key,
                    new_repeat,
                    _CIRCUIT_BREAKER_MAX,
                )
            else:
                # Fix C: Reset circuit breaker for this key on success.
                # A successful action proves the selector is valid — the prior failure
                # count is stale context and should not carry over to the next retry.
                if _cb_key in repeat_counts:
                    repeat_counts[_cb_key] = 0

            # FEAT-028: Track navigation history ONLY on success
            navigation_history = _update_navigation_history(
                navigation_history, sub_action_type, sub_action.get("value"), actual_url=result.get("actual_url")
            )
        else:
            logger.warning("[%s] Step %d failed: %s", run_id, step_index, error_msg)
            # Fix C: Only increment the circuit breaker counter on failure (success=False).
            # This prevents the breaker from tripping on correct "click, verify, click again"
            # patterns where Playwright succeeds but the verifier returns NOT_YET.
            new_repeat = repeat_counts.get(_cb_key, 0) + 1
            repeat_counts[_cb_key] = new_repeat
            logger.debug(
                "[%s] Circuit breaker: key='%s' fail_count=%d (max=%d)",
                run_id,
                _cb_key,
                new_repeat,
                _CIRCUIT_BREAKER_MAX,
            )

        # ── Capture screenshot for each sub-action ─────────────────────
        screenshot_b64: str = ""
        try:
            raw = await page.screenshot(type="png")
            screenshot_b64 = base64.b64encode(raw).decode()
            final_screenshot_b64 = screenshot_b64
        except Exception as e:
            logger.error("[%s] Failed screenshot for step %d: %s", run_id, step_index, e)

        final_url = result.get("actual_url", final_url)

        # ── Build ExecutionStep ────────────────────────────────────────
        locator_value: str = ""
        strategy = sub_action.get("strategy", "")
        if strategy:
            role = sub_action.get("role", "")
            name = sub_action.get("name", "")
            locator_value = f"{strategy}({role}, name='{name}')" if role else f"{strategy}('{name}')"

        # ── Capture post-action URL and element count (FEAT-062) ────────
        # Used by evaluator to detect amnesic loops.
        _post_url = page.url
        _post_count = 0
        try:
            # Quick count of all DOM elements
            _post_count = await page.evaluate("() => document.querySelectorAll('*').length")
        except Exception:
            pass

        execution_step = ExecutionStep(
            step_index=step_index,
            ac_step_index=state.get("ac_step_index", 0),
            timestamp=timestamp,
            action_type=sub_action_type,
            action_payload=sub_action,
            locator_strategy=strategy,
            locator_value=locator_value,
            data_input=sub_action.get("value"),
            screenshot_url="",
            accessibility_tree_snippet="",
            success=success,
            error_message=error_msg,
            self_heal_attempt=state.get("retry_count", 0),
            llm_reasoning=sub_action.get("reasoning", ""),
            llm_observation=state.get("llm_observation", "") if sub_idx == 0 else "",
            llm_thought=state.get("llm_thought", "") if sub_idx == 0 else "",
            post_url=_post_url,
            post_element_count=_post_count,
        )
        all_steps.append(execution_step)

        # Track transient text (click/press_key only)
        # Accumulate across batch sub-actions with a separator so that context
        # from the FIRST click in a batch is not silently overwritten by later
        # sub-actions. The planner and verifier receive the joined string.
        if sub_action_type in ("click", "press_key"):
            new_transient = result.get("transient_page_text", "")
            if new_transient:
                if final_transient:
                    final_transient = final_transient + "\n---\n" + new_transient
                else:
                    final_transient = new_transient
                logger.info(
                    "[%s] Transient text captured (sub %d, total %d chars): %.120s",
                    run_id,
                    sub_idx,
                    len(final_transient),
                    new_transient.replace("\n", " "),
                )

        # ── Short-circuit on failure ───────────────────────────────────
        if not success:
            final_error = error_msg or ""
            # Mark remaining batch items as skipped
            for skip_idx in range(sub_idx + 1, len(actions_to_run)):
                skipped = actions_to_run[skip_idx]
                all_steps.append(
                    ExecutionStep(
                        step_index=base_step_index + skip_idx,
                        ac_step_index=state.get("ac_step_index", 0),
                        timestamp=timestamp,
                        action_type=skipped.get("action", "unknown"),
                        action_payload=skipped,
                        locator_strategy=skipped.get("strategy", ""),
                        locator_value="",
                        data_input=skipped.get("value"),
                        screenshot_url="",
                        accessibility_tree_snippet="",
                        success=False,
                        error_message=f"SKIPPED: batch short-circuited after step {step_index} failed",
                        self_heal_attempt=state.get("retry_count", 0),
                        llm_reasoning=skipped.get("reasoning", ""),
                        llm_observation="",
                        llm_thought="",
                        post_url=page.url,
                        post_element_count=_post_count,
                    )
                )
            break  # Stop the batch
        else:
            final_error = ""

    # ── Post-action: refresh PageStateTracker ──────────────────────────
    # The tracker inspects the live DOM to produce a deterministic
    # snapshot of view, overlays, sort state, and spinners.  This runs
    # AFTER the action and screenshot, so the planner gets ground-truth
    # on the next iteration (~10-15ms overhead).
    _page_state_snapshot: str = ""
    _tracker = get_tracker(run_id)
    if _tracker and page and not page.is_closed():
        try:
            await _tracker.refresh(page)
            _page_state_snapshot = _tracker.format_for_prompt()
        except Exception as _tracker_err:
            logger.debug(
                "[%s] PageStateTracker refresh failed (non-fatal): %s",
                run_id,
                _tracker_err,
            )

    # ── Assemble final state update ────────────────────────────────────
    update: dict = {
        "detailed_execution_log": all_steps,
        "screenshots": [],
        "current_page_url": final_url,
        "navigation_history": navigation_history,
        "current_screenshot_b64": final_screenshot_b64,
        "last_error": final_error,
        # Always propagate updated circuit breaker state so the next
        # executor invocation on this AC step sees the correct counts.
        "action_repeat_counts": repeat_counts,
        # Increment total action count for this AC step (success + failure).
        # The evaluator uses this as an absolute circuit breaker — if the agent
        # takes too many actions on one step (even if some succeed), it's lost.
        "current_ac_step_action_count": (state.get("current_ac_step_action_count", 0) + len(all_steps)),
        # Deterministic page state snapshot from PageStateTracker.
        # Injected into the planner prompt as <page_state> XML block.
        "page_state_snapshot": _page_state_snapshot,
        "dom_snapshot_before": _dom_snapshot_before,
        "pre_action_state": pre_state,
        # Reset force-wait flags after they have been consumed (TASK-054).
        "_force_wait_before_next_action": False,
        "_force_wait_ms": 0,
    }

    # ── Recipe idempotent-skip fast path ──────────────────────────────
    # When the recipe runner's pre-check determined the target state was already
    # correct (e.g. compact_view_navigate finds div.po-table-wrapper.compact
    # already present), it returns success=True + skipped=True and runs ZERO
    # sub-steps.  The executor signals this to the evaluator so it can advance
    # the AC step directly, bypassing the verifier entirely.
    #
    # Without this signal, the verifier tries to re-confirm the state after
    # the recipe completed — but since no Playwright action was dispatched, the
    # screenshot / DOM reference may be stale, causing spurious NOT_YET loops.
    if (
        len(actions_to_run) == 1
        and actions_to_run[0].get("action") == "recipe"
        and _last_recipe_result.get("skipped", False)
        and _last_recipe_result.get("success", False)
    ):
        logger.info(
            "[%s] Recipe '%s' was an idempotent no-op (state already correct) — "
            "setting _recipe_already_satisfied=True to bypass verifier.",
            run_id,
            actions_to_run[0].get("recipe_name", "?"),
        )
        update["_recipe_already_satisfied"] = True

    # Only propagate transient_page_text if any click/press_key ran
    if any(a.get("action") in ("click", "press_key") for a in actions_to_run):
        update["transient_page_text"] = final_transient

    if is_batch:
        succeeded = sum(1 for s in all_steps if s.success)
        logger.info(
            "[%s] Batch complete: %d/%d actions succeeded",
            run_id,
            succeeded,
            len(all_steps),
        )

    return update


# ---------------------------------------------------------------------------
# CV Vision Diagnostic Helper (FEAT-117 / T2-c)
# ---------------------------------------------------------------------------


def _build_cv_vision_diagnostic(target_text: str, mark_map: dict) -> dict:
    """
    Build a structured diagnostic dict when CV vision returns mark_id=None.

    This diagnostic is stored in the LangGraph state as ``cv_vision_diagnostic``
    so the planner can read it on the next turn and inject a recovery prompt
    fragment via ``_build_cv_diagnostic_fragment``.

    Parameters
    ----------
    target_text : str
        The target description that vision was asked to locate.
    mark_map : dict
        The mark_coordinate_map from CvFallbackResolver.resolve() — may be empty
        if the snapshot failed, or populated (N marks seen, none matched).

    Returns
    -------
    dict with keys:
        target_text  — str, the element vision was looking for
        n_marks      — int, number of marks visible in the annotated screenshot
        options      — list[str], canonical recovery option codes for the planner
    """
    return {
        "target_text": target_text,
        "n_marks": len(mark_map),
        "options": ["open_container", "scroll", "synonyms"],
    }


# ---------------------------------------------------------------------------
# Navigation History Helper
# ---------------------------------------------------------------------------


def _update_navigation_history(
    history: list[str], action_type: str, value: Any = None, actual_url: str | None = None
) -> list[str]:
    """
    Append a navigation-type action to the rolling buffer (capped at 3).

    Navigation actions include 'navigate'.
    If action is 'navigate', we store the actual resulting URL if available,
    otherwise the requested value.
    """
    if action_type not in ["navigate"]:
        return history

    entry = actual_url if action_type == "navigate" and actual_url else value
    if not entry:
        return history

    new_history = list(history) + [str(entry)]
    return new_history[-3:]
