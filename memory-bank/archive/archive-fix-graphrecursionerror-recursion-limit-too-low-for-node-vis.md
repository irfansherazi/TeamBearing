# Archive: Fix GraphRecursionError — recursion_limit Too Low for Node-Visit Count

## Metadata

- **Task ID**: fix-graphrecursionerror-recursion-limit-too-low-for-node-vis
- **Complexity**: Level 1 (Bug Fix)
- **Priority**: High
- **Completed**: 2026-05-16
- **Branch**: main (committed directly — Level 1 task, no feature worktree)
- **Commits**:
  - `bddff0f` — `fix(fix-graphrecursionerror-recursion-limit-too-low-for-node-vis): increase recursion_limit to 3000 and catch GraphRecursionError gracefully`
  - `1888a7a` — `chore(fix-graphrecursionerror-recursion-limit-too-low-for-node-vis): add task reflection and update learned error-handling rules`
- **Reflection**: `memory-bank/reflection/reflection-fix-graphrecursionerror-recursion-limit-too-low-for-node-vis.md`

---

## Summary

The vQA backend was crashing with `GraphRecursionError: Recursion limit of 500 reached without hitting a stop condition` during long test runs (observed during `run-4c0e9194` at AC step 34/40, planner iteration ~130).

**Root cause**: A unit mismatch between two limits configured at the same value:
- `max_planner_iterations = 500` — the evaluator's guard checks **planner loop iterations**
- `recursion_limit = 500` — LangGraph's hard stop counts **graph node visits** (~5 per loop)

With ~5 node visits per planner cycle, a 500-iteration budget requires ~2,500 node visits. Setting both to 500 caused LangGraph's hard stop to fire 5× before the application's own safety guard, producing an unhandled exception that left WebSocket clients with no terminal message.

---

## Solution

### Fix 1 — Raise `recursion_limit` to 3000 (`backend/api/routes.py`)

```python
config={
    "recursion_limit": 3000,  # was 500
    "max_concurrency": 1,
}
```

Formula: `500 iterations × 5 node-visits/cycle = 2500 + headroom → 3000`

### Fix 2 — Graceful `GraphRecursionError` catch (`backend/api/routes.py`)

Added a catch branch in `_execute_run`:
- Classified alongside `TargetClosedError` as a **known non-fatal variant**
- Logged at `WARNING` (no `exc_info=True` — avoids 80-line tracebacks)
- Broadcasts a `failed` `WSTerminalMessage` to WebSocket clients with a clear error string

```python
_is_recursion_limit = "graphrecursionerror" in error_msg.lower()
if _is_recursion_limit:
    logger.warning("[%s] Graph halted — recursion limit reached ...", run_id, str(e)[:160])
```

### Fix 3 — Docstring clarification (`backend/config.py`)

Updated `max_planner_iterations` field description to include a NOTE explaining the node-visit vs. planner-iteration distinction, preventing future misconfiguration.

---

## Files Changed

| File | Change |
|------|--------|
| `backend/api/routes.py` | `recursion_limit` raised 500→3000; `GraphRecursionError` catch block added |
| `backend/config.py` | `max_planner_iterations` docstring updated with node-visit NOTE |
| `tests/test_task_027_graph_recursion_limit.py` | New — 5 regression tests, all passing |
| `memory-bank/tasks/fix-graphrecursionerror-recursion-limit-too-low-for-node-vis.md` | Task file created and maintained |
| `memory-bank/reflection/reflection-fix-graphrecursionerror-recursion-limit-too-low-for-node-vis.md` | Reflection document |
| `memory-bank/agent-rules/_learned/error-handling.md` | 2 new rules added |

---

## Test Results

```
5/5 tests passing — tests/test_task_027_graph_recursion_limit.py

AC-HAPPY-1  recursion_limit ≥ 6× max_planner_iterations          ✅ PASS
AC-HAPPY-2  GraphRecursionError → failed terminal broadcast        ✅ PASS
AC-ERROR-1  GraphRecursionError logged at WARNING (no exc_info)   ✅ PASS
AC-REGRESS-1 max_planner_iterations docstring mentions node-visits ✅ PASS
(5th test: exact value check recursion_limit == 3000)              ✅ PASS
```

---

## Key Learnings (Extracted to `error-handling.md`)

1. **Framework-level hard limits must be scaled by unit ratio** — When a framework limit and an application safety cap measure different units, configure the framework limit as `app_cap × unit_ratio + headroom`. Always catch the framework's termination exception and surface it as a clean application-level failure.

2. **String-match exception classification in broad handlers** — Use `error_msg.lower()` string matching instead of `isinstance()` against framework-internal error classes to avoid import coupling and stay resilient to framework version changes.

---

## Notes

- This bug was exposed by long production test runs (40+ AC steps with many self-heal retries). Shorter runs are unlikely to hit the node-visit ceiling.
- The fix is purely additive — no behavior change for runs that complete normally.
- The `recursion_limit=3000` value is formula-derived and documented inline in `routes.py` comments for future maintainers.
- Ecosystem note captured in reflection: consider adding `asyncio_mode = "auto"` to `pyproject.toml` to eliminate `pytest.mark.asyncio` vs `pytest.mark.anyio` confusion in future async test files.
