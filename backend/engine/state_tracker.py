"""
vQA — Deterministic Page State Tracker
=======================================
Module: backend/engine/state_tracker.py

Replaces LLM-inferred view/overlay/sort state with programmatic DOM
inspection.  After every executor action, ``refresh(page)`` is called
to produce a ground-truth ``PageState`` snapshot.  The planner receives
this as a ``<page_state>`` block that overrides its visual interpretation.

Architecture Context
--------------------
This module is the core of the Phase 1 hardening roadmap.  It eliminates
two systemic failure classes:

  **Failure Class 1 — Oscillation Loops:**  The LLM planner cannot track
  whether a dropdown is open or closed between planning cycles.  The
  ``open_overlays`` stack tells it definitively, so it never re-clicks
  a trigger that is already open.

  **Failure Class 2 — View-State Desynchronization:**  The LLM cannot
  reliably determine whether the page is in List, Compact, or Minimal
  view from screenshots alone.  ``current_view`` reads the authoritative
  CSS class from the DOM.

Design Decisions
----------------
  - **Multi-version PrimeNG selectors:** All overlay selectors use
    OR-chains (`.p-select-overlay, .p-dropdown-panel`) to handle the
    vSuite PrimeNG v17→v19 migration.  If a selector returns nothing
    in one version, the other branch catches it.

  - **Per-run scoping:** Each ``PageStateTracker`` is instantiated
    alongside a ``BrowserManager`` and keyed by ``run_id``.  Parallel
    test runs never share state.

  - **Lightweight:** ``refresh()`` uses 3-4 ``page.evaluate()`` calls
    totalling <15ms.  No LLM calls, no screenshots, no network traffic.

  - **Network-idle detection is NOT used here.**  vSuite has permanent
    WebSocket heartbeat polling that prevents ``networkidle`` from ever
    firing.  Timing is handled by ``backend/browser/network_sync.py``.

See Also
--------
  - backend/browser/context.py — BrowserManager creates and stores the tracker
  - backend/engine/executor.py — calls refresh() after every action
  - backend/engine/planner.py  — injects <page_state> into system prompt
  - backend/browser/network_sync.py — network-based timing (Phase 4)
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

from playwright.async_api import Page

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Overlay descriptor
# ---------------------------------------------------------------------------


@dataclass
class OverlayInfo:
    """A single open overlay detected in the DOM.

    Attributes
    ----------
    overlay_type : str
        Category: ``"dropdown"``, ``"dialog"``, ``"popover"``, ``"menu"``,
        ``"calendar"``, ``"autocomplete"``, or ``"unknown"``.
    selector : str
        The CSS selector that matched (for downstream scoping).
    option_texts : list[str]
        Visible option/item texts inside the overlay (capped at 20).
        Empty for dialogs/popovers that don't have discrete options.
    """

    overlay_type: str
    selector: str
    option_texts: list[str] = field(default_factory=list)
    is_functional: bool = False


# ---------------------------------------------------------------------------
# Page state snapshot
# ---------------------------------------------------------------------------


@dataclass
class PageState:
    """Immutable snapshot of the page's deterministic UI state.

    This is the single source of truth injected into the planner prompt.
    The LLM is instructed to trust these values over its visual interpretation.

    Attributes
    ----------
    current_view : str
        One of ``"list"``, ``"compact"``, ``"minimal"``, or ``"unknown"``.
        Derived from the CSS class on ``div.po-table-wrapper``.
    open_overlays : list[OverlayInfo]
        Stack of currently visible overlays, most recent last.
    sort_column : str
        Label of the column currently sorted, or ``""`` if none.
    sort_direction : str
        ``"ascending"``, ``"descending"``, or ``"none"``.
    active_tab : str
        Text of the currently selected tab, or ``""`` if no tabs.
    current_url : str
        The page URL at snapshot time.
    is_login_page : bool
        True if the page is on the login route.
    has_spinner : bool
        True if a PrimeNG spinner/loading overlay is visible.
    """

    current_view: str = "unknown"
    open_overlays: list[OverlayInfo] = field(default_factory=list)
    sort_column: str = ""
    sort_direction: str = "none"
    active_tab: str = ""
    current_url: str = ""
    is_login_page: bool = False
    has_spinner: bool = False
    interactive_counts: dict = field(default_factory=dict)
    table_rows: int = 0
    page_heading: str = ""


# ---------------------------------------------------------------------------
# Multi-version PrimeNG overlay selectors
# ---------------------------------------------------------------------------
# Each entry: (CSS selector OR-chain, overlay_type label)
# The OR-chain ensures detection works across PrimeNG v17, v18, and v19.

_OVERLAY_SELECTORS: list[tuple[str, str, bool]] = [
    # PrimeNG dropdown / p-select portals
    (
        ".p-select-overlay:not(.p-connected-overlay-hidden), .p-dropdown-panel:not(.p-connected-overlay-hidden)",
        "dropdown",
        True,
    ),
    # Custom vSuite sorting dropdown panels
    (
        ".po-sorting-dropdown-panel:not(.p-connected-overlay-hidden)",
        "dropdown",
        True,
    ),
    # Sort popover / sort panel (compact view)
    (
        ".sort-panel:not([style*='display: none'])",
        "popover",
        True,
    ),
    # PrimeNG dialog
    (
        ".p-dialog:not(.p-connected-overlay-hidden), p-dialog .p-dialog-content",
        "dialog",
        False,
    ),
    # PrimeNG menu / tieredmenu
    (
        ".p-menu-list:not(.p-connected-overlay-hidden), "
        ".p-menu-overlay:not(.p-connected-overlay-hidden), "
        ".p-tieredmenu:not(.p-connected-overlay-hidden)",
        "menu",
        True,
    ),
    # PrimeNG calendar overlay
    (
        ".p-datepicker-panel:not(.p-connected-overlay-hidden), .p-calendar-panel:not(.p-connected-overlay-hidden)",
        "calendar",
        True,
    ),
    # PrimeNG autocomplete panel
    (
        ".p-autocomplete-panel:not(.p-connected-overlay-hidden), "
        ".p-autocomplete-items:not(.p-connected-overlay-hidden)",
        "autocomplete",
        True,
    ),
    # CDK overlay container with visible backdrop (catch-all for Angular Material overlays)
    (
        ".cdk-overlay-backdrop:not(.cdk-overlay-transparent-backdrop)",
        "dialog",
        False,
    ),
]

# Spinner / loading selectors (to detect blocking states)
_SPINNER_SELECTORS: str = ".p-datatable-loading-overlay, .vcreative-icon.loading, .loading-overlay, .p-blockui"


# ---------------------------------------------------------------------------
# PageStateTracker
# ---------------------------------------------------------------------------


class PageStateTracker:
    """Deterministic page state inspector — one instance per test run.

    Usage::

        tracker = PageStateTracker(run_id="run-abc123")
        state = await tracker.refresh(page)
        print(state.current_view)       # "list"
        print(state.open_overlays)      # [OverlayInfo(type="dropdown", ...)]
        print(state.sort_column)        # "CLIENT"
        print(state.sort_direction)     # "ascending"

    Parameters
    ----------
    run_id : str
        Test run identifier for log correlation.
    """

    def __init__(self, run_id: str) -> None:
        self.run_id: str = run_id
        self._last_state: PageState = PageState()

    @property
    def state(self) -> PageState:
        """Return the most recent page state snapshot (from the last refresh)."""
        return self._last_state

    async def refresh(self, page: Page) -> PageState:
        """Inspect the live DOM and produce a fresh ``PageState`` snapshot.

        This method runs 4 fast ``page.evaluate()`` calls (~10-15ms total):
          1. View detection
          2. Overlay stack scan
          3. Sort state extraction
          4. Active tab + meta state

        All calls are wrapped in try/except so a stale page or transient
        DOM state never crashes the pipeline.

        Parameters
        ----------
        page : Page
            The active Playwright page.

        Returns
        -------
        PageState
            A fresh snapshot.  Also cached in ``self._last_state``.
        """
        ps = PageState()
        ps.current_url = page.url

        # ── 1. View detection ─────────────────────────────────────────
        ps.current_view = await self._detect_view(page)

        # ── 2. Overlay stack scan ─────────────────────────────────────
        ps.open_overlays = await self._detect_overlays(page)

        # ── 3. Sort state ────────────────────────────────────────────
        ps.sort_column, ps.sort_direction = await self._detect_sort(page)

        # ── 4. Active tab + meta state ───────────────────────────────
        ps.active_tab = await self._detect_active_tab(page)
        ps.is_login_page = "/login" in ps.current_url.lower() or "/auth" in ps.current_url.lower()
        ps.has_spinner = await self._detect_spinner(page)

        # ── 5. DOM Structure metrics ──────────────────────────────────
        ps.interactive_counts, ps.table_rows, ps.page_heading = await self._detect_dom_metrics(page)

        self._last_state = ps

        logger.debug(
            "[%s] PageState: view=%s, overlays=%d, sort=%s/%s, tab=%s, spinner=%s",
            self.run_id,
            ps.current_view,
            len(ps.open_overlays),
            ps.sort_column or "(none)",
            ps.sort_direction,
            ps.active_tab or "(none)",
            ps.has_spinner,
        )

        return ps

    # ------------------------------------------------------------------
    # Detection methods
    # ------------------------------------------------------------------

    async def _detect_view(self, page: Page) -> str:
        """Detect the current table view (list/compact/minimal) from DOM classes.

        The vSuite Angular template sets a CSS class on
        ``div.po-table-wrapper``:
          - ``.modern``  → List View
          - ``.compact`` → Compact View
          - ``.minimal`` → Minimal View

        Falls back to heuristic checks (sort-btn presence → compact).
        """
        try:
            view = await page.evaluate("""() => {
                const wrapper = document.querySelector('div.po-table-wrapper');
                if (!wrapper) return 'unknown';
                const cl = wrapper.classList;
                if (cl.contains('compact')) return 'compact';
                if (cl.contains('modern'))  return 'list';
                if (cl.contains('minimal')) return 'minimal';
                return 'unknown';
            }""")
            # Fallback: if wrapper not found, check for sort-btn (compact indicator)
            if view == "unknown":
                sort_btn_visible = await page.locator("button#sort-btn").is_visible()
                if sort_btn_visible:
                    return "compact"
            return view
        except Exception as e:
            logger.debug("[%s] View detection failed: %s", self.run_id, e)
            return "unknown"

    async def _detect_overlays(self, page: Page) -> list[OverlayInfo]:
        """Detect all currently visible PrimeNG overlays.

        For each overlay, extract the visible option/item texts so the
        planner knows what's selectable without re-reading the full a11y tree.
        """
        overlays: list[OverlayInfo] = []
        for selector_chain, overlay_type, is_functional in _OVERLAY_SELECTORS:
            try:
                # Check if any element matching the selector is visible
                locator = page.locator(selector_chain).first
                is_visible = await locator.is_visible(timeout=200)
                if not is_visible:
                    continue

                # Extract option texts inside the overlay (capped at 20)
                option_texts = await page.evaluate(
                    """(sel) => {
                        const el = document.querySelector(sel.split(',')[0].trim());
                        if (!el) return [];
                        const items = el.querySelectorAll(
                            'li, [role="option"], [role="menuitem"], .p-menuitem-text, a'
                        );
                        return Array.from(items)
                            .map(item => item.textContent?.trim() || '')
                            .filter(t => t.length > 0 && t.length < 100)
                            .slice(0, 20);
                    }""",
                    selector_chain.split(",")[0].strip(),
                )

                overlays.append(
                    OverlayInfo(
                        overlay_type=overlay_type,
                        selector=selector_chain.split(",")[0].strip(),
                        option_texts=option_texts or [],
                        is_functional=is_functional,
                    )
                )
                logger.debug(
                    "[%s] Overlay detected: type=%s, selector=%s, options=%d",
                    self.run_id,
                    overlay_type,
                    selector_chain.split(",")[0].strip()[:60],
                    len(option_texts or []),
                )
            except Exception:
                # Timeout or stale element — skip silently
                continue

        return overlays

    async def _detect_sort(self, page: Page) -> tuple[str, str]:
        """Extract the current sort column and direction from ``th[aria-sort]``.

        PrimeNG sets ``aria-sort="ascending"`` or ``aria-sort="descending"``
        on the active column header.  We read the first ``th`` with this
        attribute and extract its visible header text.
        """
        try:
            result = await page.evaluate("""() => {
                // Check for aria-sort on th elements (standard PrimeNG table)
                const sortedTh = document.querySelector('th[aria-sort="ascending"], th[aria-sort="descending"]');
                if (sortedTh) {
                    const direction = sortedTh.getAttribute('aria-sort') || 'none';
                    // Extract visible text, stripping icon spans
                    const textEl = sortedTh.querySelector('.p-column-title, span:not(.pi)');
                    const columnName = textEl
                        ? textEl.textContent.trim()
                        : sortedTh.textContent.trim().split('\\n')[0].trim();
                    return { column: columnName, direction: direction };
                }
                // Compact view: check sort-btn state or active sort indicator
                const sortIndicator = document.querySelector('.sort-arrow, .sort-indicator.active');
                if (sortIndicator) {
                    const panel = sortIndicator.closest('.sort-panel, .sort-option');
                    const label = panel?.querySelector('.sort-label, span')?.textContent?.trim() || '';
                    const isAsc = sortIndicator.classList.contains('asc') ||
                                  sortIndicator.classList.contains('pi-sort-up');
                    return {
                        column: label,
                        direction: isAsc ? 'ascending' : 'descending'
                    };
                }
                return { column: '', direction: 'none' };
            }""")
            return (result.get("column", ""), result.get("direction", "none"))
        except Exception as e:
            logger.debug("[%s] Sort detection failed: %s", self.run_id, e)
            return ("", "none")

    async def _detect_active_tab(self, page: Page) -> str:
        """Detect the currently selected tab from ``[role=tab][aria-selected=true]``."""
        try:
            tab_text = await page.evaluate("""() => {
                const tab = document.querySelector('[role="tab"][aria-selected="true"]');
                return tab ? tab.textContent.trim() : '';
            }""")
            return tab_text or ""
        except Exception:
            return ""

    async def _detect_spinner(self, page: Page) -> bool:
        """Check if any PrimeNG spinner/loading overlay is currently visible."""
        try:
            return await page.evaluate(
                """(sel) => {
                    const spinners = document.querySelectorAll(sel);
                    return Array.from(spinners).some(el => {
                        const style = window.getComputedStyle(el);
                        return style.display !== 'none' && style.visibility !== 'hidden';
                    });
                }""",
                _SPINNER_SELECTORS,
            )
        except Exception:
            return False

    async def _detect_dom_metrics(self, page: Page) -> tuple[dict, int, str]:
        """Extract structural metrics for Proof of Transition."""
        try:
            metrics = await page.evaluate("""() => {
                const heading = document.querySelector('h1, h2, .page-title, .header-title');
                const rows = document.querySelectorAll('tr, .p-datatable-row, .row, .list-item');
                const buttons = document.querySelectorAll('button, [role="button"]');
                const inputs = document.querySelectorAll('input, textarea, select');
                const links = document.querySelectorAll('a, [role="link"]');
                return {
                    interactive_counts: {
                        buttons: buttons.length,
                        inputs: inputs.length,
                        links: links.length
                    },
                    table_rows: rows.length,
                    page_heading: heading ? heading.innerText.trim() : ''
                };
            }""")
            return (
                metrics.get("interactive_counts", {}),
                metrics.get("table_rows", 0),
                metrics.get("page_heading", ""),
            )
        except Exception:
            return ({}, 0, "")

    # ------------------------------------------------------------------
    # Prompt formatting
    # ------------------------------------------------------------------

    def format_for_prompt(self) -> str:
        """Format the current state as a ``<page_state>`` XML block for the planner prompt.

        This block is injected into the system prompt at the highest priority
        position.  The planner is instructed: *"TRUST the <page_state> block
        over your visual interpretation."*

        Returns
        -------
        str
            XML-tagged state block, or empty string if no useful state.
        """
        ps = self._last_state
        if ps.current_view == "unknown" and not ps.open_overlays:
            return ""  # Nothing useful to inject

        lines = ["<page_state>"]

        # View
        lines.append(f"  <view>{ps.current_view}</view>")

        # Sort state
        if ps.sort_column:
            lines.append(f'  <sort column="{ps.sort_column}" direction="{ps.sort_direction}" />')

        # Active tab
        if ps.active_tab:
            lines.append(f"  <active_tab>{ps.active_tab}</active_tab>")

        # Spinner
        if ps.has_spinner:
            lines.append("  <spinner>VISIBLE — wait before acting</spinner>")

        # Overlays (most critical for oscillation prevention)
        if ps.open_overlays:
            lines.append("  <open_overlays>")
            for ov in ps.open_overlays:
                lines.append(f'    <overlay type="{ov.overlay_type}" selector="{ov.selector}">')
                if ov.option_texts:
                    lines.append("      <available_options>")
                    for opt in ov.option_texts[:15]:  # Cap for prompt size
                        lines.append(f"        <option>{opt}</option>")
                    lines.append("      </available_options>")
                lines.append("    </overlay>")
            lines.append("  </open_overlays>")
            # Inject the hard constraint
            lines.append("  ⚠️ AN OVERLAY IS OPEN. You MUST interact with elements INSIDE")
            lines.append("  the overlay or press Escape to close it. DO NOT click the trigger")
            lines.append("  element again — that will CLOSE the overlay and waste an action.")
        else:
            lines.append("  <open_overlays>NONE</open_overlays>")

        lines.append("</page_state>")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Phase 2: Overlay-Aware Action Constraints
    # ------------------------------------------------------------------

    def has_open_overlay(self) -> bool:
        """Return True if any overlay is currently detected as open.

        Used by the executor's pre-action gate to decide whether to
        enforce overlay-scoped interaction.
        """
        return bool(self._last_state.open_overlays)

    def get_overlay_constraint(self) -> dict:
        """Return a constraint dict for the executor's pre-action validation.

        When an overlay is open, the executor should:
          1. Block any action that would click the trigger element again
          2. Scope element resolution to the overlay container
          3. Allow Escape to close the overlay

        Returns
        -------
        dict
            ``{"active": True, "type": "...", "selector": "...", "options": [...]}``
            if an overlay is open, or ``{"active": False}`` if not.
        """
        if not self._last_state.open_overlays:
            return {"active": False}

        # Use the most recently detected overlay (last in the stack)
        top_overlay = self._last_state.open_overlays[-1]
        return {
            "active": True,
            "type": top_overlay.overlay_type,
            "selector": top_overlay.selector,
            "options": top_overlay.option_texts,
            "is_functional": top_overlay.is_functional,
        }

    def is_view(self, target_view: str) -> bool:
        """Check if the page is currently in the specified view.

        Used by the executor's idempotent-skip logic to prevent
        redundant view-switching when the page is already in the
        target state.

        Parameters
        ----------
        target_view : str
            One of ``"list"``, ``"compact"``, ``"minimal"``.
        """
        return self._last_state.current_view == target_view


# ---------------------------------------------------------------------------
# Per-run tracker registry
# ---------------------------------------------------------------------------
# Mirrors the pattern in backend/browser/context.py (_active_managers)

_active_trackers: dict[str, PageStateTracker] = {}


def create_tracker(run_id: str) -> PageStateTracker:
    """Create and register a new PageStateTracker for a test run.

    Called by ``login_node`` alongside ``BrowserManager.start()``.
    """
    tracker = PageStateTracker(run_id=run_id)
    _active_trackers[run_id] = tracker
    logger.debug("Registered PageStateTracker for run '%s'", run_id)
    return tracker


def get_tracker(run_id: str) -> Optional[PageStateTracker]:
    """Retrieve the PageStateTracker for a test run, or None if not found."""
    return _active_trackers.get(run_id)


def remove_tracker(run_id: str) -> None:
    """Remove and discard the PageStateTracker for a completed run."""
    removed = _active_trackers.pop(run_id, None)
    if removed:
        logger.debug("Removed PageStateTracker for run '%s'", run_id)
