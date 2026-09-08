---
legacy_id: fix-graphrecursionerror-recursion-limit-too-low-for-node-vis
---
# fix-graphrecursionerror-recursion-limit-too-low-for-node-vis: Fix GraphRecursionError — recursion_limit Too Low for Node-Visit Count

**Complexity**: Level 1
**Status**: COMPLETE
**Jira Issue**: N/A
**Issue Type**: Bug
**Priority**: High
**Branch**: feature/fix-graphrecursionerror-recursion-limit-too-low-for-node-vis-fix-graph-recursion-limit
**Worktree**: N/A
**Roadmap**: N/A

---

## Task Description

The vQA backend crashes with `GraphRecursionError: Recursion limit of 500 reached without hitting a stop condition` during long test runs.

**Root cause**: LangGraph counts **graph node visits** against the `recursion_limit`, NOT planner iterations. Each planner cycle visits ~4-5 nodes (planner → executor → evaluator → verifier → back to planner). With `max_planner_iterations = 500` and the graph `recursion_limit` also set to `500`, the graph hits its visit cap long before the evaluator's `planner_iteration >= max_iterations` guard fires. The result is an unhandled crash that surfaces as an uncaught exception in the WebSocket handler.

**Two required fixes:**
1. **Increase `recursion_limit`** from 500 to a value that accommodates the actual max node visits (`max_planner_iterations × ~5 nodes/cycle = ~2500`, plus headroom → 3000).
2. **Catch `GraphRecursionError`** in `_execute_run` and treat it as a graceful terminal failure (broadcast `failed` terminal message) instead of letting it propagate as an unhandled exception.

---

## Acceptance Criteria

- **AC-HAPPY-1**: Runs that previously hit the recursion limit at 500 node visits can now run their full `max_planner_iterations` budget without crashing.
- **AC-HAPPY-2**: If the recursion limit IS genuinely hit (extremely long run), the error is caught and a `failed` terminal message is broadcast to the WebSocket client with a clear error string instead of a server traceback.
- **AC-ERROR-1**: `GraphRecursionError` is classified alongside page-closed errors as a known non-fatal error variant and NOT logged with `exc_info=True`.
- **AC-REGRESS-1**: Existing evaluator `planner_iteration >= max_iterations` safety cap still works as before.

---

## Open Questions

None — task is well-defined.

---

## Affected Components

- `backend/api/routes.py` — `_execute_run` function: increase `recursion_limit`, catch `GraphRecursionError`
- `backend/config.py` — `max_planner_iterations` docstring update (clarify node-visit vs iteration distinction)

---

## Test Strategy

### Approach
- **Emphasis**: unit-focused
- **Target test count**: 1 targeted regression test

### Test Targets
- `_execute_run` exception handling path — verify `GraphRecursionError` is caught and terminal message is broadcast.

### What NOT to Test
- Internal LangGraph recursion counting mechanics.

---

## Implementation Roadmap
- [x] Phase 1: Update `recursion_limit` in `_execute_run` and add `GraphRecursionError` catch block.
- [x] Phase 2: Update `max_planner_iterations` docstring in config.py.

---

## Execution State

**Build Status**: IDLE
**Last Completed**: ARCHIVED
**Can Resume**: NO

### Active Sub-Agents
(none)

### Completed Steps
- [x] Task file created
- [x] Code fix applied to routes.py (recursion_limit + catch block)
- [x] Docstring updated in config.py (max_planner_iterations — node-visit distinction)
- [x] Regression test written: tests/test_task_027_graph_recursion_limit.py (5 tests, all passing)
- [x] All phases complete
- [x] Reflection created: memory-bank/reflection/reflection-fix-graphrecursionerror-recursion-limit-too-low-for-node-vis.md
- [x] Learned rules updated: error-handling.md (+2 rules)
