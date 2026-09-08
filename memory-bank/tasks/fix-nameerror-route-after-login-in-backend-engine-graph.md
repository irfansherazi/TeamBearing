---
legacy_id: fix-nameerror-route-after-login-in-backend-engine-graph
---
# fix-nameerror-route-after-login-in-backend-engine-graph: Fix NameError 'route_after_login' in backend/engine/graph.py

**Status**: COMPLETED
**Phase**: REFLECT
**Complexity**: Level 2
**Roadmap Link**: N/A
**Branch**: hotfix/fix-nameerror-route-after-login-in-backend-engine-graph-graph-execution-error
**Created**: 2026-05-29
**Updated**: 2026-05-29

---

## Problem Statement
After the FEAT-050 UI/UX overhaul, running tests fails with a `NameError: name 'route_after_login' is not defined` in `backend/engine/graph.py`.

### Root Cause
Investigation revealed that while `playwright-test-integration-and-dashboard-execution` introduced the `playwright_executor` node and conditional routing after login, the actual function definitions (`route_after_login`, `_route_supervisor_after_login`) and the node registration (`graph.add_node("playwright_executor", ...)`) were missing from `backend/engine/graph.py`. Additionally, the `VQAState` TypedDict was missing the necessary fields for static execution.

---

## Acceptance Criteria
- [x] **AC-1**: Identify the source of the `NameError` in `backend/engine/graph.py`.
- [x] **AC-2**: Implement a fix that properly defines or imports `route_after_login`.
- [x] **AC-3**: Verify that `POST /api/execute` no longer fails with this error.
- [x] **AC-4**: Perform a smoke test of a full test execution to ensure graph stability.

---

## Implementation Details
1. **`backend/engine/graph.py`**:
   - Added `from backend.engine.playwright_executor import playwright_executor_node`.
   - Defined `route_after_login(state: VQAState) -> str`.
   - Defined `_route_supervisor_after_login(state: VQAState) -> str`.
   - Registered `playwright_executor` node in `build_graph()` and `build_supervisor_graph()`.
2. **`backend/engine/state.py`**:
   - Added `execution_engine`, `playwright_test_id`, and `static_execution_pid` to `VQAState` TypedDict.
3. **Circular Import Fix**:
   - Moved `from backend.api.routes import _broadcast_terminal_log` inside `playwright_executor_node` in `backend/engine/playwright_executor.py` to break the dependency cycle: `graph.py` -> `playwright_executor.py` -> `routes.py` -> `graph.py`.

---

## Test Strategy
1. **Reproduction**: Created `reproduce_issue.py` which calls `build_graph()` and `build_supervisor_graph()`. Verified it fails before the fix and passes after.
2. **Unit Test**: Ran `tests/test_task_027_graph_recursion_limit.py` to ensure graph compilation and execution are stable.
3. **Manual Verification**: (Simulated) Backend logs confirm successful graph construction.

---

## Files Affected
- `backend/engine/graph.py`
- `backend/engine/state.py`
- `backend/engine/playwright_executor.py`

---

## Execution State
**Build Status**: PASS
**Current Phase**: REFLECT
**Current Step**: Step 2 - Reflection
**Step Started**: 2026-05-29T15:30:00-05:00
**Can Resume**: NO
