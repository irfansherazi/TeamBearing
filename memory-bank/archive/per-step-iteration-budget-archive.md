# Archive: per-step-iteration-budget — Per-Step Iteration Budget

**Completed**: 2026-05-11
**Complexity**: Level 2
**Branch**: feature/FEAT-001-ac-quality-gate (co-located with FEAT-001 work)
**Status**: COMPLETE

## Summary

Implemented adaptive per-AC-step iteration allocation (FEAT-021) to prevent a single stuck AC step from consuming the entire run's global iteration budget. The feature computes `min(per_step_budget_max, remaining_budget / remaining_steps)` on each evaluator entry and marks steps as SKIPPED (not FAILED) when they exceed their allocation.

Key behavioral changes:
- **Budget computation**: `min(30, remaining_budget / remaining_steps)` with `max(1, ...)` floor
- **SKIPPED status**: Budget-exhausted steps are SKIPPED — semantically distinct from FAILED
- **State tracking**: `ac_step_iteration_budget`, `ac_step_iterations_used`, `ac_steps_skipped` in VQAState
- **Reporter rendering**: Amber badge with ⊘ icon and "budget exceeded" text
- **Config tunability**: `per_step_budget_max` field (default 30, env var `PER_STEP_BUDGET_MAX`)

Bonus fix: BUG-003 — `_deduplicated_add` reducer for `ac_steps_completed` prevents duplicate step indices.

## Files Changed

- `backend/config.py` — Added `per_step_budget_max: int = Field(default=30, ge=5, le=100)` setting
- `backend/engine/state.py` — Added 3 new VQAState fields + `_deduplicated_add` reducer + `make_initial_state` initialization
- `backend/engine/planner.py` — `ac_step_iterations_used` increment in planner return dict
- `backend/engine/evaluator.py` — Budget computation, SKIPPED routing logic, counter resets in all 5+ step-advancement paths
- `backend/engine/reporter.py` — SKIPPED amber badge rendering with `class="skip"`, ⊘ icon, and "budget exceeded" detail text

## Tests Added

- `tests/test_per_step_budget.py` — 21 unit tests across 8 test classes:
  - `TestStateInitialization` (3 tests): VQAState field defaults
  - `TestBudgetComputation` (6 tests): Formula arithmetic + edge cases
  - `TestBudgetExhaustion` (3 tests): SKIPPED routing + last-step reporter routing
  - `TestBudgetReset` (1 test): Counter reset on step advancement
  - `TestConfigOverride` (2 tests): Settings field existence + default
  - `TestReporterRendering` (2 tests): Amber badge HTML + pass rendering
  - `TestRegression` (3 tests): Global cap, circuit breaker, zero-budget preservation
  - `TestPlannerIncrement` (1 test): Counter increment formula

## Key Decisions

1. **SKIPPED vs FAILED semantic split**: Using a separate `ac_steps_skipped` list (not overloading `ac_steps_completed`) preserves the distinction between "app is broken" and "agent ran out of time" for accurate reporting.

2. **Budget placement in evaluator cascade**: Inserted after the global `max_planner_iterations` cap but before failure/success routing — ensures global cap still short-circuits, and per-step budget fires before wasting verifier/classifier cycles.

3. **`max(1, ...)` floor on budget**: Prevents a zero-budget allocation when `remaining_budget < remaining_steps`, guaranteeing every step gets at least 1 iteration.

4. **Division-by-zero guard**: When `remaining_steps <= 0`, defaults to `per_step_budget_max` cap rather than computing.

## Linked Artifacts

- Task: memory-bank/tasks/per-step-iteration-budget.md
- Reflection: memory-bank/reflection/reflection-per-step-iteration-budget.md
- Roadmap Feature: FEAT-021
- Learned Rules: memory-bank/agent-rules/_learned/evaluator-routing.md
