---
legacy_id: per-step-iteration-budget
---
# per-step-iteration-budget: Per-Step Iteration Budget

**Complexity**: Level 2
**Status**: COMPLETE
**Jira Issue**: N/A
**Issue Type**: Feature
**Priority**: High
**Branch**: feature/per-step-iteration-budget-per-step-budget
**Worktree**: N/A
**Roadmap**: FEAT-021

---

## Task Description

Implement adaptive per-AC-step iteration allocation to prevent a single stuck step from consuming the entire run's iteration budget (FM-2: Budget Starvation).

**Problem**: The current global `max_planner_iterations` (default 500) is a single shared budget for the entire run. If a complex step (e.g., navigating a deeply nested form) consumes 200 iterations, the remaining 15 steps only have 300 iterations to share. Worse, if a step gets stuck in a retry loop that doesn't trigger human_takeover (because actions technically "succeed" but the verifier rejects them), it can silently consume the entire budget.

**Solution**: On entry to each AC step, compute a per-step iteration budget:

```
step_budget = min(30, remaining_budget / remaining_steps)
```

If a step exceeds its allocated budget, mark it as **SKIPPED** (not FAILED) and advance to the next AC step. The reporter flags skipped steps with a distinct visual indicator for human review.

Key behavioral changes:
1. **Budget calculation**: `min(30, remaining_budget / remaining_steps)` — ensures no step gets more than 30 iterations, and remaining budget is fairly distributed across remaining steps.
2. **SKIPPED status**: Steps that exceed their budget are marked SKIPPED, not FAILED. This is a semantic distinction: FAILED means "the app is broken"; SKIPPED means "the agent ran out of time on this step."
3. **Budget tracking in state**: Two new fields in VQAState: `ac_step_iteration_budget` (int) and `ac_step_iterations_used` (int).
4. **Reporter integration**: Skipped steps get a distinct visual indicator (amber badge) with text like "SKIPPED (budget exceeded: 30/30 iterations)".

---

## Acceptance Criteria

- AC-HAPPY-1: On entry to a new AC step, the evaluator computes `step_budget = min(30, remaining_budget / remaining_steps)` and stores it in state.
- AC-HAPPY-2: `ac_step_iterations_used` is incremented on every planner pass for the current AC step and reset to 0 when `ac_step_index` advances.
- AC-HAPPY-3: When `ac_step_iterations_used >= ac_step_iteration_budget`, the evaluator marks the step as SKIPPED, logs a warning, and advances to the next AC step.
- AC-HAPPY-4: SKIPPED steps are NOT added to `ac_steps_completed` (they were not successfully validated).
- AC-HAPPY-5: The reporter renders skipped steps with a distinct visual indicator (amber badge) showing "SKIPPED (budget: N iterations)".
- AC-HAPPY-6: The `per_step_budget_max` config field allows operators to tune the cap (default 30) via environment variable `PER_STEP_BUDGET_MAX`.
- AC-ERROR-1: When `remaining_steps` is 0 (all steps done or on last step), the budget defaults to `per_step_budget_max` to avoid division by zero.
- AC-ERROR-2: When `remaining_budget <= 0`, the evaluator routes directly to reporter (existing behavior preserved).
- AC-REGRESS-1: No regressions in existing evaluator tests (`test_evaluator_hardening.py`).
- AC-REGRESS-2: The existing `max_planner_iterations` global cap still terminates the run when hit.
- AC-REGRESS-3: The existing `current_ac_step_action_count` circuit breaker still works independently of the per-step budget.

---

## Open Questions

None — task is well-defined.

---

## Affected Components

Based on the codebase analysis:

- `backend/engine/state.py` — Add `ac_step_iteration_budget: int` and `ac_step_iterations_used: int` fields to VQAState; update `create_initial_state()` to initialize them.
- `backend/engine/evaluator.py` — Main implementation: compute budget on step entry, increment usage counter, add SKIPPED routing logic when budget is exceeded. Multiple touch points: step advancement resets, the main routing logic, and the safety cap section.
- `backend/config.py` — Add `per_step_budget_max: int = Field(default=30, ...)` setting.
- `backend/engine/reporter.py` — Render SKIPPED steps with amber badge in the HTML audit report.
- `backend/engine/planner.py` — Increment `ac_step_iterations_used` in `planner_node()` (where `planner_iteration` is already incremented).

---

## Test Strategy

### Approach
- **Emphasis**: Unit-heavy — the core logic is arithmetic + routing in the evaluator
- **Target test count**: 8-10 tests

### Test Targets
- Budget computation: `min(30, remaining / remaining_steps)` with various inputs
- Budget exhaustion routing: verify SKIPPED status + step advancement
- Budget reset on step advancement: verify `ac_step_iterations_used` resets to 0
- Division-by-zero guard: `remaining_steps == 0` edge case
- Config override: `per_step_budget_max` changes the cap
- Reporter rendering: SKIPPED badge appears in HTML output
- Regression: existing circuit breakers still fire independently

### What NOT to Test
- End-to-end LangGraph execution (requires live environment)
- Playwright browser interactions
- S3 upload behavior

---

## Implementation Roadmap
- [ ] Phase 1: Add `per_step_budget_max` to `config.py` Settings
- [ ] Phase 2: Add `ac_step_iteration_budget` and `ac_step_iterations_used` to VQAState + `create_initial_state()`
- [ ] Phase 3: Increment `ac_step_iterations_used` in `planner_node()` alongside `planner_iteration`
- [ ] Phase 4: Compute per-step budget in evaluator on step entry (all step-advancement paths)
- [ ] Phase 5: Add SKIPPED routing logic in evaluator when budget exceeded (before the existing failure/done/verifier cases)
- [ ] Phase 6: Reset `ac_step_iterations_used` to 0 in all step-advancement paths
- [ ] Phase 7: Add `ac_steps_skipped` list to VQAState for reporter tracking
- [ ] Phase 8: Reporter renders SKIPPED steps with amber badge
- [ ] Phase 9: Write unit tests

---

## Execution State

**Build Status**: ARCHIVED
**Current Phase**: ARCHIVE
**Build Started**: 2026-05-11T11:55:00-05:00
**Build Completed**: 2026-05-11T12:02:00-05:00
**Gemini CLI**: available — single-agent mode (inline)
**Can Resume**: NO

### Completed Steps
1. ✅ Phase 1: config.py — per_step_budget_max field (default 30)
2. ✅ Phase 2: state.py — ac_step_iteration_budget, ac_step_iterations_used, ac_steps_skipped
3. ✅ Phase 3: planner.py — ac_step_iterations_used increment in return dict
4. ✅ Phase 4: evaluator.py — budget computation (min(cap, remaining/steps))
5. ✅ Phase 5: evaluator.py — SKIPPED routing when budget exhausted
6. ✅ Phase 6: evaluator.py — ac_step_iterations_used reset in ALL step-advancement paths
7. ✅ Phase 7: reporter.py — SKIPPED amber badge rendering + CSS
8. ✅ Phase 8: tests — 21 unit tests (all passing, 0 regressions)
