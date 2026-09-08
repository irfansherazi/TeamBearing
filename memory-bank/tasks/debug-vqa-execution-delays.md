---
legacy_id: debug-vqa-execution-delays
---
# debug-vqa-execution-delays: Debug vQA Execution Delays

**Complexity**: Level 3
**Status**: COMPLETE
**Roadmap**: FEAT-032
**Archived**: memory-bank/archive/archive-debug-vqa-execution-delays.md
**Completed**: 2026-05-15
**Branch**: feature/FEAT-032-debug-vqa-execution-delays
**Worktree**: N/A

## Task Description

Investigate and resolve the issues causing the vQA product to take excessive time and fail during sorting operations, addressing the 124-step loop involving strict mode violations, primeng dropdown failures, and recursive coordinate_action retries bypassing the identical-action circuit breaker.

## User Journey Definition

1. **Test Initiation**: A QA engineer starts a sorting test (e.g., "Sort Production Orders by Client").
2. **Ambiguity Encountered**: The agent attempts to click the "Client" sort header but encounters a `STRICT_MODE_VIOLATION` (multiple matches).
3. **Vision Mode Escalation**: After 2 failures, the agent switches to vision mode (`som_coordinates`).
4. **Coordinate Loop**: The agent identifies the correct coordinates for the sort button but, due to page latency or incorrect verification, repeatedly clicks the same coordinates.
5. **Circuit Breaker Bypass**: Because `coordinate_action` is "successful" (mouse clicked) and lacks its `mark_id` in the deduplication key, the identical-action circuit breaker never trips.
6. **Overlay Interference**: The `Proactive Overlay Dismissal` logic repeatedly presses `Escape` before the agent's actions, closing the sort menu the agent just opened, leading to a "124-step" infinite loop until the graph recursion limit (500) is hit.
7. **Failure**: The run fails with `GraphRecursionError` instead of a meaningful error or human takeover.

## Specification

### 1. Problem Statement
The vQA engine suffers from several interrelated reliability gaps that manifest as "infinite loops" during complex UI interactions like sorting:
- **Deduplication Blind Spot**: `executor.py`'s identical-action circuit breaker key ignores `mark_id`, allowing vision-mode actions to repeat indefinitely.
- **Success-Based Loop**: Circuit breakers only count `success=False`. Actions like `press_key("Escape")` or `coordinate_action` often succeed at the Playwright level but fail to advance the AC step, evading the budget.
- **Aggressive Dismissal**: `FEAT-026` Proactive Overlay Dismissal closes functional overlays (like dropdowns and dialogs) because it lacks context for `coordinate_action` and has an overly broad "is_functional=False" mapping for dialogs.
- **Vision Mode Budget Reset**: `evaluator.py` resets the `current_ac_step_action_count` when switching to vision mode, granting a fresh budget that can be abused by a confused planner.

### 2. Technical Requirements
- **Harden Deduplication Key**: Must uniquely identify `coordinate_action` and `primeng_dropdown` vision parameters.
- **Loop Detection for Successes**: Detect and break loops of identical "successful" actions that don't lead to `SATISFIED` verdicts.
- **Context-Aware Overlay Logic**: Proactive dismissal must respect `coordinate_action` and distinguish between blocking overlays and functional dialogs.
- **Unified Step Budget**: Maintain a consistent action count across mode switches (DOM -> Vision).

### 3. Proposed Changes

#### backend/engine/executor.py
- **Deduplication Key Update**: Modify `_selector_key` generation to include `mark_id`, `trigger_mark_id`, and `target_text`.
- **Circuit Breaker Increment**: Change logic to increment `action_repeat_counts` for EVERY attempt (or specifically for `coordinate_action` and `press_key`) instead of only on `success=False`.
- **Proactive Dismissal Refinement**: 
    - Skip dismissal if `action_type == "coordinate_action"`.
    - Improve `is_inside` check by allowing `container_selector` to match the `overlay_selector` exactly.
    - Change `is_functional` to `True` for `p-dialog` in `state_tracker.py`.

#### backend/engine/evaluator.py
- **Sort Action Circuit Breaker**: Include `coordinate_action` in the `_SORT_OPTION_NAMES` loop detection.
- **Vision Mode Transition**: Remove the reset of `current_ac_step_action_count` when switching to vision mode.
- **Done Guardrail**: Ensure `DONE_GUARDRAIL_BLOCKED` increments the repeat count (already implemented but verify).

#### backend/engine/state_tracker.py
- Update `_OVERLAY_SELECTORS`: Set `is_functional=True` for `dialog` types to prevent proactive dismissal of active dialogs.

### 4. Success Criteria
- **AC-VERIFY-1**: Identical `coordinate_action` calls trip the circuit breaker after 3 repeats.
- **AC-VERIFY-2**: Repeated `press_key("Escape")` calls trip the circuit breaker even if successful.
- **AC-VERIFY-3**: Proactive dismissal no longer closes the PrimeNG sort panel when the agent is using `coordinate_action` to open it.
- **AC-VERIFY-4**: Graph recursion limit (500) is never reached; agent escalates to `human_takeover` or `reporter` well before that.

## Test Strategy

### 1. Unit Tests
- `tests/engine/test_task_021_circuit_breaker.py`: Verify new deduplication keys for `coordinate_action`.
- `tests/engine/test_task_021_success_loop.py`: Verify circuit breaker trips on repeated `press_key` and `coordinate_action` successes.

### 2. Integration Tests
- `tests/test_task_021_sorting_loop.py`: Mock a sorting scenario where the agent gets stuck and verify it escalates to HITL instead of recursion error.

## Implementation Roadmap

### Phase 1: Circuit Breaker Hardening
- [x] Update `executor.py` deduplication key and increment logic.
- [x] Update `evaluator.py` sort loop detection and budget preservation.

### Phase 2: Overlay Dismissal Fixes
- [x] Update `state_tracker.py` overlay metadata.
- [x] Refine `executor.py` proactive dismissal gate.

### Phase 3: Validation
- [x] Run benchmark tests to ensure no regressions in sorting performance.
- [x] Verify fix for the reported "124-step" scenario.

## Creative Phases

- [x] [Algorithm] Circuit Breaker Key Design → Complete
- [x] [Algorithm] Overlay Scoping Logic → Complete

---

## Execution State

**Build Status**: IDLE
**Current Phase**: COMPLETE
**Can Resume**: NO

### Active Sub-Agents
(none)

### Completed Steps
- Algorithm Creative Design: COMPLETE (2026-05-15T12:38:34-05:00) - Output: memory-bank/creative/debug-vqa-execution-delays-circuit-breaker-key-algorithm.md
- Algorithm Creative Design: COMPLETE (2026-05-15T12:38:34-05:00) - Output: memory-bank/creative/debug-vqa-execution-delays-overlay-scoping-algorithm.md
- Reflection Agent: COMPLETE - Output: memory-bank/reflection/reflection-debug-vqa-execution-delays.md
- Pattern Extraction: COMPLETE - Extracted 2 learnings
- Git Commit: COMPLETE - Latest Commit: 66e1009
