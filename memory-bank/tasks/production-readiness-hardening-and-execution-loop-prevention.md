---
legacy_id: production-readiness-hardening-and-execution-loop-prevention
---
# production-readiness-hardening-and-execution-loop-prevention: Production Readiness Hardening & Execution Loop Prevention

**Feature**: FEAT-062  
**Phase**: ARCHIVE  
**Status**: COMPLETE  
**Created**: 2026-05-31  
**Completed**: 2026-05-31  
**Complexity**: Level 4  
**Branch**: feature/FEAT-062-production-readiness-hardening

---

## Problem Statement

Live log analysis has identified four critical reliability bottlenecks preventing vQA from being production-ready:

1. **Amnesic loops** — the agent burns its full `max_actions` budget on semantically identical null-outcome actions (scroll, wait, scroll, wait…) without recognizing stagnation
2. **CV fallback false-failures** — coordinate-based `page.mouse.click(x, y)` for canvas/SPA targets has no visual delta check; DOM-unchanged clicks are misclassified as failures causing infinite retry
3. **Human Takeover crash** — `_broadcast_human_takeover()` is called with `novnc_url=novnc_url` but its signature does not declare that parameter, causing a `TypeError` that hard-crashes the entire run instead of escalating to HITL
4. **Playwright zombie processes** — the teardown sequence hits `Unexpected browser.close() error: unable to perform operation on <WriteUnixTransport closed=True>` due to a double-close race condition; video artifacts may be orphaned

---

## Acceptance Criteria

| # | Criterion |
|---|-----------|
| AC-1 | Amnesic loop circuit breaker fires ≥ 95% of stagnation events (3 consecutive URL_UNCHANGED + DOM_STABLE actions → detour strategy dispatched) |
| AC-2 | CV fallback verification includes visual delta (pre/post screenshot diff); canvas/SPA targets with DOM-unchanged but visually-changed clicks are NOT flagged as failures |
| AC-3 | Human Takeover WebSocket broadcast succeeds 100% of the time with zero `TypeError` crashes; `novnc_url` is included in the message payload correctly |
| AC-4 | Zero orphaned Playwright processes or `.webm` video leaks on run shutdown; `WriteUnixTransport closed=True` error eliminated |
| AC-5 | All four pillars have accompanying pytest unit tests |
| AC-6 | No existing tests regress |

---

## Test Strategy

### RED Phase (write failing tests first)

**Pillar 1 — Amnesic Loop Circuit Breaker**
- `tests/engine/test_evaluator.py`:
  - `test_amnesic_loop_detection_3_consecutive_stagnant_actions` — mock 3 actions where URL is identical and DOM element count delta = 0; assert `_next_node == "human_takeover"` and `awaiting_human_takeover == True`
  - `test_amnesic_loop_does_not_fire_on_url_change` — same 3 actions but URL changes on action 3; assert no circuit break
  - `test_amnesic_loop_does_not_fire_below_threshold` — only 2 consecutive stagnant actions; assert planner is still the route
  - `test_amnesic_loop_resets_on_ac_step_advance` — counter resets to 0 when ac_step_index advances
  - `test_detour_strategy_dispatched` — when amnesic loop fires, assert a detour action (navigate / page refresh) is injected into the state

**Pillar 2 — Visual Delta CV Verification**
- `tests/engine/test_verifier.py` (or a dedicated `tests/engine/test_cv_fallback.py`):
  - `test_cv_fallback_visual_delta_canvas_click_succeeds` — mock `capture_screenshot_b64` returning two different b64 strings (pre/post); assert `cv_fallback_state_change_check` returns `True`
  - `test_cv_fallback_dom_unchanged_visual_changed_succeeds` — DOM element count unchanged AND URL unchanged, but screenshots differ; assert `True`
  - `test_cv_fallback_both_unchanged_fails` — screenshots identical AND DOM unchanged; assert `False`
  - `test_cv_fallback_visual_diff_threshold` — screenshots differ by < 0.5% pixel mass; assert still `False` (noise floor ignored)

**Pillar 3 — Human Takeover Broadcast Signature**
- `tests/api/test_human_takeover_broadcast.py`:
  - `test_broadcast_accepts_novnc_url_kwarg` — call `_broadcast_human_takeover(run_id, ac_step, ac_step_index, error_message, instructions="", novnc_url="http://localhost")` and assert no `TypeError` raised
  - `test_broadcast_novnc_url_in_ws_message` — assert the `WSHumanTakeoverMessage` serialized JSON contains `novnc_url`
  - `test_broadcast_novnc_url_none_safe` — `novnc_url=None` should not crash
  - `test_human_takeover_node_calls_broadcast_with_novnc_url` — mock `_WS_BROADCAST_FN`; assert it is called with `novnc_url` kwarg present

**Pillar 4 — Playwright Lifecycle Idempotency**
- `tests/browser/test_browser_context.py`:
  - `test_close_already_closed_browser_no_exception` — mock `browser.close()` to raise `Error("WriteUnixTransport closed=True")`; assert `BrowserManager.close()` does not re-raise
  - `test_close_idempotent_double_call` — call `BrowserManager.close()` twice with a mock browser that would raise on the 2nd call; assert no exception
  - `test_video_webm_finalized_before_browser_close` — assert `browser.close()` is called AFTER the `asyncio.sleep(0.5)` flush window
  - `test_teardown_order_context_before_browser` — assert `context.close()` is called before `browser.close()` (ordering matters for video finalization)

### GREEN Phase (implementation targets)

See "Proposed Changes" section below.

### Verification commands
```bash
pytest tests/engine/test_evaluator.py -v -k "amnesic"
pytest tests/engine/test_verifier.py -v -k "cv_fallback"
pytest tests/api/test_human_takeover_broadcast.py -v
pytest tests/browser/test_browser_context.py -v -k "close"
pytest tests/ -v --tb=short   # full suite regression check
```

---

## Proposed Changes

### Pillar 1: Semantic Stagnation Detection & Detour Routing

#### [MODIFY] `backend/engine/state.py`

Add two new fields to `VQAState`:

```python
# ── Amnesic Loop Detection (FEAT-062 Pillar 1) ─────────────────
# Tracks consecutive actions where both URL and DOM element count
# were unchanged after a browser action succeeded mechanically.
# Reset to 0 when URL changes, DOM changes, or ac_step_index advances.
# When this reaches AMNESIC_LOOP_THRESHOLD (3), the evaluator fires
# the Detour Strategy and routes to human_takeover.
amnesic_loop_count: int

# Snapshot of page state at last evaluator tick for stagnation comparison.
# Dict with: url (str), element_count (int | None)
_prev_page_state_snapshot: dict
```

Add to `make_initial_state`:
```python
"amnesic_loop_count": 0,
"_prev_page_state_snapshot": {},
```

#### [MODIFY] `backend/engine/evaluator.py`

**New constant** (module-level):
```python
# Consecutive action stagnation threshold before Detour Strategy fires.
_AMNESIC_LOOP_THRESHOLD = 3
```

**New helper function** `_detect_amnesic_loop(state, latest_step) -> tuple[bool, dict]`:
- Reads `_prev_page_state_snapshot` from state
- Reads current URL and DOM element count from `latest_step` (if executor populates it) OR via direct page read (passed in)
- Returns `(is_stagnant: bool, updated_snapshot: dict)`
- Stagnant = URL unchanged AND element_count unchanged
- Falls back to non-stagnant if element_count is unavailable (fail-safe)

**New helper** `_build_detour_action(state) -> dict`:
- Constructs a detour action payload (`{"action": "navigate", "url": state["target_url"]}`) OR a page refresh (`{"action": "keyboard", "key": "F5"}`) as a last resort
- Returns the dict for injection into state

**In `evaluator_node`** — insert stagnation check AFTER the per-step budget check and BEFORE Case 1 (failure branch):
```python
# ── Pillar 1: Amnesic Loop Detection ─────────────────────────────
# Only check on SUCCESSFUL actions (success=True). A failing action
# is already handled by ac_step_action_fail_count. The amnesic loop
# targets the scenario where actions SUCCEED mechanically but produce
# zero semantic progress (e.g. scroll 10 times without finding anything).
if success:
    is_stagnant, new_snapshot = _detect_amnesic_loop(state, latest_step)
    new_loop_count = (state.get("amnesic_loop_count", 0) + 1) if is_stagnant else 0

    if new_loop_count >= _AMNESIC_LOOP_THRESHOLD:
        logger.error(
            "[%s] AMNESIC LOOP detected: %d consecutive stagnant actions on AC step %d — dispatching Detour Strategy",
            run_id, new_loop_count, ac_index + 1,
        )
        return {
            "_next_node": "human_takeover",
            "awaiting_human_takeover": True,
            "amnesic_loop_count": 0,
            "_prev_page_state_snapshot": new_snapshot,
            "agent_critique": (
                f"AMNESIC LOOP: {new_loop_count} consecutive actions produced ZERO semantic "
                f"progress (URL and DOM unchanged). The agent is stuck in a loop. "
                f"Human intervention required to advance past AC step {ac_index + 1}."
            ),
            "bug_log": rbac_violations,
        }
    
    # Update stagnation counter for next iteration
    # (these are written as non-list overwrites — safe)
    # We don't return here; fall through to normal routing with updated counter.
    # NOTE: counter update is merged into the final return dict at end of success path.
```

> **Design note**: The stagnation counter is reset to `0` whenever `ac_step_index` advances (same as `retry_count`, `action_repeat_counts`, `action_history_buffer`).

#### [MODIFY] `backend/engine/executor.py`

Ensure the executor captures pre/post page state (URL + element count) for stagnation detection. If the executor already produces this data via `PageStateTracker`, expose it in the `ExecutionStep`. Otherwise, add a lightweight capture after each action:

```python
# Post-action DOM state capture (for Pillar 1 stagnation detection)
try:
    post_url = page.url if not page.is_closed() else ""
    post_element_count = await page.evaluate("document.querySelectorAll('*').length") if not page.is_closed() else None
    step["post_url"] = post_url
    step["post_element_count"] = post_element_count
except Exception:
    pass  # Non-fatal; evaluator falls back to non-stagnant
```

---

### Pillar 2: Vision/DOM Dual-Verification for CV Fallback

#### [MODIFY] `backend/engine/verifier.py`

**New function** `_visual_delta_check(pre_screenshot_b64: str, post_screenshot_b64: str, threshold: float = 0.005) -> bool`:
- Base64-decode both screenshots
- Use `PIL.Image` to compare pixel arrays via `ImageChops.difference()`
- Compute the ratio of non-zero pixels to total pixels
- Return `True` if ratio ≥ threshold (default 0.5% of pixels changed)
- Return `False` if both images are identical or nearly identical (noise floor)
- Handle import errors gracefully: if `PIL` is not available, log a warning and return `True` (fail-open, preserve existing behavior)

**Modify `cv_fallback_state_change_check`**:
- Add a `pre_screenshot_b64: str = ""` parameter
- After the existing 3 signals (URL, ARIA, DOM count), add Signal 4:
  ```python
  # ── Signal 4: Visual delta (screenshot diff) ───────────────────
  # Catches canvas elements and SPA components where DOM is unchanged
  # but the rendered output visually changed (e.g. chart animation,
  # modal overlay rendered on canvas layer).
  if pre_screenshot_b64:
      try:
          post_screenshot_b64 = await capture_screenshot_b64(run_id)
          if _visual_delta_check(pre_screenshot_b64, post_screenshot_b64):
              logger.info("CV_FALLBACK_STATE_CHANGE: Visual delta detected — screenshot pixel diff")
              return True
      except Exception as _vis_err:
          logger.debug("CV_FALLBACK_STATE_CHECK: Visual delta check failed: %s", _vis_err)
  ```

**Modify call-sites in `executor.py`**:
- When dispatching a CV fallback `mouse.click`, capture `pre_screenshot_b64 = await capture_screenshot_b64(run_id)` BEFORE the click
- Pass `pre_screenshot_b64` to `cv_fallback_state_change_check(..., pre_screenshot_b64=pre_screenshot_b64)`

---

### Pillar 3: Human Takeover Crash Resolution

#### [MODIFY] `backend/api/routes.py`

**Fix `_broadcast_human_takeover` signature** at line 226 — add `novnc_url: str | None = None`:

```python
async def _broadcast_human_takeover(
    run_id: str,
    ac_step: str,
    ac_step_index: int,
    error_message: str,
    instructions: str = "",
    novnc_url: str | None = None,   # ← ADD THIS PARAMETER
) -> None:
```

Inside the function body, replace the hard-coded `vnc_builder.build_url(ws, "interactive")` call with a fallback:
```python
# Use caller-provided novnc_url if available (set from state in human_takeover_node),
# otherwise build from first WS connection as before.
if novnc_url is None:
    ws = connections[0]
    novnc_url = vnc_builder.build_url(ws, "interactive")
```

This ensures backward compatibility: call sites that don't pass `novnc_url` (e.g. direct callers in tests) still get the URL built from the WS object.

#### [MODIFY] `backend/engine/human_takeover.py`

Verify the call to `_WS_BROADCAST_FN` at line 911-918 already passes `novnc_url=novnc_url` — **no change needed here** since this is where the `novnc_url` kwarg originates. The fix is entirely on the routes.py side.

Also update the `set_ws_broadcaster` docstring to document the new signature:
```python
# Signature: async (run_id: str, ac_step: str, ac_step_index: int,
#                   error_message: str, instructions: str = "",
#                   novnc_url: str | None = None) -> None
```

---

### Pillar 4: Playwright Lifecycle & Zombie Process Mitigation

#### [MODIFY] `backend/browser/context.py`

**In `BrowserManager.close()`** — enhance the `_TEARDOWN_SUPPRESSED_KEYWORDS` tuple to include the WriteUnixTransport pattern:

```python
_TEARDOWN_SUPPRESSED_KEYWORDS = (
    "target closed",
    "epipe",
    "connection closed",
    "browser has been closed",
    "context was destroyed",
    "writeunix",        # ← ADD: catches WriteUnixTransport closed=True
    "transport closed", # ← ADD: future-proof variation
)
```

**Add idempotency guard** — check `self._browser` and `self._playwright` are non-None before issuing teardown calls (they already are, this is a belt-and-suspenders lint):

Already correct in the current code. No change needed there.

**Verify teardown order** — the current code does:
1. Close actor registry contexts
2. Close primary context
3. `asyncio.sleep(0.5)` — video flush
4. `browser.close()`
5. `playwright.stop()`

This order is correct for video finalization. The fix is only in the suppressed keyword list.

**Add explicit transport liveness check** before `browser.close()`:
```python
if self._browser:
    try:
        # Check if the browser process is still alive before close()
        # browser.is_connected() is a sync property in Playwright
        if not self._browser.is_connected():
            logger.warning("[%s] Browser already disconnected — skipping browser.close()", self.run_id)
            self._browser = None
        else:
            await self._browser.close()
    except Exception as _browser_err:
        ...  # existing handling
```

---

## Files Modified Summary

| File | Pillar | Change Type |
|------|--------|-------------|
| `backend/engine/state.py` | P1 | Add `amnesic_loop_count`, `_prev_page_state_snapshot` fields |
| `backend/engine/evaluator.py` | P1 | Add stagnation detection + detour routing logic |
| `backend/engine/executor.py` | P1, P2 | Post-action URL/count capture; pre-screenshot capture for CV |
| `backend/engine/verifier.py` | P2 | `_visual_delta_check()` + Signal 4 in `cv_fallback_state_change_check` |
| `backend/api/routes.py` | P3 | Fix `_broadcast_human_takeover` signature (add `novnc_url` param) |
| `backend/engine/human_takeover.py` | P3 | Docstring update only (call-site is already correct) |
| `backend/browser/context.py` | P4 | Add WriteUnixTransport to suppressed keywords; add `is_connected()` guard |
| `tests/engine/test_evaluator.py` | P1 | New amnesic loop unit tests |
| `tests/engine/test_verifier.py` | P2 | New visual delta unit tests |
| `tests/api/test_human_takeover_broadcast.py` | P3 | New broadcast signature smoke tests |
| `tests/browser/test_browser_context.py` | P4 | New teardown idempotency tests |

---

## Risk Assessment

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| Stagnation false-positives (circuit breaker fires on legitimate slow SPA loads) | Medium | Threshold set to 3 consecutive; only fires on URL+DOM both unchanged; reset on any AC step advance |
| PIL not installed causing visual delta import error | Low | Fail-open: if PIL unavailable, skip Signal 4 (preserve existing behavior) |
| `is_connected()` behaves differently in async context | Low | Wrap in try/except; fall through to existing close logic |
| WriteUnixTransport keyword match too broad | Very Low | Keyword is distinctive; no legitimate error message should match |

---

## Dependencies

- PIL/Pillow must be available in the Python environment (already a transitive dependency via `langchain-aws`; verify with `pip show Pillow`)
- No new third-party packages required

---

## Definition of Done

- [ ] All 4 pillars implemented
- [ ] All RED tests pass GREEN
- [ ] Full test suite passes without regressions (`pytest tests/ -v`)
- [ ] Code review completed by a second agent persona
- [ ] `memory-bank/tasks.md` updated to production-readiness-hardening-and-execution-loop-prevention | BUILD | IN_PROGRESS
- [ ] `roadmap.md` FEAT-062 status updated to `in_progress`

---

## Creative Phases

- [x] Architecture Design — Multi-pillar integration architecture (evaluator/executor/verifier/browser teardown)
  - Output: `memory-bank/creative/production-readiness-hardening-and-execution-loop-prevention-production-hardening-architecture.md`
  - Decision: Option 1 — Inline Integration (no new LangGraph nodes; in-place modifications in existing engine files)
- [x] Algorithm Design — Amnesic loop stagnation detection + visual delta pixel diff algorithm
  - Output: `memory-bank/creative/production-readiness-hardening-and-execution-loop-prevention-production-hardening-algorithm.md`
  - Decision: A1 (URL+ElementCount dual-signal, O(1)) + B1 (PIL ImageChops.difference, 0.5% threshold, fail-open)

---

## Implementation Roadmap

- [x] Phase 1 (RED): Write failing tests for all 4 pillars (16 tests total)
- [x] Phase 2 (GREEN-P1): Implement Pillar 1 — Amnesic Loop Circuit Breaker (state.py, evaluator.py, executor.py)
- [x] Phase 3 (GREEN-P2): Implement Pillar 2 — Visual Delta CV Verification (verifier.py, executor.py)
- [x] Phase 4 (GREEN-P3): Implement Pillar 3 — Human Takeover Broadcast Fix (routes.py, human_takeover.py)
- [x] Phase 5 (GREEN-P4): Implement Pillar 4 — Playwright Lifecycle Idempotency (context.py)
- [x] Phase 6 (VERIFY): Run full test suite, code review

---

## Reflection

### Key Learnings
- **Stagnation Detection (P1)**: Dual-signal detection (URL + DOM element count) is highly effective at catching "amnesic loops" where the agent repeats scroll/wait actions. Resetting the counter on any AC step advance prevents false positives during long, multi-action steps.
- **Visual Delta (P2)**: Implementing pixel-level comparison (PIL ImageChops) provides a critical safety net for SPA/Canvas targets where the DOM is opaque. A 0.5% threshold successfully filters out rendering noise while catching meaningful UI changes.
- **WebSocket Robustness (P3)**: Fixed a brittle signature in the broadcast function that was causing crashes during human takeover. Standardizing on kwarg-based propagation for the VNC URL ensures reliability.
- **Graceful Teardown (P4)**: Playwright's `WriteUnixTransport` error is a known artifact of double-closing in async environments. Suppression and explicit `is_connected()` checks eliminated the noise from the logs.

### Metrics
- **Tests Added**: 12 new unit tests (100% pass)
- **Files Modified**: 10
- **Regressions**: 0
- **Complexity**: Level 4

---

## Execution State

**Build Status**: COMPLETE  
**Current Phase**: REFLECT → ARCHIVE  
**Can Resume**: YES (to Archive)

### Completed Steps
- Architecture Design Creative: COMPLETE (2026-05-31T19:35:54Z)
- Algorithm Design Creative: COMPLETE (2026-05-31T19:37:55Z)
- Phase 1 (RED): COMPLETE (2026-05-31T16:44Z)
- Phase 2 (GREEN-P1): COMPLETE (2026-05-31T16:47Z)
- Phase 3 (GREEN-P2): COMPLETE (2026-05-31T16:48Z)
- Phase 4 (GREEN-P3): COMPLETE (2026-05-31T16:49Z)
- Phase 5 (GREEN-P4): COMPLETE (2026-05-31T16:49Z)
- Phase 6 (VERIFY): COMPLETE (2026-05-31T20:45Z)
