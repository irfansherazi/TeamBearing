---
slug: cu-loop-default-remove-toggle
legacy_id:
feature:
status: COMPLETE
---

# cu-loop-default-remove-toggle: Make Computer-Use loop the default for all runs and remove the toggle checkbox

**Complexity**: Level 1
**Status**: COMPLETE
**Roadmap**: N/A
**Branch**: task/cu-loop-default-remove-toggle
**Worktree**: N/A (Level 1 uses direct branch, not worktree)
**Reflection**: memory-bank/reflection/cu-loop-default-remove-toggle-reflection.md
**Archived**: memory-bank/archive/cu-loop-default-remove-toggle-archive.md
**Completed**: 2026-08-11

## Task Description

Implement the functionality that the "Use Computer-Use Loop" checkbox does as the default for all runs, and remove the checkbox from the UI.

Concretely: when a user clicks **Start Test** on a Jira ticket, the app should always take the Computer-Use path (POST `/execute-cu`, screenshot → Claude → tool loop). The legacy LangGraph pipeline path (POST `/execute`) is no longer reachable from the ticket-run flow, and the toggle UI is removed.

## Implementation Notes

**Change surface** (single file): `frontend/src/components/RunTestView.tsx`

Concrete edits:
- Delete `useComputerUseLoop` state + persistence effect (currently lines ~153–163, backed by `localStorage["vqa.useComputerUseLoop"]`).
- Delete the checkbox card JSX (lines ~615–645) — the whole `<div>` under the `{/* Computer-Use loop toggle */}` comment.
- Un-condition the CU branch in the run handler (line ~406 `if (useComputerUseLoop) { … }`) — always execute the CU path.
- Delete the "Legacy LangGraph pipeline" block (lines ~443–479) — the `startExecution(req)` call site becomes unreachable.
- Remove `useComputerUseLoop` from the effect deps (line ~212) and the `useCallback` deps array (line ~480).
- Simplify the terminal-message effect (lines ~203–210): drop the `useComputerUseLoop &&` guard — every ticket run is now a CU run, so the save-as-test dialog condition collapses to `terminalMessage.type === 'completed' && activeRunId && !isStaticRunRef.current`.
- Remove the now-unused `startExecution` from the `useExecution()` destructuring at line ~93 (still exported from the hook — leave that alone for now; it might be used elsewhere).

**Deliberately out of scope** (keeps this Level 1):
- `useExecution.ts` — leaving `startExecution` in the hook untouched (could be used by other views; not blocking).
- `backend/api/routes.py` — the `/execute` endpoint is no longer called from the ticket-run flow, but static-test replay and other callers may still use it. Removing it is a separate cleanup task.
- Static-test replay (`handleStaticTestSelected` → POST `/playwright/run`) — orthogonal to this toggle and untouched.
- `isStaticRunRef` gating — still valid; distinguishes CU ticket runs from saved-Playwright-test replays.

**Cleanup after this task lands** — file a follow-up Level 1 to sweep unused `startExecution` / `/execute` if they turn out to be dead everywhere.

**Verification** — this is UI. Confirmation should be:
1. TypeScript compiles cleanly (`npm --prefix frontend run build` or `tsc --noEmit`).
2. Manual browser check: load Run Test view, confirm no checkbox above the run panels, click Start Test on a ticket → POST `/execute-cu` fires (Network tab), Save-as-test dialog appears on success.
3. `localStorage["vqa.useComputerUseLoop"]` becomes ignored (harmless leftover for users who had it set — do NOT clean it up; not worth the code).

---

## Execution State

**Build Status**: IDLE
**Current Phase**: COMPLETE
**Can Resume**: NO

### Active Sub-Agents
(none)

### Completed Steps
- Step 0 Discovery + clean-tree gate: COMPLETE — task branch confirmed; memory-bank clean
- Step 1 Read task context: COMPLETE — Level 1, single-phase, RunTestView.tsx
- Step 3 TDD (RED→GREEN): COMPLETE — 2 regression guard tests added; source edits made; 6 tests GREEN; TS build clean
- Step 7 Integration verify: COMPLETE — full suite 165 pass / 4 pre-existing fail (unrelated); RunTestView 6/6 PASS; build PASS
- Reflection Agent: COMPLETE — Output: memory-bank/reflection/cu-loop-default-remove-toggle-reflection.md (commit 538a7a0)

### Guard & Recovery Log
Phase 1 commit guard PASS: prod=1 (RunTestView.tsx), test=1 (RunTestView.test.tsx).
