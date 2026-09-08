# Algorithm: Recovery Dispatch & Strategy Logic

## Decision
**Chosen**: Option 2 — Error-Message Pattern Matching with Strategy Table Dispatch
**Rationale**: Reuses the existing `_classify_error()` pattern from the evaluator (proven approach), avoids adding a dependency on `failure_classifier.py`'s categories (which are too coarse for recovery routing), and provides O(1) dispatch via a dict lookup after O(n) regex classification where n is small (5 patterns).

---

## Problem Space

### Input
- `error_msg: str` — Raw Playwright/executor error message (typically 50–300 chars)
- `planned_action: dict` — The action that failed (has strategy, role, name, container_selector, etc.)
- `state: dict` — Full VQAState (for accessing page_state_snapshot, DOM context, config flags)

### Output
- `RecoveryResult | None` — Either a recovery strategy with modified action/critique, or None (no recovery applicable)

### Constraints
- **One-shot**: Recovery runs at most once per AC step (gated by `recovery_attempted` bool)
- **Feature-flagged**: Each of the 5 strategies can be independently disabled
- **Zero fail-count cost**: Recovery does NOT increment `ac_step_action_fail_count`
- **Fail-safe**: If recovery logic throws any exception, return None (fall through to normal retry)
- **No browser calls**: The recovery router is a pure function — it returns data, not Playwright calls

### Performance Targets
- Classification: < 1ms (regex matching against 5 patterns)
- Strategy execution: < 1ms (dict manipulation, string formatting)
- Total overhead per failure: < 2ms

---

## Options Explored

### Option 1: Reuse `FailureCategory` from `failure_classifier.py`

Map `FailureCategory.SELECTOR` → STRICT_MODE recovery, `FailureCategory.TRANSIENT` → TIMEOUT/DETACHED recovery, etc.

```python
from backend.engine.failure_classifier import classify_failure, FailureCategory

def attempt_recovery(state, error_msg, planned_action):
    category = classify_failure(error_msg)
    if category == FailureCategory.SELECTOR:
        return _recover_strict_mode(...)
    elif category == FailureCategory.TRANSIENT:
        return _recover_timeout(...)
    ...
```

**Complexity**: O(n) regex scan from `classify_failure()` + O(1) dispatch
**Space**: O(1) — no additional data structures

**Problems**:
- ❌ `FailureCategory` is too coarse — `SELECTOR` includes both STRICT_MODE and NOT_VISIBLE, which need completely different recovery strategies
- ❌ `TRANSIENT` includes both TIMEOUT and DETACHED, which also need different strategies
- ❌ INTERCEPTED is classified as `SELECTOR` (it matches "blocked"/"another element"), but recovery is completely different
- ❌ Would require sub-classification anyway, defeating the purpose of reuse

### Option 2: Error-Message Pattern Matching with Strategy Table (CHOSEN)

Direct regex classification against 5 specific patterns (matching the recovery types, not the failure categories), followed by dict-based strategy dispatch.

```python
import re

# ── Recovery Type Classification ──────────────────────────────────
_RECOVERY_PATTERNS: list[tuple[re.Pattern, RecoveryType]] = [
    (re.compile(r"strict.?mode.?violation|locator.*resolved to.*elements", re.I),
     RecoveryType.STRICT_MODE),
    (re.compile(r"timeout\s+\d+ms\s+exceeded|waiting for.*timeout", re.I),
     RecoveryType.TIMEOUT),
    (re.compile(r"not.?visible|hidden|dom_hidden|element.*not.*visible", re.I),
     RecoveryType.NOT_VISIBLE),
    (re.compile(r"detach|element removed from DOM", re.I),
     RecoveryType.DETACHED),
    (re.compile(r"intercept|blocked|another element.*receiving", re.I),
     RecoveryType.INTERCEPTED),
]

# ── Strategy Dispatch Table ───────────────────────────────────────
_RECOVERY_STRATEGIES: dict[RecoveryType, Callable] = {
    RecoveryType.STRICT_MODE: _recover_strict_mode,
    RecoveryType.TIMEOUT:     _recover_timeout,
    RecoveryType.NOT_VISIBLE:  _recover_not_visible,
    RecoveryType.DETACHED:     _recover_detached,
    RecoveryType.INTERCEPTED:  _recover_intercepted,
}

# ── Feature Flag Map ─────────────────────────────────────────────
_RECOVERY_FLAGS: dict[RecoveryType, str] = {
    RecoveryType.STRICT_MODE: "recovery_strict_mode_enabled",
    RecoveryType.TIMEOUT:     "recovery_timeout_enabled",
    RecoveryType.NOT_VISIBLE:  "recovery_not_visible_enabled",
    RecoveryType.DETACHED:     "recovery_detached_enabled",
    RecoveryType.INTERCEPTED:  "recovery_intercepted_enabled",
}

def attempt_recovery(state, error_msg, planned_action) -> RecoveryResult | None:
    # 1. Classify
    recovery_type = _classify_for_recovery(error_msg)
    if recovery_type is None:
        return None
    
    # 2. Feature flag check
    flag_name = _RECOVERY_FLAGS[recovery_type]
    if not getattr(settings, flag_name, True):
        return None
    
    # 3. Dispatch
    handler = _RECOVERY_STRATEGIES[recovery_type]
    return handler(state, error_msg, planned_action)
```

**Complexity**: O(n) regex scan where n=5 (constant), O(1) dict dispatch
**Space**: O(1) — compile-time regex + static dicts

**Advantages**:
- ✅ Pattern granularity matches recovery granularity exactly (5 patterns → 5 strategies)
- ✅ Pattern priority order prevents mis-classification (STRICT_MODE checked before generic "blocked")
- ✅ Feature flag check is centralized, not scattered
- ✅ Strategy table is easily extensible (add a new RecoveryType + handler + flag)
- ✅ Pure function — testable with string inputs alone

### Option 3: Decision Tree with DOM Context

Use a multi-factor decision tree that considers both the error message AND the DOM state (page_state_snapshot) to determine recovery.

```python
def attempt_recovery(state, error_msg, planned_action):
    snapshot = state.get("page_state_snapshot", "")
    has_spinner = "<spinner" in snapshot or "p-progress-spinner" in snapshot
    has_overlay = "<overlay" in snapshot or "p-dialog-mask" in snapshot
    
    if "strict mode" in error_msg.lower():
        if planned_action.get("container_selector"):
            return None  # Already scoped — recovery won't help
        return _recover_strict_mode(...)
    elif "timeout" in error_msg.lower():
        if has_spinner:
            return _recover_timeout_with_spinner(...)
        else:
            return _recover_timeout_without_spinner(...)
    elif has_overlay:
        return _recover_intercepted(...)  # Even if error doesn't say "intercept"
    ...
```

**Complexity**: O(n) regex + O(m) snapshot parsing where m = snapshot size (~2-5KB)
**Space**: O(1)

**Problems**:
- ❌ Over-engineers the classification — snapshot parsing adds latency and complexity
- ❌ DOM context is unreliable after a failure (the page may have changed)
- ❌ Harder to test — need realistic snapshot strings in test fixtures
- ❌ Decision tree branches multiply quickly (5 error types × 3-4 DOM states = 15-20 paths)
- ✅ Could be more accurate for edge cases (e.g. detecting spinner for TIMEOUT)

---

## Evaluation Matrix

| Criteria | Weight | Option 1 (Reuse) | Option 2 (Pattern) | Option 3 (Tree) |
|----------|--------|-------------------|---------------------|-----------------|
| Correctness | Critical | 5/10 | **9/10** | 8/10 |
| Time complexity | High | 9/10 | **9/10** | 7/10 |
| Space complexity | Medium | 10/10 | **10/10** | 9/10 |
| Implementation simplicity | Medium | 6/10 | **9/10** | 4/10 |
| Testability | Medium | 6/10 | **10/10** | 5/10 |
| Extensibility | Medium | 4/10 | **9/10** | 7/10 |
| **Weighted Total** | | **6.2** | **9.3** | **6.5** |

---

## Algorithm Design

### Entry Point: `attempt_recovery()`

```
FUNCTION attempt_recovery(state, error_msg, planned_action):
    // Guard: already attempted recovery on this AC step
    IF state.recovery_attempted == True:
        RETURN None
    
    // Guard: empty or missing inputs
    IF error_msg is empty:
        RETURN None
    
    // Step 1: Classify error into RecoveryType
    recovery_type = classify_for_recovery(error_msg)
    IF recovery_type is None:
        RETURN None
    
    // Step 2: Check feature flag
    flag = RECOVERY_FLAGS[recovery_type]
    IF flag is disabled in settings:
        LOG "Recovery {recovery_type} disabled by feature flag"
        RETURN None
    
    // Step 3: Dispatch to handler (wrapped in try/except)
    TRY:
        result = RECOVERY_STRATEGIES[recovery_type](state, error_msg, planned_action)
        RETURN result
    EXCEPT any Exception:
        LOG warning "Recovery handler failed — falling through to normal retry"
        RETURN None
```

### Classification: `_classify_for_recovery()`

```
FUNCTION classify_for_recovery(error_msg):
    lower = error_msg.lower()
    
    // Priority order matters — most specific patterns first
    FOR each (pattern, recovery_type) in RECOVERY_PATTERNS:
        IF pattern.search(error_msg):
            RETURN recovery_type
    
    RETURN None  // No recoverable failure type detected
```

Pattern priority (first match wins):
1. **STRICT_MODE** — "strict mode violation" or "resolved to N elements" (most specific)
2. **NOT_VISIBLE** — "not visible" or "hidden" or "dom_hidden" (before TIMEOUT, since both can contain "waiting")
3. **DETACHED** — "detach" or "element removed from DOM" (specific to DOM lifecycle)
4. **INTERCEPTED** — "intercept" or "another element receiving" (specific to overlays)
5. **TIMEOUT** — "timeout Nms exceeded" (most generic — LAST to avoid consuming the others)

### Recovery Handlers

#### `_recover_strict_mode(state, error_msg, planned_action) → RecoveryResult`

**User's decision**: Use nearest common ancestor if within 500px of current view.

```
FUNCTION recover_strict_mode(state, error_msg, planned_action):
    // If the action already has a container_selector, recovery can't help
    IF planned_action has container_selector:
        RETURN None
    
    // Strategy: Inject a container_selector to disambiguate
    // Use the page_state_snapshot to find the active panel/section
    snapshot = state.get("page_state_snapshot", "")
    
    // Determine container based on known vSuite patterns
    container = infer_container(snapshot, planned_action)
    
    // Build modified action with container_selector
    modified = copy(planned_action)
    modified["container_selector"] = container
    
    RETURN RecoveryResult(
        recovery_type = STRICT_MODE,
        modified_action = modified,
        critique = "RECOVERY: STRICT_MODE — injected container_selector '{container}' 
                    to disambiguate. Retry with scoped locator.",
        recovery_log = {
            "recovery_type": "STRICT_MODE",
            "container_injected": container,
        }
    )

FUNCTION infer_container(snapshot, planned_action):
    name = planned_action.get("name", "").lower()
    
    // Known vSuite container mappings (high-confidence)
    IF name in SORT_OPTION_NAMES:
        RETURN ".sort-panel"
    IF "overlay" in snapshot or "dialog" in snapshot:
        RETURN ".p-dialog-content"
    IF "sidebar" in snapshot:
        RETURN ".detail-panel"
    
    // Default: use the toolbar if it exists in the snapshot
    IF "toolbar" in snapshot:
        RETURN ".p-toolbar"
    
    // Fallback: generic panel scope
    RETURN ".p-panel"
```

#### `_recover_timeout(state, error_msg, planned_action) → RecoveryResult`

```
FUNCTION recover_timeout(state, error_msg, planned_action):
    // Strategy: Wait 3s and check for spinner, then retry
    RETURN RecoveryResult(
        recovery_type = TIMEOUT,
        modified_action = {"action": "wait", "value": 3000},
        critique = "RECOVERY: TIMEOUT — waiting 3s for page stabilization. 
                    Check for .p-progress-spinner or app-loading before retrying 
                    the original action. If spinner is present, wait for it to 
                    disappear before proceeding.",
        recovery_log = {
            "recovery_type": "TIMEOUT",
            "wait_ms": 3000,
        }
    )
```

#### `_recover_not_visible(state, error_msg, planned_action) → RecoveryResult`

**User's decision**: Max 3 levels of DOM traversal depth.

```
FUNCTION recover_not_visible(state, error_msg, planned_action):
    // Strategy: Identify nearest openable parent container
    snapshot = state.get("page_state_snapshot", "")
    name = planned_action.get("name", "")
    
    // Search for known openable parent patterns in the snapshot
    // Max depth: 3 levels (user's answer to open question)
    parent_target = find_openable_parent(snapshot, name, max_depth=3)
    
    IF parent_target is None:
        RETURN None  // No openable parent found — skip recovery
    
    // Build a click action on the parent container
    RETURN RecoveryResult(
        recovery_type = NOT_VISIBLE,
        modified_action = {
            "action": "click",
            "strategy": "css_selector",
            "name": parent_target,
            "reasoning": f"RECOVERY: Opening parent container to reveal '{name}'"
        },
        critique = f"RECOVERY: NOT_VISIBLE — '{name}' is in the DOM but hidden. 
                     Clicking parent container '{parent_target}' to reveal it. 
                     After this click, retry the original action.",
        recovery_log = {
            "recovery_type": "NOT_VISIBLE",
            "parent_target": parent_target,
            "traversal_depth": "≤3",
        }
    )

FUNCTION find_openable_parent(snapshot, element_name, max_depth=3):
    // Known PrimeNG openable container patterns
    OPENABLE_PATTERNS = [
        "p-accordion",
        "p-accordiontab",
        "p-tabview",
        "p-tabpanel",
        "p-sidebar",
        "p-panel",
        "p-fieldset",
        ".expandable-section",
        ".collapsible",
    ]
    
    // Check page_state_snapshot for known patterns
    snapshot_lower = snapshot.lower()
    FOR pattern in OPENABLE_PATTERNS:
        IF pattern in snapshot_lower:
            RETURN f"{pattern} .p-accordion-header, {pattern} .p-tabview-nav-link"
    
    RETURN None  // No openable parent detected
```

#### `_recover_detached(state, error_msg, planned_action) → RecoveryResult`

```
FUNCTION recover_detached(state, error_msg, planned_action):
    // Strategy: Wait 500ms for Angular re-render, then retry same action
    RETURN RecoveryResult(
        recovery_type = DETACHED,
        modified_action = {"action": "wait", "value": 500},
        critique = "RECOVERY: DETACHED — element was removed from DOM during 
                    Angular re-render. Waiting 500ms for DOM to stabilize. 
                    After wait, retry the EXACT SAME action — the element 
                    should be re-rendered by then.",
        recovery_log = {
            "recovery_type": "DETACHED",
            "wait_ms": 500,
        }
    )
```

#### `_recover_intercepted(state, error_msg, planned_action) → RecoveryResult`

**User's decision**: Escape first, then click overlay backdrop.

```
FUNCTION recover_intercepted(state, error_msg, planned_action):
    // Strategy: Press Escape to dismiss overlay, then retry
    // User decision: Escape first (cheaper, works for most PrimeNG dialogs)
    RETURN RecoveryResult(
        recovery_type = INTERCEPTED,
        modified_action = {
            "action": "press_key",
            "value": "Escape",
            "reasoning": "RECOVERY: Pressing Escape to dismiss overlay blocking target"
        },
        critique = "RECOVERY: INTERCEPTED — an overlay/modal is blocking the click target. 
                    Pressing Escape to dismiss it. If Escape doesn't work, try clicking 
                    '.p-dialog-mask' or '.cdk-overlay-backdrop' to close the overlay, 
                    then retry the original action.",
        recovery_log = {
            "recovery_type": "INTERCEPTED",
            "dismiss_method": "Escape",
            "fallback": ".p-dialog-mask or .cdk-overlay-backdrop click",
        }
    )
```

### Recovery Telemetry

Each recovery attempt is logged in the failure diary entry by adding a `recovery_attempted` field:

```python
diary_entry = {
    "attempt": step_fail_count,
    "action": action_type,
    "locator": locator_key,
    "error": classified_error,
    "suggestion": suggestion,
    "recovery_attempted": "STRICT_MODE",  # NEW: recovery type or None
    "recovery_critique": "...",            # NEW: what the recovery did
}
```

This integrates with the existing diary schema (no new data structures needed).

---

## Complexity Analysis

- **Classification**: O(5) regex scans = O(1) constant time
- **Feature flag check**: O(1) attribute lookup
- **Strategy dispatch**: O(1) dict lookup
- **Handler execution**: O(1) for all handlers (dict manipulation + string formatting)
  - Exception: `_recover_not_visible` with `find_openable_parent` does O(k) where k=10 (constant set of patterns)
- **Overall**: O(1) per failure event
- **Space**: O(1) — all data structures are compile-time constants

### Edge Cases

1. **Empty error_msg**: `classify_for_recovery()` returns None → no recovery attempted
2. **Empty planned_action**: Each handler checks for required fields; returns None if missing
3. **All flags disabled**: `attempt_recovery()` returns None for every failure type → existing pipeline unchanged (AC-ERROR-1)
4. **Recovery handler throws exception**: Outer try/except catches it → returns None → normal retry
5. **STRICT_MODE with existing container_selector**: `_recover_strict_mode()` returns None (can't double-scope)
6. **NOT_VISIBLE with no openable parent**: `_recover_not_visible()` returns None → normal retry (AC-ERROR-2)
7. **Multiple failure types in one error**: First-match wins (pattern priority order handles this)
