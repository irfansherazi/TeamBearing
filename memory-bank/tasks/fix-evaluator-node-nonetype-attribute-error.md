---
legacy_id: fix-evaluator-node-nonetype-attribute-error
---
# fix-evaluator-node-nonetype-attribute-error: Fix evaluator_node NoneType attribute error

**Complexity**: Level 1
**Status**: COMPLETE
**Archived**: memory-bank/archive/archive-fix-evaluator-node-nonetype-attribute-error.md
**Completed**: 2026-05-15
**Jira Issue**: N/A
**Issue Type**: Bug
**Priority**: Medium
**Branch**: feature/fix-evaluator-node-nonetype-attribute-error-fix-evaluator-nonetype-error
**Worktree**: .worktrees/fix-evaluator-node-nonetype-attribute-error
**Roadmap**: N/A

---

## Task Description

The vQA engine crashes with an `AttributeError: 'NoneType' object has no attribute 'lower'` at `backend/engine/evaluator.py:761` during test execution (specifically around step 60, switching to compact view).

The error occurs on this line:
`_sort_target = (planned_name or planned.get("target_text", "")).lower()`

If both `planned_name` and the explicit value of `target_text` inside `planned` are `None` (for instance, during a recipe execution where no name or text is targeted), the `or` expression evaluates to `None`, which then throws an error when `.lower()` is called. The fix is to add a fallback to an empty string.

---

## Acceptance Criteria

- AC-HAPPY-1: The evaluator node handles `None` values for `planned_name` and `target_text` gracefully without throwing an `AttributeError`.
- AC-REGRESS-1: The existing sorting circuit breaker logic continues to function correctly for valid sort targets.

---

## Open Questions

None — task is well-defined.

---

## Affected Components

- `backend/engine/evaluator.py` — Needs a null-safe fallback for `_sort_target` generation.

---

## Test Strategy

### Approach
- **Emphasis**: Unit-heavy.
- **Target test count**: 0 (simple defensive null-check, verified via runtime execution)

### Test Targets
- `evaluator_node` execution with missing or null action attributes.

### What NOT to Test
- Unrelated components.
- Third-party library internals.

---

## Implementation Roadmap
- [x] Phase 1: Update `evaluator.py:761` to include an `or ""` fallback before calling `.lower()`.

---

## Build Execution State

**Build Status**: IDLE
**Current Phase**: COMPLETE
**Can Resume**: NO
**Phase Number**: 1 of 1
**Is Multi-Phase**: NO

### Current Build Step
**Step**: Step 11 - Git Completion
**Status**: COMPLETE
**Started**: 2026-05-15T19:38:00Z
**Completed**: 2026-05-15T19:38:45Z
**Output**: Changes committed to feature branch.

### Completed Steps
- Step 0.1 Check for Interrupted Build: COMPLETE (2026-05-15T19:35:00Z) - New build
- Step 0.1 Agent Rules Check: COMPLETE (2026-05-15T19:35:00Z) - No rules
- Step 0.5 Git Setup: COMPLETE (2026-05-15T19:36:00Z) - Worktree created and branch checked out
- Step 1 Read Task Context: COMPLETE (2026-05-15T19:36:05Z) - Phase 1 identified, single-phase task.
- Step 2 Load Complexity Context: COMPLETE (2026-05-15T19:36:13Z) - Loaded Level 1 rules.
- Step 4 Code Implementation: COMPLETE (2026-05-15T19:36:22Z) - Fixed evaluator.py fallback logic.
- Step 7 Integration Verification: COMPLETE (2026-05-15T19:38:10Z) - Tests and linting completed.
- Step 11 Git Completion: COMPLETE (2026-05-15T19:38:45Z) - Committed fix to branch.

### Sub-Agents
(none)

### Resumption Notes
**Can Resume**: NO
**Resume From**: N/A
**Notes**: Build complete.
