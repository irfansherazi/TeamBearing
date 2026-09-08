# Archive: Fix reporter.py — COVERAGE_GAP Steps Incorrectly Show as PASSED

## Metadata
- **Task ID**: fix-reporter-coverage-gap-steps-incorrectly-show-as-passed
- **Complexity**: Level 1
- **Branch**: `hotfix/fix-reporter-coverage-gap-steps-incorrectly-show-as-passed-coverage-gap-reporter-fix`
- **Commits**: `471d4a5` (fix), `15a0cb7` (reflection + learned rule)
- **Completed**: 2026-05-21
- **Duration**: ~6 minutes (09:01 → 09:07 CST)

## Summary

Fixed a false-positive reporting defect in `backend/engine/reporter.py` where AC steps carrying a `COVERAGE_GAP` bug entry were incorrectly rendered as **passed** in the vQA HTML audit report — both in the report header badge and in the AC steps table.

**Root cause**: The evaluator's `done` handler appends an AC step index to `ac_steps_completed` regardless of whether the step was actually executed or hit a coverage gap. Both reporter functions blindly trusted `ac_steps_completed` membership without cross-referencing `bug_log` for `COVERAGE_GAP` entries.

## Solution

**Bug A — `_render_header`**: Extracted a `coverage_gap_indices` set from `bug_log` and used set subtraction (`_completed_set - coverage_gap_indices`) to compute the corrected pass count. Added `len(coverage_gap_indices) == 0` guard to `all_passed`.

**Bug B — `_render_ac_table`**: Added a priority-first check (`if i in coverage_gap_indices`) before the existing `if i in completed` check, so gap status always overrides `completed` membership and renders the row as ✗ / `fail`.

## Files Changed
- `backend/engine/reporter.py` — `_render_header` (Bug A fix) and `_render_ac_table` (Bug B fix)
- `tests/test_reporter_coverage_gap.py` — 10 new unit tests covering all 6 ACs and edge cases
- `memory-bank/agent-rules/_learned/testing-patterns.md` — Added `reporter-priority-override-test` learned rule

## Test Results
- **New tests**: 10/10 PASS
- **Regression suite**: 87/87 PASS (zero regressions)

## Key Learnings / Notes

1. **Priority-first conditional pattern**: When a reporter function's pass/fail logic must respect a priority ordering (e.g., `COVERAGE_GAP` overrides `completed` membership), write an explicit test for the priority-override case — a gap index that is *also* in `completed` — to prove the guard order is correct.

2. **Evaluator contract debt**: The root cause is that `ac_steps_completed` doesn't encode *why* a step is "done". A future task could add `ac_steps_coverage_gap: list[int]` to `VQAState` to make this distinction explicit at the state layer, removing the need for the reporter to re-derive it from `bug_log`.

3. **Phase gate vs. level12 conflict**: The `/vc-archive` phase gate unconditionally requires a reflection doc even for Level 1 tasks, while `level12-archive.md` marks reflection as optional. The phase gate currently wins. Recommend aligning these in a future system update.

## Evidence
- Run `run-1b6e49c7` (QA-298, Account Executive): all 4 steps showed ✓ with `COVERAGE_GAP` in bug log → now correctly shows FAILED ✗ and 3/4 passed.
