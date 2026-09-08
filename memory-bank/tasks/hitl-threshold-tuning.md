---
legacy_id: hitl-threshold-tuning
---
# hitl-threshold-tuning: HITL Threshold Tuning

**Complexity**: Level 2
**Status**: ARCHIVED
**Jira Issue**: N/A
**Issue Type**: Feature
**Priority**: Medium
**Branch**: feature/FEAT-024-hitl-threshold-tuning
**Worktree**: N/A
**Roadmap**: FEAT-024 (v2.0.0)

---

## Task Description

Increase the HITL trigger threshold from 2 to 4 consecutive failures (FM-4), with failure-type-aware exceptions. Some failure types (like INTERCEPTED) should still escalate early, while others (like TIMEOUT or DETACHED) should get more retries.

### Problem (FM-4: Premature HITL Escalation)

Currently, the evaluator node escalates to `human_takeover` after 5 consecutive Playwright action failures. The initial product brief suggested 2, but the actual implementation uses 5. However, it's not failure-type aware.

### Solution: Failure-Type Aware Thresholds

Refine the threshold logic in `evaluator.py`:
1.  **General Threshold**: Increased default to 4 failures (configurable).
2.  **INTERCEPTED**: Escalate at 2 failures (unlikely to self-heal).
3.  **STRICT_MODE**: Escalate at 3 failures (requires human disambiguation).
4.  **TIMEOUT / DETACHED**: Allow full 4-retry budget.

---

## Acceptance Criteria

- [x] AC-HAPPY-1: Default HITL threshold is 4 for most failure types.
- [x] AC-HAPPY-2: `INTERCEPTED` failures trigger HITL after 2 failures.
- [x] AC-HAPPY-3: `STRICT_MODE` failures trigger HITL after 3 failures.
- [x] AC-HAPPY-4: Thresholds are configurable via `config.py`.
- [x] AC-REGRESS-1: No regressions in existing evaluator routing or other circuit breakers.
- [x] AC-REGRESS-2: Ensure `retry_count` is still tracked correctly across AC steps.

---

## Open Questions

⚠️ **Review these before starting the build:**

- [x] Should the "STRICT_MODE" threshold apply to *all* strict mode violations, or only those with high match counts? **Decision**: Apply to all for simplicity and consistency.
- [x] Do we need a separate "AUTO_ESCALATE_THRESHOLD" for vision mode, or should it use the same logic? **Decision**: Use the same logic for now; keep it unified.

---

## Affected Components

- `backend/engine/evaluator.py` — Updated `evaluator_node` to use `_classify_error` and `settings` for dynamic threshold selection.
- `backend/config.py` — Added `hitl_threshold_general`, `hitl_threshold_intercepted`, and `hitl_threshold_strict_mode`.

---

## Test Strategy

### Approach
- **Emphasis**: unit-heavy (evaluator routing logic)
- **Final test count**: 5 tests in `backend/engine/test_hitl_thresholds.py`

### Test Targets
- `evaluator_node` -> verify escalation at 4 failures for TIMEOUT (PASSED).
- `evaluator_node` -> verify escalation at 2 failures for INTERCEPTED (PASSED).
- `evaluator_node` -> verify escalation at 3 failures for STRICT_MODE (PASSED).
- `config.py` -> verify new settings are available and correctly used (PASSED).

---

## Implementation Roadmap

- [x] Phase 1: Config updates — Added threshold settings to `Settings` class in `config.py`.
- [x] Phase 2: Evaluator logic — Refactored `evaluator_node` to use failure-type aware thresholds from config.
- [x] Phase 3: Verification — Added unit tests for the new threshold logic in `backend/engine/test_hitl_thresholds.py`.

---

## Execution State

**Build Status**: ARCHIVED
**Can Resume**: NO
