# Archive: hitl-threshold-tuning — HITL Threshold Tuning

**Completed**: 2026-05-12
**Complexity**: Level 2
**Branch**: feature/FEAT-024-hitl-threshold-tuning
**Status**: COMPLETE

## Summary
Implemented failure-type aware HITL escalation thresholds to reduce premature human takeovers. Increased the general threshold to 4 failures, while maintaining strictness for `INTERCEPTED` (2) and `STRICT_MODE` (3) errors. 

## Files Changed
- `backend/config.py`: Added `hitl_threshold_general`, `hitl_threshold_intercepted`, and `hitl_threshold_strict_mode`.
- `backend/engine/evaluator.py`: Refactored `evaluator_node` to select thresholds dynamically based on error classification.
- `backend/engine/test_hitl_thresholds.py`: Added 5 unit tests for the new logic.

## Tests Added
- `backend/engine/test_hitl_thresholds.py`:
    - `test_hitl_general_threshold_escalates_at_4`
    - `test_hitl_intercepted_threshold_escalates_at_2`
    - `test_hitl_strict_mode_threshold_escalates_at_3`
    - `test_hitl_timeout_below_threshold_does_not_escalate`
    - `test_hitl_thresholds_configurable`

## Key Decisions
- **Unified Vision Threshold**: Decided to use the same logic for vision mode auto-escalation to keep the system simple and consistent.
- **Strict Mode Threshold**: Applied the 3-failure threshold to all `STRICT_MODE` violations for consistency.

## Linked Artifacts
- Task: memory-bank/tasks/hitl-threshold-tuning.md
- Reflection: memory-bank/reflection/reflection-hitl-threshold-tuning.md
