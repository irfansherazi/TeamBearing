---
legacy_id: fix-reporter-coverage-gap-steps-incorrectly-show-as-passed
---
# fix-reporter-coverage-gap-steps-incorrectly-show-as-passed: Fix reporter.py — COVERAGE_GAP steps incorrectly show as PASSED

**Complexity**: Level 1
**Status**: COMPLETE
**Jira Issue**: N/A
**Issue Type**: Bug
**Priority**: Medium
**Branch**: hotfix/fix-reporter-coverage-gap-steps-incorrectly-show-as-passed-coverage-gap-reporter-fix
**Worktree**: N/A
**Roadmap**: N/A

---

## Task Description

The vQA HTML audit report generator (`backend/engine/reporter.py`) incorrectly treats AC steps that carry a `COVERAGE_GAP` bug entry as **passed**, resulting in two visible defects in the generated report:

1. **Report header shows "PASSED ✓" and "4/4 passed"** even when one or more AC steps were never executed (coverage gap detected).
2. **AC table shows ✓ for steps that have a COVERAGE_GAP** — the table row renders with the `pass` CSS class and a ✓ icon instead of ✗.

### Root Causes

**Bug A — `_render_header` (line ~96):**  
`all_passed` is computed by checking whether every AC step index appears in `ac_steps_completed`:
```python
all_passed = (
    len(ac_steps) > 0
    and all(i in _completed_set for i in range(len(ac_steps)))
)
```
A `COVERAGE_GAP` step still gets appended to `ac_steps_completed` (the evaluator's last-step `done` handler adds `ac_index` regardless of gaps), so all indices appear present and `all_passed` is `True`. The function never inspects `bug_log` for `COVERAGE_GAP` entries.

**Bug B — `_render_ac_table` (line ~209):**  
```python
if i in completed:
    icon = "✓"
    status_class = "pass"
```
The table renders ✓ for any index that appears in `completed`. Since COVERAGE_GAP indices are still in `completed`, the row incorrectly renders as passing.

### Evidence
From run `run-1b6e49c7` (QA-298, Account Executive):
- AC table: all 4 steps show ✓
- Header: "PASSED ✓", "4/4 passed"  
- Bug registry: `[COVERAGE_GAP] AC step 4/4 was never executed`

### Expected Behavior
- Steps with a `COVERAGE_GAP` bug entry render as ✗ (fail) in the AC table.
- The header `all_passed` check excludes COVERAGE_GAP indices.
- The "X/4 passed" count subtracts COVERAGE_GAP steps.
- The overall badge reads "FAILED ✗" when any COVERAGE_GAP exists.

---

## Acceptance Criteria

- **AC-HAPPY-1**: When `bug_log` contains a `COVERAGE_GAP` entry for AC step index `N`, the report header badge shows "FAILED ✗" (red).
- **AC-HAPPY-2**: When `bug_log` contains a `COVERAGE_GAP` for step `N`, the "AC Steps" meta shows `(total - gap_count)/(total) passed`, e.g., "3/4 passed" not "4/4 passed".
- **AC-HAPPY-3**: In the AC table, any step index that appears in a `COVERAGE_GAP` bug entry renders with the `fail` CSS class and ✗ icon, even if that index is also in `ac_steps_completed`.
- **AC-HAPPY-4**: Runs with zero `COVERAGE_GAP` entries continue to compute `all_passed` and render the AC table exactly as before (no regression).
- **AC-REGRESS-1**: Existing unit tests for `_render_header` and `_render_ac_table` (if any) continue to pass.
- **AC-REGRESS-2**: Skipped steps (in `ac_steps_skipped`) still render with the `skip` CSS class and ⊘ icon, unaffected by this change.

---

## Open Questions

None — task is well-defined.

---

## Affected Components

- `backend/engine/reporter.py` — `_render_header` function (line ~85) and `_render_ac_table` function (line ~180). Both need to extract a `coverage_gap_indices` set from `bug_log` and use it to override pass/fail logic.

---

## Test Strategy

### Approach
- **Emphasis**: unit-heavy
- **Target test count**: 4–6 unit tests

### Test Targets
- `_render_header` with a state containing a `COVERAGE_GAP` bug entry → assert "FAILED ✗" badge and correct "3/4 passed" count.
- `_render_header` with a state containing **no** `COVERAGE_GAP` entries → assert "PASSED ✓" and "4/4 passed" (no regression).
- `_render_ac_table` with a COVERAGE_GAP at index 3 → assert the 4th row contains `class="fail"` and `✗`.
- `_render_ac_table` with no gaps → assert all rows pass (no regression).
- Edge case: COVERAGE_GAP at index 0 (first step) → header and table both fail correctly.

### What NOT to Test
- Other bug types (UI, LOGIC, API, etc.) — they must NOT affect `all_passed` or the AC table icons.
- `_render_bug_log` — unrelated to this fix.
- Executor/evaluator logic that writes `COVERAGE_GAP` to `bug_log` — already tested upstream.

---

## Implementation Roadmap

- [x] Phase 1: In `_render_header`, extract `coverage_gap_indices = {b["ac_step_index"] for b in state.get("bug_log", []) if b.get("type") == "COVERAGE_GAP"}`. Subtract from `_completed_set` when computing `all_passed` and `_unique_completed`.
- [x] Phase 2: In `_render_ac_table`, extract the same `coverage_gap_indices`. Add a priority check: if `i in coverage_gap_indices`, render as fail (✗) regardless of `completed` membership.
- [x] Phase 3: Write/update unit tests in `tests/` to cover the new behavior per the test strategy above.
- [x] Phase 4: Verify the fix manually against the evidence run (run-1b6e49c7 scenario) using a synthetic state dict.

---

## Execution State

**Build Status**: IDLE
**Phase Being Built**: COMPLETE
**Phase Number**: 4 of 4
**Is Multi-Phase**: YES
**Build Started**: 2026-05-21T09:01:23-05:00
**Build Completed**: 2026-05-21T09:07:14-05:00
**Reflection Completed**: 2026-05-21T09:31:00-05:00
**Archived**: 2026-05-21T09:44:00-05:00
**Branch**: `hotfix/fix-reporter-coverage-gap-steps-incorrectly-show-as-passed-coverage-gap-reporter-fix`
**Commit**: `471d4a5`
**Current Phase**: ARCHIVE
**Status**: COMPLETE

### Active Sub-Agents
(none — Level 1 inline execution)

### Completed Steps
- Step 0: Parse Task ID ✓
- Step 1: Read Task Context ✓
- Step 2: Load Level 1 rules ✓
- Step 3-4: Fix `_render_header` (Bug A) ✓
- Step 3-4: Fix `_render_ac_table` (Bug B) ✓
- Step 5: Write 10 unit tests ✓
- Step 6: All 10 tests PASS ✓
- Step 7: Regression suite (87 tests) PASS ✓
- Step 11: Committed to `hotfix/fix-reporter-coverage-gap-steps-incorrectly-show-as-passed-coverage-gap-reporter-fix` ✓
- Reflect: reflection-fix-reporter-coverage-gap-steps-incorrectly-show-as-passed.md created ✓
- Learned: `reporter-priority-override-test` added to testing-patterns.md ✓
