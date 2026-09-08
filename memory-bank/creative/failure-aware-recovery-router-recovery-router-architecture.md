# Architecture: Failure-Aware Recovery Router

## Decision
**Chosen**: Option 2 — Standalone Module with Evaluator Gateway
**Rationale**: Maximizes testability (pure functions), respects the existing evaluator routing flow, enables feature-flag gating at a single call site, and keeps the 1400-line evaluator from growing further.

---

## Context

The evaluator (`evaluator.py`, 1403 lines) is already the most complex node in the LangGraph state machine. It handles 15+ routing decisions via a cascade of `if/return` blocks. The recovery router must integrate into the failure path (Case 1: Action FAILED, lines 589–1068) **between** the fast-paths (#0, #0a, #1, #1a, #1b, #2) and the generic retry logic (line ~967).

### Quality Attributes (Priority Order)
1. **Testability** — Recovery logic must be unit-testable with mock state dicts (no Playwright, no LangGraph)
2. **Maintainability** — Must not balloon evaluator.py further; each recovery strategy should be independently modifiable
3. **Safety** — One-shot recovery (no retry loops), feature-flagged, no fail-count increment
4. **Compatibility** — Existing fast-paths, vision-mode escalation, FEAT-020/021 must be untouched

### Integration Points
- **Reads from**: `VQAState` (failure_classifier result, error_msg, planned_action, page_state_snapshot)
- **Writes to**: `VQAState` (recovery_attempted, modified planned_action, agent_critique)
- **Calls into**: `executor.py` (for INTERCEPTED auto-Escape and NOT_VISIBLE parent-reveal clicks)
- **Gated by**: `config.py` feature flags (5 new booleans)

---

## Options Explored

### Option 1: Inline Recovery Logic in Evaluator

Add the recovery dispatch as additional `if/elif` branches directly in the evaluator's Case 1 failure block, between line ~880 (vision-mode auto-escalation) and line ~922 (human_takeover at 5+ failures).

**Component Interaction**:
```
evaluator_node()
  └── Case 1: not success
       ├── fast-path #0, #0a, #1, #1a, #1b, #2 (unchanged)
       ├── NEW: if STRICT_MODE → inline container scoping
       ├── NEW: if TIMEOUT → inline wait + spinner check
       ├── NEW: if NOT_VISIBLE → inline DOM traversal
       ├── NEW: if DETACHED → inline stabilization wait
       ├── NEW: if INTERCEPTED → inline auto-dismiss
       ├── vision-mode auto-escalation (unchanged)
       └── generic retry → planner (unchanged)
```

**Trade-offs**:
- ✅ Zero new files — simple diff
- ✅ Direct access to all state variables
- ❌ Evaluator grows from 1403 → ~1600 lines — already the largest file
- ❌ Recovery logic tangled with routing logic — hard to test in isolation
- ❌ Feature-flag checks scattered across 5 separate branches
- ❌ DOM traversal and Escape-press logic don't belong in evaluator (it's a JUDGE, not an ACTOR)

### Option 2: Standalone Module with Evaluator Gateway (CHOSEN)

Create `backend/engine/recovery_router.py` as a pure module with a single entry point `attempt_recovery(state, error_msg, planned_action) → RecoveryResult | None`. The evaluator calls this function once, at a single well-defined location, and uses the result to either:
- **Recovery succeeded**: Route to planner with modified state (no fail-count increment)
- **Recovery failed/skipped**: Fall through to existing retry logic (fail-count increments normally)

**Component Interaction**:
```
evaluator_node()
  └── Case 1: not success
       ├── fast-path #0, #0a, #1, #1a, #1b, #2 (unchanged)
       ├── safety net (10+ failures) (unchanged)
       │
       ├── NEW GATEWAY (single call site, ~15 lines):
       │    recovery_result = attempt_recovery(state, error_msg, planned_action)
       │    if recovery_result and not state["recovery_attempted"]:
       │        return {
       │            "_next_node": "planner",
       │            "planned_action": recovery_result.modified_action,
       │            "agent_critique": recovery_result.critique,
       │            "recovery_attempted": True,
       │            # NOTE: ac_step_action_fail_count NOT incremented
       │        }
       │
       ├── vision-mode auto-escalation (unchanged)
       ├── human_takeover at 5+ failures (unchanged)
       └── generic retry → planner (unchanged)

recovery_router.py
  ├── attempt_recovery(state, error_msg, planned_action) → RecoveryResult | None
  │    ├── _classify_for_recovery(error_msg) → RecoveryType | None
  │    ├── _recover_strict_mode(state, planned_action) → RecoveryResult
  │    ├── _recover_timeout(state) → RecoveryResult
  │    ├── _recover_not_visible(state, planned_action) → RecoveryResult
  │    ├── _recover_detached(state, planned_action) → RecoveryResult
  │    └── _recover_intercepted(state) → RecoveryResult
  └── RecoveryResult (dataclass)
       ├── recovery_type: str
       ├── modified_action: dict | None
       ├── critique: str
       └── pre_action: dict | None  # Action to execute BEFORE the retry
```

**Trade-offs**:
- ✅ Evaluator grows by only ~15 lines (single gateway call)
- ✅ Recovery logic is fully unit-testable with mock state dicts
- ✅ Feature-flag gating centralized in `attempt_recovery()` entry point
- ✅ Each recovery handler is an independent function — easy to add/modify/disable
- ✅ Clean separation: evaluator JUDGES, recovery_router RECOVERS
- ✅ `RecoveryResult` dataclass makes the contract explicit and type-safe
- ❌ New file to maintain (but it's focused and cohesive)
- ❌ Need to pass state + error_msg through the function boundary

### Option 3: Recovery as a Separate LangGraph Node

Add a `recovery_node` between the evaluator and planner in the graph. The evaluator routes to `recovery_node` instead of `planner` when a recoverable failure is detected. The recovery node performs the auto-fix and then routes to planner.

**Component Interaction**:
```
graph.py:
  evaluator → recovery_node → planner  (new edge)
  evaluator → planner                  (existing edge, for non-recoverable failures)

recovery_node(state) → dict:
  # Reads error_msg, planned_action from state
  # Performs recovery action (modify planned_action, press Escape, etc.)
  # Returns modified state
```

**Trade-offs**:
- ✅ Clean graph-level separation
- ✅ Recovery node can access the Page directly (it's a full LangGraph node)
- ❌ Adds a new node to the graph — increases graph complexity
- ❌ Requires new conditional edges in graph.py
- ❌ State transitions are more complex (evaluator must set routing hints)
- ❌ Recovery is a micro-step, not a full "think" phase — overkill for a node
- ❌ The one-shot gate (`recovery_attempted`) is harder to enforce across graph cycles
- ❌ Testing requires LangGraph test harness, not simple unit tests

---

## Evaluation Matrix

| Criteria | Weight | Option 1 (Inline) | Option 2 (Module) | Option 3 (Node) |
|----------|--------|-------------------|-------------------|-----------------|
| Fits existing patterns | High | 7/10 | **9/10** | 5/10 |
| Maintainability | High | 4/10 | **9/10** | 7/10 |
| Testability | High | 5/10 | **10/10** | 6/10 |
| Performance | Medium | 10/10 | **9/10** | 7/10 |
| Implementation effort | Medium | 8/10 | **7/10** | 4/10 |
| Safety (one-shot gate) | High | 6/10 | **9/10** | 5/10 |
| **Weighted Total** | | **6.2** | **8.9** | **5.6** |

---

## Component Design (Option 2)

### New Files

#### `backend/engine/recovery_router.py`
```python
"""
vQA — Failure-Aware Recovery Router (FEAT-022)
===============================================
Attempts type-specific automatic recovery before the evaluator
falls through to the generic retry pipeline.

Recovery is ONE-SHOT per AC step: if the auto-fix fails, the normal
retry → escalation pipeline handles it. Recovery does NOT consume
from the retry budget (it's a free attempt).

Each recovery strategy is individually feature-flagged in config.py.
"""

from dataclasses import dataclass
from enum import Enum

class RecoveryType(str, Enum):
    STRICT_MODE = "STRICT_MODE"
    TIMEOUT = "TIMEOUT"
    NOT_VISIBLE = "NOT_VISIBLE"
    DETACHED = "DETACHED"
    INTERCEPTED = "INTERCEPTED"

@dataclass
class RecoveryResult:
    recovery_type: RecoveryType
    modified_action: dict | None     # Modified planned_action for retry
    critique: str                     # Agent critique explaining recovery
    pre_action: dict | None = None   # Action to execute BEFORE the retry
                                      # (e.g. press Escape for INTERCEPTED)
    recovery_log: dict | None = None # Telemetry entry for failure diary

def attempt_recovery(
    state: dict,
    error_msg: str,
    planned_action: dict,
) -> RecoveryResult | None:
    """
    Single entry point called by evaluator_node.
    
    Returns RecoveryResult if a recovery strategy applies,
    or None if no recovery is possible (fall through to normal retry).
    """
    ...
```

### Modified Files

#### `backend/config.py` — 5 new feature flags
```python
# Recovery Router Feature Flags (FEAT-022)
recovery_strict_mode_enabled: bool = True
recovery_timeout_enabled: bool = True
recovery_not_visible_enabled: bool = True
recovery_detached_enabled: bool = True
recovery_intercepted_enabled: bool = True
```

#### `backend/engine/state.py` — 2 new fields
```python
# Recovery Router (FEAT-022)
recovery_attempted: bool  # One-shot gate per AC step
recovery_action_log: list[dict]  # Telemetry for recovery actions
```

#### `backend/engine/evaluator.py` — Gateway insertion (~15 lines)
Insert between the safety net (10+ failures) and vision-mode auto-escalation:
```python
# ── FEAT-022: Recovery Router — one-shot type-specific auto-fix ────
if not state.get("recovery_attempted", False):
    from backend.engine.recovery_router import attempt_recovery
    _recovery = attempt_recovery(state, error_msg, planned_action)
    if _recovery is not None:
        logger.info(
            "[%s] RECOVERY ROUTER: %s auto-fix applied for AC step %d",
            run_id, _recovery.recovery_type.value, ac_index + 1,
        )
        _recovery_diary = dict(diary_entry)
        _recovery_diary["recovery_attempted"] = _recovery.recovery_type.value
        _recovery_diary["recovery_critique"] = _recovery.critique
        existing_diary[-1] = _recovery_diary  # Update last entry
        return {
            "_next_node": "planner",
            "recovery_attempted": True,
            "planned_action": _recovery.modified_action or planned_action,
            "agent_critique": _recovery.critique,
            "last_error": error_msg,
            "ac_step_fail_counts": fail_counts,
            # NOTE: ac_step_action_fail_count NOT incremented (free attempt)
            "long_term_memory": new_memories,
            "bug_log": rbac_violations,
            "ac_step_failure_diary": existing_diary,
        }
```

#### `backend/engine/reporter.py` — Recovery telemetry display
Add a "Recovery Actions" column to the step timeline in the HTML report.

### Data Flow Diagram

```
Action FAILS
    │
    ▼
evaluator_node (Case 1: not success)
    │
    ├── Fast-paths (#0, #0a, #1, #1a, #1b, #2) → return early
    │
    ├── Safety net (10+ failures) → reporter
    │
    ├── ★ RECOVERY GATEWAY ★ (new, ~15 lines)
    │   │
    │   ├── recovery_attempted == True? → SKIP (fall through)
    │   │
    │   └── attempt_recovery(state, error_msg, planned_action)
    │       │
    │       ├── _classify_for_recovery(error_msg)
    │       │   └── Maps to RecoveryType or None
    │       │
    │       ├── Feature flag check (config.recovery_X_enabled)
    │       │   └── Disabled? → return None (fall through)
    │       │
    │       ├── Strategy dispatch:
    │       │   ├── STRICT_MODE → _recover_strict_mode()
    │       │   ├── TIMEOUT    → _recover_timeout()
    │       │   ├── NOT_VISIBLE → _recover_not_visible()
    │       │   ├── DETACHED   → _recover_detached()
    │       │   └── INTERCEPTED → _recover_intercepted()
    │       │
    │       └── RecoveryResult
    │           ├── modified_action (patched planned_action)
    │           ├── critique (agent_critique for planner)
    │           ├── pre_action (browser action before retry)
    │           └── recovery_log (telemetry entry)
    │
    │   Recovery applied? → return to planner (NO fail-count increment)
    │   Recovery skipped?  → fall through ▼
    │
    ├── Vision-mode auto-escalation (unchanged)
    │
    ├── Human takeover at 5+ failures (unchanged)
    │
    └── Generic retry → planner (unchanged, fail-count increments)
```

### Reset Points

`recovery_attempted` must be reset to `False` at these points (same as other per-step counters):
- AC step advances (evaluator: `ac_step_index` changes)
- `done` action accepted
- Role changes (setup_role_node)
- Recipe idempotent-skip

This follows the existing pattern used by `ac_step_action_fail_count`, `ac_step_fail_counts`, etc.

### Pre-Action Execution

For INTERCEPTED and NOT_VISIBLE recovery, the router returns a `pre_action` dict that the evaluator must execute on the browser BEFORE routing back to the planner. However, the evaluator is a JUDGE node — it should NOT execute browser actions.

**Resolution**: The `pre_action` is included in the `modified_action` returned to the planner. The planner sees a critique like "RECOVERY: Press Escape to dismiss overlay, then retry click on 'Submit'" and the modified action is `{"action": "press_key", "value": "Escape"}`. This keeps the evaluator pure (no browser calls) while still achieving the auto-fix.

For DETACHED recovery: The modified action wraps the original action with a wait prefix: `{"action": "wait", "value": 500}`. The planner executes the wait, then re-plans the original action.

For STRICT_MODE: The modified action is the original action with `container_selector` injected.

For TIMEOUT: The modified action is `{"action": "wait", "value": 3000}` with a critique telling the planner to check for spinners.
