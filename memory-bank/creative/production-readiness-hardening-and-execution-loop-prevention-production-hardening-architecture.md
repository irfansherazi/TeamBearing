# Architecture Decision: Production Readiness Hardening — 4-Pillar Integration

**Created**: 2026-05-31T19:34:00Z
**Status**: DECIDED
**Decision Type**: Architecture
**Task**: production-readiness-hardening-and-execution-loop-prevention / FEAT-062

---

## Context

### System Requirements

production-readiness-hardening-and-execution-loop-prevention introduces four independent reliability pillars into the existing LangGraph execution engine:

1. **Pillar 1 — Amnesic Loop Circuit Breaker**: Detect and interrupt agent loops where actions succeed mechanically but produce zero semantic progress (URL + DOM element count unchanged across N consecutive actions).
2. **Pillar 2 — Visual Delta CV Verification**: Augment the existing `cv_fallback_state_change_check` with screenshot pixel-diff as a fourth verification signal, catching canvas/SPA targets where DOM is unchanged but rendering changed.
3. **Pillar 3 — Human Takeover Broadcast Signature Fix**: Add `novnc_url` parameter to `_broadcast_human_takeover` in `routes.py` to match the call-site in `human_takeover.py`.
4. **Pillar 4 — Playwright Lifecycle Idempotency**: Suppress `WriteUnixTransport closed=True` teardown errors; add `is_connected()` guard before `browser.close()`.

### Technical Constraints

- **Zero new dependencies** — Pillow/PIL is already a transitive dependency; no new packages.
- **Non-breaking** — All changes must be backward-compatible (existing call-sites that don't pass `novnc_url` continue to work).
- **Fail-open** — All new detection logic must degrade gracefully when data is unavailable (e.g., PIL import error → skip visual delta; element count unavailable → non-stagnant).
- **LangGraph state mutation discipline** — New state fields must be added to `VQAState` and `make_initial_state`, and must use non-list overwrite semantics (not `operator.add` reducers).
- **Existing guiding principles**: Failure Diary Pattern, Programmatic Tier 1 Verification, HITL as Learning Signal.

### Non-Functional Requirements

- **Reliability**: Amnesic loop must fire ≥ 95% of stagnation events; zero false-positives on legitimate slow SPA loads.
- **Correctness**: Human takeover broadcast zero `TypeError` crashes.
- **Safety**: Zero orphaned Playwright processes or video leaks on shutdown.
- **Testability**: All 4 pillars independently unit-testable with `unittest.mock`.

---

## Component Analysis

### Core Components Affected

| Component | File | Pillar | Change Type |
|-----------|------|--------|-------------|
| `VQAState` | `backend/engine/state.py` | P1 | New state fields |
| `evaluator_node` | `backend/engine/evaluator.py` | P1 | Stagnation detection + routing |
| `_dispatch_action` | `backend/engine/executor.py` | P1, P2 | Post-action capture; pre-screenshot |
| `cv_fallback_state_change_check` | `backend/engine/verifier.py` | P2 | 4th signal (visual delta) |
| `_broadcast_human_takeover` | `backend/api/routes.py` | P3 | Signature fix |
| `human_takeover_node` | `backend/engine/human_takeover.py` | P3 | Docstring only |
| `BrowserManager.close()` | `backend/browser/context.py` | P4 | Suppress keyword + is_connected guard |

### Component Interaction Diagram (Pillar 1 — Amnesic Loop)

```
executor_node
    │  succeeds (success=True)
    │  captures: step["post_url"], step["post_element_count"]
    ▼
evaluator_node
    │  calls _detect_amnesic_loop(state, latest_step)
    │  reads: _prev_page_state_snapshot from state
    │  compares: post_url vs snapshot.url, post_element_count vs snapshot.element_count
    ├─ stagnant=False → amnesic_loop_count reset to 0 → normal routing
    └─ stagnant=True  → amnesic_loop_count += 1
          └─ count >= 3 → route to human_takeover_node
                          set awaiting_human_takeover=True
                          inject agent_critique explaining the loop
```

### Component Interaction Diagram (Pillar 2 — Visual Delta)

```
executor_node._dispatch_action()
    │  (CV fallback path, before page.mouse.click)
    │  pre_screenshot_b64 = await capture_screenshot_b64(run_id)
    ▼
    page.mouse.click(x, y)  ← coordinate-based click
    ▼
cv_fallback_state_change_check(..., pre_screenshot_b64=pre_screenshot_b64)
    │  Signal 1: URL changed?         → True
    │  Signal 2: ARIA tree changed?   → True
    │  Signal 3: Element count delta? → True
    │  Signal 4 (NEW): pixel diff?    → True (if ratio >= 0.5%)
    └─ Any True → success=True (CV click counted as success)
```

---

## Options Explored

### Option 1: Inline Integration (Chosen)

**Description**: All four pillars are implemented directly in-place within their respective existing nodes/modules. No new LangGraph nodes, no new Python modules for pillars 1-4 (tests are new files; implementation is in-place modifications).

**Architecture**:
```
Existing Graph:      [planner] → [executor] → [evaluator] → [verifier] → [human_takeover]
Modified Graph:      [planner] → [executor*] → [evaluator*] → [verifier*] → [human_takeover*]
                                                   ↑ P1 added                ↑ P3 fixed
                                    ↑ P1+P2 captures          ↑ P2 added
                     [browser.close*] ← P4 fixed (context.py)
```

**Pros**:
- Zero LangGraph topology changes — existing routing graph unchanged
- Minimal surface area — each change is surgical (no file touches adjacent to it)
- Backward compatible by construction — new params have defaults
- Independently testable — each pillar tested via its own test file with `unittest.mock`
- No import chain disruption — no new modules imported by existing nodes

**Cons**:
- Evaluator grows slightly longer (stagnation check block adds ~35 lines)
- State snapshot (`_prev_page_state_snapshot`) is passed through every state update even when not stagnant

**Technical Fit**: High — aligns with existing Inline Sub-Agent Fallback Rule and Failure Diary Pattern
**Complexity**: Low — in-place modifications only
**Scalability**: High — O(1) per evaluation cycle; snapshot is a 2-field dict

---

### Option 2: New `StagnationMonitor` Service Class

**Description**: Extract stagnation detection into a standalone `StagnationMonitor` service class in `backend/engine/stagnation_monitor.py`, instantiated per run and passed into evaluator.

**Pros**:
- Clean SRP — stagnation logic fully isolated
- Easier to extend (e.g., add more stagnation signals: timing, scroll depth)

**Cons**:
- Adds a new module + dependency injection pattern not used elsewhere in evaluator
- Counter state would still need to be in `VQAState` (cross-iteration state); service class adds no state benefit
- Inconsistent with existing inline pattern (Failure Classifier, Circuit Breaker are both inline in evaluator)

**Technical Fit**: Medium — new pattern breaks consistency with existing evaluator style
**Complexity**: Medium
**Scalability**: High (same as Option 1)

---

### Option 3: New `StagnationGuard` LangGraph Node

**Description**: Add a new `stagnation_guard_node` between `executor_node` and `evaluator_node` that checks for stagnation and routes to `human_takeover` directly.

**Pros**:
- Topologically clean — concern fully separated from evaluator

**Cons**:
- Changes LangGraph topology — risks breaking graph routing tests
- Adds overhead to every action cycle (new node invocation even for non-stagnant actions)
- Visual delta (Pillar 2) still needs to be in executor's CV path — creates split concern
- Human takeover broadcast fix (Pillar 3) still needs to be in routes.py regardless

**Technical Fit**: Low — topology change contradicts constraint "no new LangGraph nodes"
**Complexity**: High
**Scalability**: High

---

## Evaluation Matrix

| Criteria | Option 1 (Inline) | Option 2 (Service Class) | Option 3 (New Node) |
|----------|-------------------|--------------------------|---------------------|
| Scalability | ✅ High | ✅ High | ✅ High |
| Maintainability | ✅ High | ✅ High | ⚠️ Medium |
| Performance | ✅ O(1)/cycle | ✅ O(1)/cycle | ⚠️ Overhead/cycle |
| Backward Compat | ✅ Full | ✅ Full | ⚠️ Topology risk |
| Testability | ✅ Independent | ✅ Independent | ⚠️ Graph integration needed |
| Consistency | ✅ Matches existing | ⚠️ New pattern | ❌ Breaks existing |
| Implementation Cost | ✅ Low | ⚠️ Medium | ❌ High |

---

## Observability Architecture

### Logging Strategy

All four pillars emit structured log lines using the existing `logger` instance (standard Python logging, output via `backend/utils/logging.py`):

**Pillar 1 — Amnesic Loop**:
```python
# Per-cycle (non-stagnant):
logger.debug("[%s] Stagnation check: url_changed=%s, element_delta=%d", run_id, ...)
# On trip:
logger.error("[%s] AMNESIC LOOP detected: %d consecutive stagnant actions on AC step %d", run_id, count, ac_index+1)
```

**Pillar 2 — Visual Delta**:
```python
logger.info("CV_FALLBACK_STATE_CHANGE: Visual delta detected — screenshot pixel diff (%.2f%% pixels changed)", ratio*100)
logger.debug("CV_FALLBACK_STATE_CHECK: Visual delta check failed: %s", err)
```

**Pillar 3 — Human Takeover**:
```python
# No new log lines; existing WS broadcast logging unchanged
```

**Pillar 4 — Browser Lifecycle**:
```python
logger.warning("[%s] Browser already disconnected — skipping browser.close()", run_id)
logger.debug("[%s] Teardown: suppressed %s error (keyword match: %s)", run_id, err_type, matched_kw)
```

### Metrics
- No new metrics exported — pillars are reliability improvements, not new features requiring dashboards
- Human takeover events are already tracked in `knowledge/human_guidance.md` (HITL as Learning Signal)

---

## Decision

**Chosen**: Option 1 — Inline Integration

### Rationale

Option 1 is the only choice that satisfies all four constraints simultaneously:
1. **Zero topology change** — existing LangGraph graph routing is untouched
2. **Fail-open** — inline conditionals degrade gracefully when data is unavailable
3. **Non-breaking** — default parameter values preserve all existing call-sites
4. **Consistent** — matches the established pattern of inline circuit breakers in `evaluator.py` (see `action_repeat_counts` breaker, `ac_step_action_fail_count` breaker)

The evaluator growing by ~35 lines is acceptable given that all existing circuit breaker logic (Goal Satisfiable Check, Identical-Action Breaker, AC-Level Breaker) lives in the same node. production-readiness-hardening-and-execution-loop-prevention Pillar 1 is the semantic evolution of those existing breakers.

### Trade-offs Accepted

| Trade-off | Mitigation |
|-----------|------------|
| `_prev_page_state_snapshot` dict is carried in state even on non-stagnant cycles | Dict is 2 fields (url string, element_count int); negligible memory footprint |
| Evaluator is longer | Stagnation block is clearly delimited with comments; each helper function is independently testable |
| PIL import can fail silently | Fail-open: log a warning and skip Signal 4 (existing behavior preserved) |

---

## Implementation Guidelines

1. **Pillar ordering for implementation**: Implement P3 first (smallest change, immediate crash fix), then P4 (suppress + guard), then P1 (state + evaluator + executor capture), then P2 (visual delta in verifier + pre-screenshot in executor).
2. **State field naming convention**: Prefix private snapshot fields with `_` (e.g., `_prev_page_state_snapshot`) per existing convention (`_next_node`).
3. **Threshold constant**: `_AMNESIC_LOOP_THRESHOLD = 3` — module-level constant, not a config/env var (too low-level for operator tuning). Document in docstring.
4. **Visual delta threshold**: `0.005` (0.5%) — provides noise floor rejection while catching real SPA renders. Caller-overridable via parameter.
5. **Teardown keyword list**: All keywords lowercase for case-insensitive comparison. Document each keyword's origin.
6. **All new helper functions**: Pure functions (no side effects) where possible — enables unit testing without mocking state.

---

## Validation Checklist

- [x] Meets all system requirements (4 pillars, backward-compatible, fail-open)
- [x] Respects technical constraints (no new dependencies, no topology changes)
- [x] Addresses non-functional requirements (≥95% detection, zero crash, zero leaks)
- [x] Technically feasible with current constraints
- [x] Risks identified and mitigations documented
- [x] Complies with Guiding Principles: Failure Diary Pattern, Programmatic Tier 1 Verification, HITL as Learning Signal
- [x] Respects established patterns in systemPatterns.md (Inline Circuit Breaker pattern)
- [x] Observability: structured log lines at appropriate levels
- [x] All pillars independently unit-testable via unittest.mock

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Amnesic loop fires on legitimate slow SPA load | Medium | Medium — unnecessary HITL | Threshold=3, only fires on URL+DOM both unchanged; reset on AC advance |
| PIL unavailable in some environments | Low | Low — Signal 4 skipped | Fail-open with warning log |
| `is_connected()` sync/async behavior | Low | Low — try/except wraps it | Fall through to existing close logic |
| WriteUnixTransport keyword too broad | Very Low | Low | Keyword is distinctive; test with real error messages in unit test |
| Pixel diff threshold too sensitive (noise) | Medium | Medium — false CV successes | 0.5% threshold provides ~120k pixel margin in 1080p; tested via unit test |

---

## Next Steps

1. Write failing RED tests for all 4 pillars (16 tests across 4 test files)
2. Implement P3 (routes.py signature fix — 1 line change)
3. Implement P4 (context.py teardown keyword + is_connected guard)
4. Implement P1 (state.py fields → evaluator.py detection → executor.py post-capture)
5. Implement P2 (verifier.py visual delta → executor.py pre-screenshot)
6. Run full test suite; code review
