# Archive: action-history-buffer — Action History Buffer

**Completed**: 2026-05-11
**Complexity**: Level 3
**Branch**: feature/action-history-buffer-action-history-buffer
**Status**: COMPLETE

## Summary

Implemented a structured rolling buffer of the last 5 failed actions injected as a `<past_actions>` XML block into the planner system prompt. The buffer enforces a hard constraint: "NEVER repeat a strategy that appears in `<past_actions>` with outcome=FAILED." This eliminates amnesic retry loops (FM-1) where the planner previously forgot what it already tried and re-attempted the same broken locator strategies across iterations.

Key implementation:
- Added `action_history_buffer: list[dict]` field to `VQAState` (plain field, evaluator overwrites full list)
- Evaluator appends structured entries on `success=False` with keys: action, strategy, target, error_type, iteration
- Buffer capped at 5 entries (FIFO eviction); cleared when `ac_step_index` advances
- Planner injects `<past_actions>` XML block into `<context>` section when buffer is non-empty
- Wired into both `_build_system_prompt` (v1) and `_build_system_prompt_v2` (v2) codepaths

## Files Changed

```
 backend/engine/state.py      — action_history_buffer field added to VQAState
 backend/engine/evaluator.py  — append on failure + cap at 5; clear on AC step advance (6 paths)
 backend/engine/planner.py    — _build_past_actions_block() + injection into both prompt variants
 tests/test_action_history_buffer.py — 10 unit tests (all passing)
```

81 files changed total on branch (includes .agent/workflows scaffolding, prior FEAT work).
Core action-history-buffer changes: 4 files (3 engine + 1 test).

## Tests Added

- `tests/test_action_history_buffer.py` — 10 tests covering:
  - `_build_past_actions_block()` — empty buffer → empty string; non-empty → correct XML
  - Buffer capping logic — 6th entry evicts oldest (FIFO)
  - Buffer clearing on AC step advance
  - Evaluator appends correct structured entry on failure
  - Integration: full evaluator_node failure path populates buffer correctly

## Key Decisions

1. **Evaluator-owned buffer (not planner-owned)**: The evaluator is the natural owner because it already processes action outcomes and has direct access to failure classification data. This avoids coupling the planner to execution results.
2. **Plain list field (no `operator.add` annotation)**: The evaluator overwrites the full list on each update rather than using LangGraph's reducer pattern. This simplifies the capping logic and avoids merge conflicts in the state graph.
3. **Rolling window of 5**: Small enough to fit within prompt budget constraints; large enough to capture the typical 3-5 retry pattern before `human_takeover` triggers.
4. **Clear on AC step advance**: A new acceptance criterion step is a fresh context — past failures on step N are irrelevant to step N+1.
5. **Supplements, not replaces, failure diary**: The existing `ac_step_failure_diary` continues to work unchanged. The buffer adds structured deduplication on top of the free-text suggestions.

## Linked Artifacts

- Task: memory-bank/tasks/action-history-buffer.md
- Reflection: memory-bank/reflection/reflection-action-history-buffer.md (if exists)
- Creative: memory-bank/creative/action-history-buffer-action-history-buffer-architecture.md
- Creative: memory-bank/creative/action-history-buffer-action-history-buffer-algorithm.md
- Roadmap Feature: FEAT-020 (v2.0.0)
