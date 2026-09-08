# Archive: failure-aware-recovery-router — Failure-Aware Recovery Router

**Completed**: 2026-05-11
**Complexity**: Level 4
**Branch**: feature/failure-aware-recovery-router-failure-aware-recovery
**Status**: COMPLETE

## Summary

Replaced the flat retry→HITL→abort failure pipeline in the evaluator with type-specific automatic recovery strategies. The recovery router intercepts 5 Playwright failure categories and applies targeted fixes before burning retry budget: STRICT_MODE (auto-inject container_selector), TIMEOUT (3s stabilization wait), NOT_VISIBLE (parent accordion/tab click), DETACHED (500ms Angular re-render wait), and INTERCEPTED (Escape key / overlay backdrop dismiss). Recovery actions are one-shot per AC step, do not consume retry budget, and fall through to the existing pipeline on failure.

## Files Changed

```
 backend/config.py                                  |  29 ++
 backend/engine/evaluator.py                        |  37 ++
 backend/engine/recovery_router.py                  | 298 ++++++++++++++
 backend/engine/reporter.py                         |  57 +++
 backend/engine/state.py                            |  11 +
 tests/test_recovery_router.py                      | 415 +++++++++++++++++++
```

6 core files changed, ~847 insertions

## Tests Added

- `tests/test_recovery_router.py` — 32 tests covering:
  - Recovery dispatch per failure type (STRICT_MODE, TIMEOUT, NOT_VISIBLE, DETACHED, INTERCEPTED)
  - Feature flag gating (each flag disabled → skip recovery)
  - One-shot gate (recovery_attempted=True → skip)
  - Recovery does not increment fail counts
  - Recovery failure → normal pipeline fallthrough
  - Edge cases: empty planned_action, None inputs, all flags disabled
  - Recovery_attempted reset on step advance

## Key Decisions

1. **Standalone module (`recovery_router.py`)** — Kept recovery logic out of `evaluator.py` to avoid further bloating the 1200+ line evaluator. The router is a pure function that takes state and returns a recovery result.
2. **One-shot per AC step** — Recovery is attempted once per step. If it fails, the normal retry pipeline continues. The `recovery_attempted` flag resets at 4 evaluator transition points (recipe skip, AUTH_GATE re-login, actor switch, step advance).
3. **Free attempt** — Recovery actions do not increment `ac_step_action_fail_count`, preserving the full retry budget for the planner.
4. **5 independent feature flags** — Each recovery type can be disabled individually in `config.py` for safe rollout (`recovery_strict_mode_enabled`, etc., all default to `True`).
5. **Recovery after fast-paths** — Router runs AFTER existing fast-path routes (#0, #0a, #1, #1a, #1b, #2) but BEFORE the generic retry logic, preserving all existing short-circuit behavior.
6. **Reporter integration** — Recovery actions are displayed as a distinct row in the HTML audit report step timeline with a 🔧 icon.

## Linked Artifacts

- Task: memory-bank/tasks/failure-aware-recovery-router.md
- Creative: memory-bank/creative/failure-aware-recovery-router-recovery-router-architecture.md
- Creative: memory-bank/creative/failure-aware-recovery-router-recovery-dispatch-algorithm.md
