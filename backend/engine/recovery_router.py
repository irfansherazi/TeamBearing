"""
vQA — Failure-Aware Recovery Router (FEAT-022)
===============================================
Attempts type-specific automatic recovery before the evaluator
falls through to the generic retry pipeline.

Recovery is ONE-SHOT per AC step: if the auto-fix fails, the normal
retry → escalation pipeline handles it. Recovery does NOT consume
from the retry budget (it's a free attempt).

Each recovery strategy is individually feature-flagged in config.py.

Phase 3 addition (accessibility-tree-grounding):
  - RecoveryType.A11Y_AMBIGUOUS — triggered when the a11y resolver returned
    N>1 matches and the CSS fallback also failed. Feature-flagged off by
    default (settings.recovery_a11y_ambiguous_enabled = False).
"""

import logging
import re
import unicodedata
from dataclasses import dataclass
from enum import Enum
from typing import Any
from urllib.parse import urlparse

from backend.config import settings

logger = logging.getLogger(__name__)


class RecoveryType(str, Enum):
    """Supported recovery categories mapped from Playwright errors."""

    STRICT_MODE = "STRICT_MODE"
    TIMEOUT = "TIMEOUT"
    NOT_VISIBLE = "NOT_VISIBLE"
    DETACHED = "DETACHED"
    INTERCEPTED = "INTERCEPTED"
    A11Y_AMBIGUOUS = "A11Y_AMBIGUOUS"  # Phase 3: a11y resolver returned N>1 matches


# ---------------------------------------------------------------------------
# A11Y_AMBIGUOUS: allowed disambiguator attribute whitelist
# ---------------------------------------------------------------------------

_ALLOWED_DISAMBIGUATOR_ATTRS = frozenset({
    "aria-label",
    "aria-labelledby",
    "aria-describedby",
    "placeholder",
    "title",
    "data-testid",
})


@dataclass
class RecoveryResult:
    """Contract between recovery router and evaluator."""

    recovery_type: RecoveryType
    modified_action: dict[str, Any] | None  # Modified planned_action for retry
    critique: str  # Agent critique explaining recovery
    pre_action: dict[str, Any] | None = None  # Action to execute BEFORE the retry
    recovery_log: dict[str, Any] | None = None  # Telemetry entry for failure diary


def attempt_recovery(
    state: dict[str, Any],
    error_msg: str,
    planned_action: dict[str, Any],
) -> RecoveryResult | None:
    """
    Single entry point called by evaluator_node.

    Returns RecoveryResult if a recovery strategy applies and is enabled,
    or None if no recovery is possible (fall through to normal retry).
    """
    # 0. Guard / Backward Compatibility: check already attempted recovery types (AC-2, AC-4)
    raw_types = state.get("recovery_attempted_types")
    if isinstance(raw_types, list):
        attempted_types = set(raw_types)
    elif isinstance(raw_types, set):
        attempted_types = raw_types
    else:
        attempted_types = set()

    if state.get("recovery_attempted", False):
        attempted_types = {t.value for t in RecoveryType}

    # 1. Classify the error for recovery
    recovery_type = _classify_for_recovery(error_msg, state)
    if not recovery_type:
        return None

    if recovery_type.value in attempted_types or recovery_type in attempted_types:
        logger.debug("Recovery for %s already attempted, skipping.", recovery_type.value)
        return None

    # 2. Check feature flags
    if not _is_recovery_enabled(recovery_type):
        logger.debug("Recovery for %s is disabled via feature flag.", recovery_type.value)
        return None

    # 3. Dispatch to specific recovery handler
    if recovery_type == RecoveryType.STRICT_MODE:
        return _recover_strict_mode(state, planned_action)
    elif recovery_type == RecoveryType.TIMEOUT:
        return _recover_timeout(state, planned_action)
    elif recovery_type == RecoveryType.NOT_VISIBLE:
        return _recover_not_visible(state, planned_action)
    elif recovery_type == RecoveryType.DETACHED:
        return _recover_detached(state, planned_action)
    elif recovery_type == RecoveryType.INTERCEPTED:
        return _recover_intercepted(state, planned_action)
    elif recovery_type == RecoveryType.A11Y_AMBIGUOUS:
        return _recover_a11y_ambiguous(state, planned_action)

    return None


def _classify_for_recovery(
    error_msg: str,
    state: dict[str, Any] | None = None,
) -> RecoveryType | None:
    """Map raw Playwright error substrings to RecoveryType.

    Phase 3: when ``settings.recovery_a11y_ambiguous_enabled`` is True,
    checks ``state["last_resolution_path"]`` for the ``"selector_fallback_ambiguous"``
    marker before falling back to the standard STRICT_MODE classifier.
    A11Y_AMBIGUOUS outranks STRICT_MODE when the ambiguity came from the a11y
    resolver — per Algorithm Decision 2 (accessibility-tree-grounding).
    """
    e = error_msg.lower()

    # A11Y_AMBIGUOUS wins over STRICT_MODE when the flag is on and the
    # resolution path recorded a a11y-ambiguous outcome.
    if settings.recovery_a11y_ambiguous_enabled and state is not None:
        last_path = state.get("last_resolution_path", "")
        if last_path == "selector_fallback_ambiguous":
            if "strict mode violation" in e or "timeout" in e:
                return RecoveryType.A11Y_AMBIGUOUS

    if "strict mode violation" in e:
        return RecoveryType.STRICT_MODE
    if "timeout" in e:
        return RecoveryType.TIMEOUT
    if "not visible" in e or "hidden" in e or "dom_hidden" in e:
        return RecoveryType.NOT_VISIBLE
    if "detach" in e:
        return RecoveryType.DETACHED
    if "intercept" in e or "blocked" in e or "another element" in e:
        return RecoveryType.INTERCEPTED
    return None


def _is_recovery_enabled(recovery_type: RecoveryType) -> bool:
    """Check the corresponding feature flag in Settings."""
    if recovery_type == RecoveryType.STRICT_MODE:
        return settings.recovery_strict_mode_enabled
    if recovery_type == RecoveryType.TIMEOUT:
        return settings.recovery_timeout_enabled
    if recovery_type == RecoveryType.NOT_VISIBLE:
        return settings.recovery_not_visible_enabled
    if recovery_type == RecoveryType.DETACHED:
        return settings.recovery_detached_enabled
    if recovery_type == RecoveryType.INTERCEPTED:
        return settings.recovery_intercepted_enabled
    if recovery_type == RecoveryType.A11Y_AMBIGUOUS:
        return settings.recovery_a11y_ambiguous_enabled
    return False


# ═══════════════════════════════════════════════════════════════════════════
# Recovery Handlers
# ═══════════════════════════════════════════════════════════════════════════


def _recover_strict_mode(state: dict, planned_action: dict) -> RecoveryResult | None:
    """
    STRICT_MODE: Auto-inject container_selector from DOM context to disambiguate.

    If the action already has a container_selector, we can't double-scope,
    so we return None to fall through to normal retry.

    Bug E fix: Also extract the 'aka get_by_role(...)' hint from the error
    message (sourced from state["last_error"]) and prepend it to the critique
    so the planner sees Playwright's recommended locator even when recovery fires.

    Combobox-filter guard: when the target looks like a dropdown filter input
    (name starts with "Select "/"Choose "/etc.), the search input lives in a
    portal overlay rather than the chrome that produced the trigger — a
    heuristic container guess (e.g. `.p-toolbar`) will always miss. Fall
    through so the evaluator/planner picks a different strategy.
    """
    if planned_action.get("container_selector"):
        return None

    if _looks_like_combobox_filter(planned_action):
        return None

    snapshot = state.get("page_state_snapshot", "")
    container = _infer_container(snapshot, planned_action)
    if container is None:
        return None

    # Bug E fix: extract aka get_by_role hint if present in last_error
    _aka_hint = ""
    try:
        from backend.engine.evaluator import _extract_aka_hint as _eah

        _raw_err = state.get("last_error", "") or ""
        _hint = _eah(_raw_err)
        if _hint:
            _aka_hint = f"{_hint}\n\n"
    except Exception:
        pass  # Non-critical — never block recovery for hint extraction failure

    modified = dict(planned_action)
    modified["container_selector"] = container

    return RecoveryResult(
        recovery_type=RecoveryType.STRICT_MODE,
        modified_action=modified,
        critique=(
            f"{_aka_hint}"
            f"RECOVERY: STRICT_MODE violation — locator matched multiple elements. "
            f"Auto-injected container_selector '{container}' to disambiguate. "
            "Retrying with scoped locator."
        ),
        recovery_log={
            "recovery_type": "STRICT_MODE",
            "container_injected": container,
        },
    )


_COMBOBOX_FILTER_PREFIXES = ("select ", "choose ", "search ", "filter ", "pick ")
_BUTTON_LIKE_ACTIONS = {"click", "press", "tap"}


def _looks_like_combobox_filter(planned_action: dict) -> bool:
    """
    True when the target looks like a dropdown/combobox filter input.

    These inputs (e.g. PrimeNG p-select filter, Select2 search) are typically
    rendered into a floating overlay/portal, so scoping to the chrome that
    hosts the trigger (`.p-toolbar`, `.detail-panel`, ...) misses the input.
    """
    name = str(planned_action.get("name") or "").strip().lower()
    role = str(planned_action.get("role") or "").strip().lower()
    strategy = str(planned_action.get("strategy") or "").strip().lower()

    if role in ("combobox", "listbox", "searchbox"):
        return True
    if strategy == "get_by_placeholder":
        return True
    if name.endswith("...") and any(name.startswith(p) for p in _COMBOBOX_FILTER_PREFIXES):
        return True
    return False


def _infer_container(snapshot: str, planned_action: dict) -> str | None:
    """
    Heuristic to determine the best container_selector based on vSuite patterns.

    Returns ``None`` when no confident guess is available so the caller falls
    through to normal retry instead of injecting a wrong container.
    """
    name = str(planned_action.get("name", "")).lower()
    action = str(planned_action.get("action", "")).lower()
    snapshot_lower = snapshot.lower()

    # 1. Sort options belong in the sort panel
    sort_keywords = ["sort", "order", "alphabetical", "date", "priority"]
    if any(k in name for k in sort_keywords):
        return ".sort-panel"

    # 2. If a floating dropdown overlay is open, prefer it — the target is
    #    almost certainly an option or filter inside the overlay panel.
    overlay_candidates = (
        (".p-select-overlay", "p-select-overlay"),
        (".p-dropdown-panel", "p-dropdown-panel"),
        (".p-multiselect-panel", "p-multiselect-panel"),
        (".p-overlaypanel", "p-overlaypanel"),
        (".p-autocomplete-panel", "p-autocomplete-panel"),
        (".select2-drop", "select2-drop"),
        (".select2-results", "select2-results"),
    )
    for sel, marker in overlay_candidates:
        if marker in snapshot_lower:
            return sel

    # 3. If a dialog is active, scope to it (excluding the generic word
    #    "overlay" which fires above for panels).
    if "p-dialog" in snapshot_lower or "dialog" in snapshot_lower:
        return ".p-dialog-content"

    # 4. If a sidebar is present, scope to the detail panel
    if "sidebar" in snapshot_lower or "detail" in snapshot_lower:
        return ".detail-panel"

    # 5. Toolbar fallback — only for button-shaped clicks, never for fills.
    #    Every PrimeNG app has a top toolbar; scoping to it for inputs almost
    #    always misses the real target (portal-rendered).
    is_button_like = action in _BUTTON_LIKE_ACTIONS or action == ""
    if is_button_like and (
        "p-toolbar" in snapshot_lower or "toolbar" in snapshot_lower
    ):
        return ".p-toolbar"

    # 6. Generic panel fallback for button-like actions only. Inputs/combobox
    #    filters render into portal overlays; injecting `.p-panel` for a fill
    #    would just move the strict-mode failure into a container timeout.
    if is_button_like:
        return ".p-panel"

    return None


def _recover_detached(state: dict, planned_action: dict) -> RecoveryResult | None:
    """
    DETACHED: Element removed from DOM during Angular re-render.
    Strategy: Wait 500ms for DOM stabilization, then retry same action.
    """
    return RecoveryResult(
        recovery_type=RecoveryType.DETACHED,
        modified_action={"action": "wait", "value": 500},
        critique=(
            "RECOVERY: DETACHED — element was removed from DOM during Angular re-render. "
            "Waiting 500ms for DOM to stabilize. After wait, retry the EXACT SAME action "
            "— the element should be re-rendered by then."
        ),
        recovery_log={
            "recovery_type": "DETACHED",
            "wait_ms": 500,
        },
    )


def _recover_timeout(state: dict, planned_action: dict) -> RecoveryResult | None:
    """
    TIMEOUT: Element not found or still loading.
    Strategy: Wait 3s and check for spinner presence.
    """
    return RecoveryResult(
        recovery_type=RecoveryType.TIMEOUT,
        modified_action={"action": "wait", "value": 3000},
        critique=(
            "RECOVERY: TIMEOUT — waiting 3s for page stabilization. "
            "Check for .p-progress-spinner or app-loading before retrying "
            "the original action. If a spinner is present, wait for it to "
            "disappear before proceeding."
        ),
        recovery_log={
            "recovery_type": "TIMEOUT",
            "wait_ms": 3000,
        },
    )


def _recover_not_visible(state: dict, planned_action: dict) -> RecoveryResult | None:
    """
    NOT_VISIBLE: Element exists in DOM but is hidden (e.g. inside a closed tab).
    Strategy: Identify and open the nearest parent container (max depth 3).
    """
    snapshot = state.get("page_state_snapshot", "")
    name = planned_action.get("name", "")

    parent_target = _find_openable_parent(snapshot, name)
    if not parent_target:
        return None

    return RecoveryResult(
        recovery_type=RecoveryType.NOT_VISIBLE,
        modified_action={
            "action": "click",
            "strategy": "css_selector",
            "selector": parent_target,
            "name": parent_target,
            "reasoning": f"RECOVERY: Opening parent container to reveal '{name}'.",
        },
        critique=(
            f"RECOVERY: NOT_VISIBLE — '{name}' is in the DOM but hidden. "
            f"Auto-clicking parent container '{parent_target}' to reveal it. "
            "After this click, retry the original action."
        ),
        recovery_log={
            "recovery_type": "NOT_VISIBLE",
            "parent_target": parent_target,
        },
    )


def _find_openable_parent(snapshot: str, element_name: str) -> str | None:
    """
    Search for known PrimeNG openable container patterns in the snapshot.
    """
    # Known PrimeNG openable container patterns and their headers
    OPENABLE_MAP = {
        "p-accordion": "p-accordion-header",
        "p-accordiontab": "p-accordion-header",
        "p-tabview": "p-tabview-nav-link",
        "p-tabpanel": "p-tabview-nav-link",
        "p-sidebar": ".p-sidebar-header",
        "p-panel": ".p-panel-header",
        "p-fieldset": ".p-fieldset-legend",
        "expandable-section": ".header",
        "collapsible": ".title",
    }

    snapshot_lower = snapshot.lower()
    for pattern, header_class in OPENABLE_MAP.items():
        if pattern in snapshot_lower:
            # We return a CSS selector that targets the header/toggle of the container
            return f"{pattern} .{header_class}, {pattern} {header_class}"

    return None


def _recover_intercepted(state: dict, planned_action: dict) -> RecoveryResult | None:
    """
    INTERCEPTED: Overlay/modal blocking the click target.
    Strategy: Auto-press Escape to dismiss the overlay.
    """
    return RecoveryResult(
        recovery_type=RecoveryType.INTERCEPTED,
        modified_action={
            "action": "press_key",
            "value": "Escape",
            "reasoning": "RECOVERY: Pressing Escape to dismiss overlay blocking the target.",
        },
        critique=(
            "RECOVERY: INTERCEPTED — an overlay/modal is blocking the click target. "
            "Auto-pressed Escape to dismiss it. Retrying original action."
        ),
        recovery_log={
            "recovery_type": "INTERCEPTED",
            "dismiss_method": "Escape",
        },
    )


# ═══════════════════════════════════════════════════════════════════════════
# A11Y_AMBIGUOUS Recovery Handler (Phase 3 — accessibility-tree-grounding)
# ═══════════════════════════════════════════════════════════════════════════


def _normalize_name_for_fingerprint(name: str) -> str:
    """
    Lightweight normalisation for the Failure Diary fingerprint.

    NFC, case-fold, strip leading/trailing whitespace.  Does NOT strip
    icon characters — the fingerprint must be stable across the two
    resolver tiers (exact and normalised) because both log the same
    ``(role, name)`` pair.
    """
    try:
        return unicodedata.normalize("NFC", name).casefold().strip()
    except Exception:
        return name.strip()


def _locator_fingerprint(state: dict[str, Any], planned_action: dict[str, Any]) -> str:
    """
    Stable Failure Diary fingerprint for an (a11y-role, name, page-scope) triple.

    Scoped to host + path prefix — query and fragment change per step and
    would defeat the retry cap.  NOT persisted across runs; the diary lives
    in VQAState for one run only (same semantics as recovery_attempted_types).
    """
    role = (planned_action.get("role") or planned_action.get("_aria_role") or "").lower().strip()
    name = _normalize_name_for_fingerprint(
        planned_action.get("name") or planned_action.get("_aria_name") or ""
    )
    url = state.get("current_url") or ""
    try:
        p = urlparse(url)
        scope = f"{p.hostname or ''}{p.path or ''}"
    except Exception:
        scope = ""
    return f"a11y_ambig::{role}::{name}::{scope}"


def _recover_a11y_ambiguous(
    state: dict[str, Any],
    planned_action: dict[str, Any],
) -> RecoveryResult | None:
    """
    A11Y_AMBIGUOUS: a11y resolver returned N>1 matches AND CSS fallback failed.

    Strategy (Algorithm Decision 2 — hybrid disambiguator cascade):

    1. Check the Failure Diary cap.  If this fingerprint has already been
       attempted >= settings.a11y_ambiguous_max_retries times, return None
       (cede to normal retry pipeline).

    2. If ``aria_disambiguators`` is populated with known-good attributes,
       build a ``container_selector`` from them and inject it into the
       modified action (reusing the existing STRICT_MODE scope injection
       at executor.py:546-547).

    3. Otherwise (no disambiguators), return None — STRICT_MODE recovery
       takes over on the next evaluator cycle (same behavior as today).

    Feature-flagged: returns None immediately when
    ``settings.recovery_a11y_ambiguous_enabled`` is False (enforced in
    ``attempt_recovery`` before this function is called).
    """
    # 1. Failure Diary cap
    fingerprint = _locator_fingerprint(state, planned_action)
    diary: dict[str, int] = state.get("locator_failure_diary") or {}
    retry_count = diary.get(fingerprint, 0)
    max_retries = settings.a11y_ambiguous_max_retries
    if retry_count >= max_retries:
        logger.debug(
            "A11Y_AMBIGUOUS: fingerprint %r capped at %d/%d retries — ceding to normal retry.",
            fingerprint,
            retry_count,
            max_retries,
        )
        return None

    # 2. Build container_selector from aria_disambiguators
    disambiguators: list[str] = planned_action.get("_aria_disambiguators") or []
    container_selector = _build_container_from_disambiguators(disambiguators)

    if not container_selector:
        # No usable disambiguators — cede to STRICT_MODE recovery
        logger.debug(
            "A11Y_AMBIGUOUS: no usable aria_disambiguators — ceding to STRICT_MODE recovery."
        )
        return None

    # 3. Increment Failure Diary (write back into mutable state dict)
    updated_diary = dict(diary)
    updated_diary[fingerprint] = retry_count + 1
    state["locator_failure_diary"] = updated_diary

    modified = dict(planned_action)
    modified["container_selector"] = container_selector

    logger.info(
        "A11Y_AMBIGUOUS: injecting container_selector=%r for fingerprint %r (attempt %d/%d).",
        container_selector,
        fingerprint,
        retry_count + 1,
        max_retries,
    )

    return RecoveryResult(
        recovery_type=RecoveryType.A11Y_AMBIGUOUS,
        modified_action=modified,
        critique=(
            f"RECOVERY: A11Y_AMBIGUOUS — a11y resolver matched multiple elements. "
            f"Injecting container_selector='{container_selector}' from aria_disambiguators "
            f"to scope the locator. Retrying with narrowed scope "
            f"(attempt {retry_count + 1}/{max_retries})."
        ),
        recovery_log={
            "recovery_type": "A11Y_AMBIGUOUS",
            "container_selector": container_selector,
            "fingerprint": fingerprint,
            "retry_attempt": retry_count + 1,
        },
    )


def _build_container_from_disambiguators(disambiguators: list[str]) -> str:
    """
    Build a CSS attribute selector from ``aria_disambiguators`` entries.

    Entries may be bare attribute names (``"aria-label"``) or
    ``attr:value`` pairs (``"aria-label:Save button"``).

    Only attributes in ``_ALLOWED_DISAMBIGUATOR_ATTRS`` are accepted;
    unknown entries are silently skipped (security guard — prevent
    arbitrary CSS injection via malformed disambiguator values).

    Returns an empty string if no valid entries are found.
    """
    parts: list[str] = []
    for entry in disambiguators:
        entry = entry.strip()
        if ":" in entry:
            attr, _, value = entry.partition(":")
            attr = attr.strip()
            value = value.strip()
            if attr in _ALLOWED_DISAMBIGUATOR_ATTRS and value:
                # Escape any double-quotes in value to prevent CSS injection
                safe_value = value.replace('"', '\\"')
                parts.append(f'[{attr}="{safe_value}"]')
        else:
            if entry in _ALLOWED_DISAMBIGUATOR_ATTRS:
                parts.append(f"[{entry}]")

    return ", ".join(parts) if parts else ""
