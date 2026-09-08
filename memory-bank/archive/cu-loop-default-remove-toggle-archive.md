---
slug: cu-loop-default-remove-toggle
legacy_id:
feature:
status: COMPLETE
completed: 2026-08-11
complexity: 1
---

# Archive: cu-loop-default-remove-toggle

**Task**: Make Computer-Use loop the default for all runs and remove the toggle checkbox
**Complexity**: Level 1
**Completed**: 2026-08-11
**Branch**: task/cu-loop-default-remove-toggle

## Summary

Removed the `useComputerUseLoop` opt-in toggle from `RunTestView.tsx` and unconditionally routed all ticket-run starts through POST `/execute-cu` (screenshot → Claude → tool loop). The legacy LangGraph pipeline call site was deleted from the ticket-run flow; the `/execute` backend endpoint and `startExecution` hook export were deliberately left in place per the task's out-of-scope fence (follow-up sweep task).

## Change Set

- **Files touched**: 2
  - `frontend/src/components/RunTestView.tsx` (production, net −159 LOC)
  - `frontend/src/components/__tests__/RunTestView.test.tsx` (tests, +71 LOC — 4 updated for CU-only path + 2 regression guards)
- **Commits on branch**:
  - `254c92b` task: create Level 1 task file
  - `3228620` feat: make Computer-Use the default run path, remove toggle
  - `538a7a0` reflect: two-dimensional reflection
  - `6fb7b95` chore: mark REFLECTION_COMPLETE

## Verification

- `tsc -b` + `vite build`: PASS (0 errors, 299ms)
- RunTestView test suite: 6/6 PASS
- Full frontend suite: 165/171 (4 pre-existing failures in AppShell/ExecutionLog/SelectView — unrelated, not regressions)
- Lint: N/A (no `lint` script in `frontend/package.json` — flagged as ecosystem gap)
- Commit-guard: PASS first attempt (prod=1, test=1)

## Extractable Learnings Consolidated

- `testing-patterns.md` — appended regression-guard-for-ui-deletion pattern (evidence 1x)
- `frontend-patterns.md` — appended transitive-unused-var-cleanup-bundling pattern (evidence 1x)

Both learnings additive; no rules merged, retired, expired, or pruned. Consolidation is **additive**, not mutating.

## Follow-Up

- Level 1 sweep: verify no remaining consumers of `startExecution` (in `useExecution.ts`) or the `/execute` backend endpoint; if unused everywhere, delete both.
- No behavioral coverage of the CU flow was added — regression guards only assert deleted elements stay deleted. If the CU path breaks, existing higher-level tests would need to catch it.

## Advisory: ux-patterns.md Freshness

Task touched UI files (`RunTestView.tsx`). `memory-bank/ux-patterns.md` last updated 2026-06-04. This task was strictly subtractive (removed one toggle) — no new component patterns introduced — so no ux-patterns refresh is required. Recording here per the archive soft-check.
