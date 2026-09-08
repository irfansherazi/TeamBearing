---
legacy_id: multi-type-recovery-router-feat-079
---
# multi-type-recovery-router-feat-079: Multi-Type Recovery Router (FEAT-079)

**Status**: COMPLETE
**Complexity**: Level 3
**Roadmap Link**: FEAT-079
**Branch**: feature/FEAT-079-multi-type-recovery-router
**Worktree**: N/A
**Pillar**: P2 — Execution Engine Reliability
**Gap ID**: P2-A
**Estimated Effort**: ~3h
**Created**: 2026-06-03

---

## Description

The recovery router is currently one-shot per AC step — after one recovery attempt the agent falls into HITL escalation even when a different recovery strategy would succeed. Root cause: `recovery_attempted: bool` flag prevents any further recovery once set. Fix: replace `recovery_attempted: bool` with `recovery_attempted_types: set[str]` and update the recovery router to check whether the proposed recovery type has already been tried.

This is a Level 3 complexity feature that hardens execution engine reliability by allowing multiple recovery actions of different types to execute sequentially before escalating.

---

## Acceptance Criteria

### AC-1: State Refactoring & Field Replacement
**Priority**: MUST

**Given** the initial state of the run or any intermediate execution state
**When** state fields are loaded or initialized via `make_initial_state`
**Then**:
- `VQAState` has `recovery_attempted_types: set[str]` instead of `recovery_attempted: bool`.
- The field is initialized as an empty set `set()`.

**Verification**:
- [x] Unit test: `test_recovery_attempted_types_in_state` inside `tests/test_recovery_router.py`

### AC-2: Multi-Type Recovery Router Checks
**Priority**: MUST

**Given** a Playwright error has occurred and has been classified into a `RecoveryType`
**When** the recovery router decides whether to apply recovery
**Then**:
- The recovery router checks if the classified `RecoveryType` is already in `recovery_attempted_types`.
- If the type is NOT in the set, the recovery router proceeds with applying recovery for this type.
- If the type IS in the set, the recovery router returns `None` (falling through to normal retry or escalation).

**Verification**:
- [x] Unit test: `test_recovery_router_gated_by_type` inside `tests/test_recovery_router.py`

### AC-3: Attempt Logging & Dispatch
**Priority**: MUST

**Given** a recovery of a specific type has been dispatched by `evaluator_node`
**When** the evaluator node updates the execution state and returns to the planner
**Then**:
- The dispatched recovery type is added to `recovery_attempted_types` in the state.
- Subsequent recoveries of the same type are blocked, but other recovery types remain eligible.

**Verification**:
- [x] Unit test: `test_recovery_type_added_to_state_on_dispatch` inside `tests/test_recovery_router.py`

### AC-4: Backward Compatibility Migration
**Priority**: MUST

**Given** an older serialized `VQAState` or dictionary containing `recovery_attempted: bool` or lacking the `recovery_attempted_types` field (e.g. from an upgraded/migrated state)
**When** accessed by the recovery router or the evaluator
**Then**:
- The system handles it gracefully without throwing an exception or failing.
- It safely falls back to treating `recovery_attempted: bool` or missing fields as an empty set.

**Verification**:
- [x] Unit test: `test_backward_compatible_state_migration` inside `tests/test_recovery_router.py`

### AC-5: Sequenced Multi-Type Recovery Execution
**Priority**: MUST

**Given** an AC step that experiences two different types of Playwright failures sequentially (e.g., first a `STRICT_MODE` violation, and then a `TIMEOUT` error)
**When** evaluated by the evaluator
**Then**:
- Both recovery actions are attempted in sequence (one for strict mode, then one for timeout) before falling back to HITL escalation.
- Each recovery type is recorded in the `recovery_action_log` and registered in `recovery_attempted_types`.

**Verification**:
- [x] Integration test: `test_multiple_distinct_recoveries_on_same_step` inside `tests/test_recovery_router.py`

---

## Clarifications Needed

_None — specifications from FEAT-079 are clear._

---

## Implementation Roadmap

### 1. State Definition (`backend/engine/state.py`)
- Remove `recovery_attempted: bool` from `VQAState`.
- Add `recovery_attempted_types: set[str]` to `VQAState`.
- Update `make_initial_state()` to initialize `recovery_attempted_types=set()`.

### 2. Recovery Router Logic (`backend/engine/recovery_router.py`)
- Modify `attempt_recovery` signature or implementation to read `state.get("recovery_attempted_types", set())`.
- For backward compatibility (AC-4), check if `state` contains `"recovery_attempted": True`. If so, or if `recovery_attempted_types` is not a set (e.g., a list or absent), convert/seed appropriately:
  ```python
  raw_types = state.get("recovery_attempted_types")
  if isinstance(raw_types, list):
      attempted_types = set(raw_types)
  elif isinstance(raw_types, set):
      attempted_types = raw_types
  else:
      attempted_types = set()
  
  if state.get("recovery_attempted", False):
      attempted_types = {t.value for t in RecoveryType}
  ```
- Check `if recovery_type.value in attempted_types:` or `if recovery_type in attempted_types:` before routing. Return `None` if already attempted.

### 3. Evaluator Updates (`backend/engine/evaluator.py`)
- Locate all places resetting `recovery_attempted` to `False` (e.g., step advance, actor change, persona switch, role change).
- Replace `"recovery_attempted": False` with `"recovery_attempted_types": set()`.
- Inside `evaluator_node`'s recovery router block (around line 1207):
  - Safely retrieve `attempted_types = state.get("recovery_attempted_types", set())` with legacy/deserialization fallback.
  - If the proposed recovery type is not in `attempted_types`, call `attempt_recovery`.
  - When applying recovery (line 1229), return the updated state including:
    ```python
    "recovery_attempted_types": attempted_types | {_recovery.recovery_type.value}
    ```

### 4. Regression / Legacy Tests
- Update existing references to `recovery_attempted` in legacy unit/integration tests to use `recovery_attempted_types` (or keep them backward compatible if checking both).
- Update the mock states in `tests/test_recovery_router.py`, `tests/test_deferred_verification.py`, and `tests/test_task_051_phase2_bug_d.py`.

---

## Test Strategy

### 1. Test Method
- We will execute our tests using:
  ```bash
  pytest tests/test_recovery_router.py -v
  ```

### 2. Success Metrics
- 100% of recovery router tests pass.
- At least 5 new unit/integration tests covering AC-1 through AC-5 are added to `tests/test_recovery_router.py`.

### 3. Observable Location
- Terminal output of `pytest tests/test_recovery_router.py -v` showing all passed tests.

---

## Creative Phases

_None required — Level 3, but implementation and requirements are completely clear and well-defined by existing recovery router paradigms._

---

## Execution State

**Build Status**: COMPLETE
**Current Phase**: None
**Current Step**: None
**Step Started**: None
**Can Resume**: NO
**Worktree Cleaned**: YES
**Branch Deleted**: NO (preserved for PR)
