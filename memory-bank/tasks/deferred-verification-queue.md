---
legacy_id: deferred-verification-queue
---
# deferred-verification-queue: Deferred Verification Queue

**Complexity**: Level 3
**Status**: REFLECTION_COMPLETE
**Jira Issue**: N/A
**Issue Type**: Feature
**Priority**: High
**Branch**: feature/deferred-verification-queue-deferred-verification
**Worktree**: N/A
**Roadmap**: FEAT-023 (v2.0.0)

---

## Task Description

Replace verifier auto-satisfy bypasses (transient selector blocklist, sparse dataset bypass) with queued "soft assertions" that are re-checked N steps later. If a soft assertion fails its deferred re-check, the step that was auto-satisfied is flagged in the audit report as a **deferred verification failure** (DVF).

### Problem (FM-3: False-Positive Step Advancement)

The current verifier has two mechanisms that auto-satisfy steps without actually verifying the expected state:

1. **Transient Selector Blocklist** (`_TRANSIENT_PATTERNS` in `verifier.py:325-356`): When `element_visible` targets a transient element (e.g., `p-select-overlay`, `sort-panel`, `p-menu-list`), the verifier immediately returns `"satisfied"` because the element closes before the verifier fires. The assumption is that the action itself confirms success — but this is wrong when the action _silently failed_ (e.g., wrong option selected, panel didn't open at all).

2. **Sparse Dataset Bypass** (`verifier.py:681-754`): When PrimeNG `p-table` has ≤2 visible rows, sort verification is auto-satisfied because PrimeNG suppresses `aria-sort` and sort icons on trivially small result sets. The sort _is_ applied, but there's no confirmation that the _correct_ column was sorted.

Both bypasses cause **false-positive step advancement**: the verifier says "SATISFIED" when the underlying assertion was never actually checked. If the action silently failed, subsequent AC steps that depend on the auto-satisfied step cascade into failures that are hard to diagnose.

### Solution: Deferred Verification Queue (DVQ)

Instead of auto-satisfying, the verifier:
1. Records the bypass as a **soft assertion** in a new `deferred_verification_queue` field on `VQAState`
2. Returns `"satisfied"` with a `deferred=True` marker so the run continues
3. After N steps (configurable, default 2), the evaluator triggers a **deferred re-check** before advancing to the next step
4. The re-check evaluates the soft assertion against the _current_ page state
5. If the re-check passes → no action needed (the bypass was correct)
6. If the re-check fails → the step is flagged as a **DVF** in the audit report, and a limited backtrack (max 2 steps) is considered

### Backtrack Mechanism

When a deferred re-check fails:
- The DVF is recorded in a new `deferred_verification_failures` list on `VQAState`
- **If within backtrack limit (2 steps from the deferred step)**: The evaluator sets `ac_step_index` back to the deferred step and re-attempts it with the verifier running in strict mode (no auto-satisfy)
- **If beyond backtrack limit**: The step is flagged as a DVF in the report but execution continues forward (no backtrack — too much state has changed)
- Backtrack limit is configurable via `config.py`

---

## Acceptance Criteria

- [x] AC-HAPPY-1: When `element_visible` matches a transient selector pattern, the verifier returns `"satisfied"` AND enqueues a soft assertion in `deferred_verification_queue` instead of only auto-satisfying
- [x] AC-HAPPY-2: After N steps (default 2), the evaluator checks all pending soft assertions whose `check_after_step` has been reached
- [x] AC-HAPPY-3: A soft assertion re-check that PASSES is silently removed from the queue with a debug-level log
- [x] AC-HAPPY-4: A soft assertion re-check that FAILS is recorded in `deferred_verification_failures` and triggers backtrack if within the 2-step limit
- [x] AC-HAPPY-5: Sparse dataset bypass (`table_sort` with ≤2 rows) also enqueues a deferred re-check instead of only auto-satisfying
- [x] AC-HAPPY-6: The HTML audit report renders DVFs with a distinct visual indicator (e.g., amber warning badge, different from red FAILED and green PASSED)
- [x] AC-HAPPY-7: DVQ is feature-flagged via `config.py` (`enable_deferred_verification: bool = True`) — when disabled, the old auto-satisfy behavior is preserved exactly
- [x] AC-HAPPY-8: Deferred re-checks attempt a robust verification by evaluating the next AC step's precondition and verifying if the previous action's result is persistent in the DOM.
- [x] AC-ERROR-1: When a backtrack is triggered but the re-attempt also fails, the step is marked as DVF-CONFIRMED and execution continues forward (no infinite backtrack loops)
- [x] AC-ERROR-2: Deferred queue entries are cleared when `ac_step_index` advances beyond `check_after_step + backtrack_limit` to prevent stale entries accumulating
- [x] AC-ERROR-3: Backtracked steps inherit the previous `retry_count` rather than resetting the budget.
- [x] AC-REGRESS-1: No regressions in existing verifier tests (transient selector auto-satisfy still works correctly when DVQ is disabled)
- [x] AC-REGRESS-2: No regressions in evaluator routing — step advancement, HITL escalation, and per-step budget logic all function identically
- [x] AC-REGRESS-3: Existing reporter HTML output is unchanged for runs that don't trigger any DVFs

---

## Open Questions

⚠️ **Review these before starting the build:**

- [x] Should the deferred re-check use the same verification type (e.g., `element_visible`) or should it attempt a more robust check? **Decision**: It should attempt a more robust check (verifying the *result* of the action).
- [x] For transient selector bypasses, what *persistent* DOM state should the re-check verify? **Decision**: The next AC step's precondition and verifying if the previous step was successful.
- [x] Should backtrack reset `retry_count` for the re-attempted step, or should it inherit the previous retry budget? **Decision**: It should inherit the previous retry budget.
- [x] Is 2 steps the right default for `check_after_step` delay? **Decision**: Yes, 2 steps is good.

None — all initial questions resolved.

---

## Affected Components

- `backend/engine/verifier.py` — Replaced auto-satisfy returns in `_check_single_verification()` with DVQ enqueue calls.
- `backend/engine/evaluator.py` — Added robust re-check logic and backtrack mechanism with retry inheritance.
- `backend/engine/state.py` — Added `deferred_verification_queue` and `deferred_verification_failures` fields.
- `backend/engine/reporter.py` — Added amber DVF badge rendering to HTML audit report.
- `backend/config.py` — Added DVQ feature flag and settings.

---

## Test Strategy

### Approach
- **Emphasis**: unit-heavy (verifier enqueue logic, evaluator re-check logic, state schema)
- **Target test count**: 12-15 tests (Final count: 37 tests)

### Test Targets
- `_check_single_verification()` → verify transient selector match enqueues DVQ entry AND returns satisfied (PASSED)
- `_check_single_verification()` → verify sparse dataset bypass enqueues DVQ entry AND returns satisfied (PASSED)
- Evaluator step-advancement → verify deferred re-check fires when `check_after_step` reached (PASSED)
- Evaluator backtrack → verify `ac_step_index` rewinds when re-check fails within limit (PASSED)
- Evaluator backtrack → verify NO backtrack when re-check fails beyond limit (DVF recorded only) (PASSED)
- Evaluator → verify DVQ entries are cleared when they expire (step advanced past check window) (PASSED)
- Config → verify `enable_deferred_verification=False` preserves original auto-satisfy behavior (PASSED)
- Reporter → verify DVF section renders with amber badge for runs with deferred failures (PASSED)
- Reporter → verify NO DVF section renders for runs without deferred failures (PASSED)
- State schema → verify `deferred_verification_queue` field exists and accepts list[dict] (PASSED)
- AC-HAPPY-8: Robust look-ahead verification (PASSED)
- AC-ERROR-3: Retry count inheritance (PASSED)

---

## Implementation Roadmap

- [x] Phase 1: State schema + config — Add DVQ fields to `VQAState`, add feature flag + settings to `config.py`
- [x] Phase 2: Verifier enqueue — Replace auto-satisfy returns in `_check_single_verification()` with DVQ enqueue + satisfied return
- [x] Phase 3: Evaluator re-check — Add deferred re-check logic in evaluator step-advancement path
- [x] Phase 4: Evaluator backtrack — Implement conditional backtrack when deferred re-check fails
- [x] Phase 5: Reporter DVF section — Add amber DVF badge rendering to HTML audit report
- [x] Phase 6: Integration + regression — Verify feature-flag toggle, ensure no regressions

---

## Execution State

**Build Status**: ARCHIVED
**Can Resume**: NO
