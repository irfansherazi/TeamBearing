# Reflection: fix-graphrecursionerror-recursion-limit-too-low-for-node-vis — Fix GraphRecursionError — recursion_limit Too Low

**Date**: 2026-05-16
**Complexity**: Level 1 (Bug Fix)
**Status**: REFLECTION_COMPLETE

---

## 1. What Was the Issue?

The vQA backend crashed with an unhandled `GraphRecursionError` during long test runs:

```
langgraph.errors.GraphRecursionError: Recursion limit of 500 reached without hitting a stop condition.
```

**Root cause**: A category mismatch between LangGraph's `recursion_limit` and the application's `max_planner_iterations`.

- `max_planner_iterations = 500` — the evaluator's safety guard fires after 500 **planner loop iterations**
- `recursion_limit = 500` — LangGraph's hard stop fires after 500 **graph node visits**

Each planner iteration visits ~5 nodes (planner → executor → evaluator → verifier → back to planner). So for 500 planner iterations, ~2,500 node visits are needed. With both limits set to 500, the LangGraph hard stop fired 5× too early — before the evaluator's own guard could produce a clean, reportable failure. The exception propagated uncaught, leaving the WebSocket client with no terminal message.

This was visually confirmed in the terminal log captured alongside this reflection: `run-4c0e9194` hit the recursion error at AC step 34/40, at planner iteration ~130 (well within the 500-iteration budget), because the node visit count had already exceeded 500.

---

## 2. How Was It Resolved?

**Two-part fix:**

### Fix 1 — Raise `recursion_limit` (`backend/api/routes.py`)
Changed the `recursion_limit` in the `graph.astream()` config from `500` to `3000`:
```
500 iterations × ~5 node-visits/cycle = 2500 node visits + headroom → 3000
```
This ensures the evaluator's `planner_iteration >= max_iterations` guard always fires before LangGraph's hard stop, making the recursion limit a true last-resort safety net.

### Fix 2 — Catch `GraphRecursionError` gracefully (`backend/api/routes.py`)
Added a catch branch for `GraphRecursionError` in the outer `except` block inside `_execute_run`. The error is:
- Classified as a known non-fatal variant (same tier as `TargetClosedError`)
- Logged at `WARNING` level with no `exc_info=True` (avoids 80-line tracebacks)
- Results in a `failed` terminal `WSTerminalMessage` being broadcast to the WebSocket client, so the frontend receives a clean failure state rather than a silent disconnect

### Fix 3 — Docstring update (`backend/config.py`)
Updated the `max_planner_iterations` field description with a NOTE clarifying the node-visit vs planner-iteration distinction to prevent this category error from recurring in future tuning.

---

## 3. Files Changed

| File | Change |
|------|--------|
| `backend/api/routes.py` | Raised `recursion_limit` from 500 → 3000; added `GraphRecursionError` catch block |
| `backend/config.py` | Updated `max_planner_iterations` docstring with node-visit distinction NOTE |
| `tests/test_task_027_graph_recursion_limit.py` | New — 5 regression tests covering all 4 ACs |

---

## 4. Verification

All 5 regression tests pass:

```
tests/test_task_027_graph_recursion_limit.py::TestRecursionLimitValue::test_recursion_limit_is_at_least_six_times_max_planner_iterations PASSED
tests/test_task_027_graph_recursion_limit.py::TestRecursionLimitValue::test_recursion_limit_equals_3000_by_default PASSED
tests/test_task_027_graph_recursion_limit.py::TestGraphRecursionErrorHandling::test_graph_recursion_error_broadcasts_failed_terminal[asyncio] PASSED
tests/test_task_027_graph_recursion_limit.py::TestGraphRecursionErrorHandling::test_graph_recursion_error_does_not_log_exc_info[asyncio] PASSED
tests/test_task_027_graph_recursion_limit.py::TestMaxPlannerIterationsDocstring::test_max_planner_iterations_docstring_mentions_node_visits PASSED
```

AC coverage: AC-HAPPY-1 ✅, AC-HAPPY-2 ✅, AC-ERROR-1 ✅, AC-REGRESS-1 ✅

---

## 5. Key Learnings

### Learning 1 (High Reuse)
- **error-handling** (`backend/api/routes.py` and any framework-integrated executor):
  Distinguish between **framework-level hard limits** (e.g., LangGraph's `recursion_limit`) and **application-level safety caps** (e.g., `max_planner_iterations`). When a framework imposes a limit on a unit that differs from the application's unit (node visits vs. loop iterations), the framework limit must be scaled by the ratio of the two units PLUS headroom. Always catch framework-specific termination errors and surface them as clean application-level failures, not uncaught exceptions.

### Learning 2 (Narrow Scope — Routes)
- **error-handling** (`backend/api/routes.py`): When classifying exception types for log-level decisions, use `error_msg.lower()` string matching rather than `isinstance()` on framework error classes. This avoids import coupling to the framework's internal error hierarchy and is more resilient to framework version changes.

---

## 6. Ecosystem Notes

**What worked well:**
- The two-part fix (raise limit + catch exception) was identified immediately from reading the LangGraph error message. Root cause analysis was straightforward.
- The existing exception-handling pattern in `_execute_run` (the `_is_page_closed` branch) provided a clean template — the `GraphRecursionError` branch was added in exactly the same idiom.
- The test file structure followed the existing project convention (`tests/test_task_NNN_*.py`, `@pytest.mark.anyio`) cleanly.

**Minor friction:**
- The initial test file used `@pytest.mark.asyncio` instead of `@pytest.mark.anyio` — the project uses `anyio` but the mark choice is implicit (not enforced by `pyproject.toml`). A `pyproject.toml` entry `asyncio_mode = "auto"` or a `pytest.ini` marker alias would prevent this friction on future async tests.
- The docstring regex in the test was brittle (DOTALL stopped at first `)`) — fixed by switching to an index+window slice approach, which is more robust for multi-line Pydantic field descriptions.

---

## Completed Bug Fix Entry

- [x] [Level 1] Fixed: GraphRecursionError crash — LangGraph `recursion_limit` too low for configured `max_planner_iterations`
  - Issue: `recursion_limit=500` (node visits) fired before `max_planner_iterations=500` guard (loop iterations), crashing with unhandled exception
  - Solution: Raised `recursion_limit` to 3000; added graceful `GraphRecursionError` catch with WARNING log and terminal broadcast
  - Files: `backend/api/routes.py`, `backend/config.py`, `tests/test_task_027_graph_recursion_limit.py`
  - Completed: 2026-05-16
  - Ecosystem Note: Consider adding `anyio_mode = "auto"` to pytest config to avoid `asyncio` vs `anyio` mark confusion on future async tests
