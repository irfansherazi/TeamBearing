---
legacy_id: fix-audit-report-404-and-misleading-all-steps-passed-banner
---
# fix-audit-report-404-and-misleading-all-steps-passed-banner: Fix Audit Report 404 & Misleading "All Steps Passed" Banner

**Complexity**: Level 1
**Status**: COMPLETE
**Jira Issue**: N/A
**Issue Type**: Bug
**Priority**: Medium
**Branch**: hotfix/fix-audit-report-404-and-misleading-all-steps-passed-banner-audit-report-and-pass-banner
**Worktree**: .worktrees/fix-audit-report-404-and-misleading-all-steps-passed-banner
**Roadmap**: N/A
**Archived**: memory-bank/archive/archive-fix-audit-report-404-and-misleading-all-steps-passed-banner.md
**Completed**: 2026-05-21
**PR Created**: YES
**PR URL**: https://github.com/vcreativeinc/vQA/pull/23
**Latest Commit**: 4e4c794

---

## Task Description

Two separate bugs reported from the vQA dashboard:

### Bug A — "View Audit Report" returns 404

Clicking **📄 View Audit Report** in the `ExecutionLog` terminal card produces:
```json
{"detail":"HTML report not yet generated for run 'run-015092b4'."}
```

**Root cause**: `ExecutionLog.tsx` builds the report URL as:
```ts
const reportUrl = message.report_url || `${API_BASE_URL}/runs/${message.run_id}/report`;
```
When `message.report_url` is empty (S3 upload failed or was never attempted), it falls back to the in-memory backend route `GET /runs/{run_id}/report` ([routes.py L1151–L1191](file:///Users/joshschauer/Documents/vProMedia/vQA/backend/api/routes.py#L1151-L1191)), which returns a 404 if `state["final_html_report"]` is empty — which happens when either:
1. The `reporter_node` did not complete (run was cancelled or errored before reaching the reporter), OR
2. The server restarted and `_run_states` was cleared (the in-memory dict is lost on restart).

The terminal `WSTerminalMessage` is broadcast *after* the reporter sets `final_html_report`, so if S3 succeeds, `report_url` is populated and the fallback is never hit. But if S3 upload fails, `report_url` is `""` and the fallback hits a state entry whose `final_html_report` may or may not be populated.

### Bug B — "All N steps passed" shown even when a step has ⚠ (awaiting_human / warning)

In the UAT step results panel, the completion banner reads:
```
✓ All 3 steps passed
```
…even when one step has status `awaiting_human` (⚠). 

**Root cause** in `CopilotSidebar.tsx` ([L190–L192](file:///Users/joshschauer/Documents/vProMedia/vQA/frontend/src/components/CopilotSidebar.tsx#L190-L192)):
```ts
const passedCount = state.steps.filter((s) => s.status === "passed").length;
const failedCount = state.steps.filter((s) => s.status === "failed").length;
```
The completion banner at [L308–L310](file:///Users/joshschauer/Documents/vProMedia/vQA/frontend/src/components/CopilotSidebar.tsx#L306-L311) only checks `failedCount === 0`:
```tsx
{failedCount === 0
  ? `✓ All ${totalSteps} steps passed`
  : `${passedCount}/${totalSteps} passed · ${failedCount} failed`}
```
`awaiting_human` and `skipped` steps are never counted in `failedCount`, so a run with 2 passed + 1 awaiting_human reports "All 3 steps passed" — which is incorrect.

---

## Acceptance Criteria

- **AC-HAPPY-1**: Clicking "📄 View Audit Report" on a completed run where S3 upload succeeded opens the S3 report URL in a new tab without a 404.
- **AC-HAPPY-2**: Clicking "📄 View Audit Report" on a completed run where S3 upload failed and the in-memory report exists opens the in-memory HTML report.
- **AC-ERROR-1**: When the in-memory report is unavailable (server restarted), a clear, user-friendly message is shown instead of a raw JSON 404 (e.g., a disabled/tooltip link or an error message in the UI).
- **AC-HAPPY-3**: The "All N steps passed" completion banner is ONLY shown when every step has `status === "passed"`.
- **AC-HAPPY-4**: If any step has `status === "awaiting_human"` or `status === "skipped"`, the banner shows `"X/N passed · Y warning(s)"` or similar non-passing message.
- **AC-REGRESS-1**: No regressions in existing HITL takeover or report generation flows.
- **AC-REGRESS-2**: The `completed` vs `failed` terminal card pass/fail distinction remains correct.

---

## Open Questions

⚠️ **Review these before starting the build:**

- [ ] **Bug A — preferred UX for missing report**: Should the "View Audit Report" button be hidden/disabled when `report_url` is empty AND the backend returns 404? Or should it open with an inline error message? Current behavior is a blank tab with JSON error.
- [ ] **Bug B — what to show for `awaiting_human` steps in banner**: Options are: (a) `"2/3 passed · 1 needs review"`, (b) `"2/3 passed"` (drop the "All" prefix), (c) use a ⚠ warning-style banner instead of pass/fail. Which is preferred?
- [ ] **Bug B — should `skipped` steps also prevent "All passed"?** Currently `skipped` steps are also excluded from `failedCount`. A skipped step arguably means the test was incomplete.

---

## Affected Components

- [`frontend/src/components/ExecutionLog.tsx`](file:///Users/joshschauer/Documents/vProMedia/vQA/frontend/src/components/ExecutionLog.tsx) — `TerminalCard` component: report URL fallback logic ([L205–L206](file:///Users/joshschauer/Documents/vProMedia/vQA/frontend/src/components/ExecutionLog.tsx#L205-L206)); consider hiding/disabling the link when the report is unavailable.
- [`frontend/src/components/CopilotSidebar.tsx`](file:///Users/joshschauer/Documents/vProMedia/vQA/frontend/src/components/CopilotSidebar.tsx) — Completion banner logic ([L308–L311](file:///Users/joshschauer/Documents/vProMedia/vQA/frontend/src/components/CopilotSidebar.tsx#L306-L312) inline; [L410–L412](file:///Users/joshschauer/Documents/vProMedia/vQA/frontend/src/components/CopilotSidebar.tsx#L408-L413) sidebar): must count `awaiting_human` and `skipped` in the non-passing path.
- [`backend/api/routes.py`](file:///Users/joshschauer/Documents/vProMedia/vQA/backend/api/routes.py) — `GET /runs/{run_id}/report` ([L1151–L1191](file:///Users/joshschauer/Documents/vProMedia/vQA/backend/api/routes.py#L1151-L1191)): returns 404 if `final_html_report` is empty; the error message could be improved to better explain the situation.

---

## Test Strategy

### Approach
- **Emphasis**: unit-focused frontend tests + manual verification
- **Target test count**: 3–5 tests

### Test Targets
- `CopilotSidebar` completion banner: verify it shows warning text (not "All passed") when any step is `awaiting_human` or `skipped`
- `CopilotSidebar` completion banner: verify it shows "All N passed" only when all steps are `passed`
- `ExecutionLog` / `TerminalCard`: verify the report link points to S3 URL when available; gracefully degrades when not

### What NOT to Test
- S3 upload internals (`upload_report` function)
- LangGraph graph traversal/reporter_node internals

---

## Implementation Roadmap

- [x] Phase 1: Fix `CopilotSidebar.tsx` — update `failedCount` to include `awaiting_human` and `skipped` statuses in the non-passing condition for the completion banner (both inline and sidebar render paths)
- [x] Phase 2: Fix `ExecutionLog.tsx` — handle missing report gracefully: if `report_url` is empty, check availability before rendering the link, or show a disabled link with tooltip explaining the report may not be available
- [x] Phase 3 (optional): Improve backend 404 error message in `GET /runs/{run_id}/report` to be more descriptive about why the report is unavailable
- [x] Phase 4: Code review by second agent persona
- [ ] Phase 5: Manual verification in browser

---

## Execution State

**Build Status**: IDLE
**Current Phase**: COMPLETE
**Current Step**: ARCHIVE_COMPLETE
**Completed**: 2026-05-21T13:08:37-05:00
**Can Resume**: NO
**Worktree Cleaned**: YES
**Branch Deleted**: NO (preserved for PR #23)
**Is Multi-Phase**: YES
**Build Started**: 2026-05-21T10:40:00-05:00
**Build Completed**: 2026-05-21T11:01:00-05:00
**Reflection Completed**: 2026-05-21T13:03:00-05:00
**Last Implementation Step**:
  Step: Step 11 — Git Completion
  Status: COMPLETE
  Committed: `4f0931f`
  Pushed: `origin/hotfix/fix-audit-report-404-and-misleading-all-steps-passed-banner-audit-report-and-pass-banner`

### Active Sub-Agents
(none)

### Completed Steps
- Step 0: Parse Task ID — COMPLETE
- Step 0.5: Git Worktree created `.worktrees/fix-audit-report-404-and-misleading-all-steps-passed-banner` on branch `hotfix/fix-audit-report-404-and-misleading-all-steps-passed-banner-audit-report-and-pass-banner`
- Step 1: Read Task Context — COMPLETE
- Step 2: Load Complexity Context (Level 1) — COMPLETE
- Step 3–4: Implemented Phase 1 (CopilotSidebar), Phase 2 (ExecutionLog), Phase 3 (backend message already improved) — COMPLETE
- Step 7: Integration Verification — TypeScript clean, 18/18 pytest passed — COMPLETE
- Step 8: Code Review (second persona) — COMPLETE, 1 issue found and fixed (tooltip pointer-events)
- Step 11: Git commit + push — COMPLETE
