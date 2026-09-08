---
legacy_id: FEAT-111
version: next
linked_tasks: []
status: planned
---

  ### FEAT-111: Bolstered Failure Report for Suite Runs
- **Version**: next
- **Status**: planned
- **Priority**: high
- **Complexity**: Level 2
- **Description**: After running the full Playwright test suite via "▶ Run All Tests", the end-of-run report should include a bolstered, prominent failure summary section that consolidates all failed tests and their failure reasons into one glanceable block — eliminating the need to click through each row individually.
    1. **Backend — Structured Failure Digest**: Extend the `GET /playwright/run-all/{suite_run_id}/report` response with a new `failure_digest` field: an array of `{ test_id, name, error_summary }` objects, one per failed test. The `error_summary` is a cleaned, one-line condensation of the `error_snippet` (strip ANSI codes, collapse multi-line stack traces to the primary assertion message). This field is only populated when `status === "completed"` or `status === "failed"` and `failed > 0`.
    2. **Frontend — Failure Summary Panel**: Add a new collapsible "❌ Failure Summary" panel to `SuiteResultsPanel.tsx` that appears between the KPI cards and the results table when the suite run is complete and has at least one failure. The panel renders a numbered list of every failed test: `#N — Test Name — Error reason`. Each entry is color-coded red with a monospace error excerpt. The panel starts expanded by default so the operator sees it immediately.
    3. **Clipboard Export**: Add a "📋 Copy Failure Summary" button at the top-right of the failure summary panel. Clicking it copies a plain-text version of the failure list (test name + error reason, one per line) to the clipboard for easy pasting into Slack, Jira comments, or stand-up notes.
- **Acceptance Criteria**:
    - AC-1: `GET /playwright/run-all/{suite_run_id}/report` includes a `failure_digest` array when the suite run has failed tests.
    - AC-2: Each entry in `failure_digest` contains `test_id`, `name`, and a cleaned one-line `error_summary`.
    - AC-3: The `SuiteResultsPanel` renders a prominent "❌ Failure Summary" panel listing all failed tests with their error reasons, positioned between the KPI cards and the results table.
    - AC-4: The failure summary panel is only visible when the suite run is complete/failed AND at least one test failed.
    - AC-5: A "📋 Copy Failure Summary" button copies a plain-text failure list to the clipboard.
    - AC-6: The failure summary panel starts expanded by default for immediate visibility.
    - AC-7: The `error_summary` field strips ANSI escape codes and condenses multi-line errors to the primary assertion message (≤120 chars).
- **Key Files**:
    - `backend/api/playwright_routes.py` — Modify `_run_suite_orchestrator` and report endpoint to include `failure_digest`
    - `backend/api/schemas.py` — Add `FailureDigestEntry` and update `PlaywrightSuiteReportResponse`
    - `frontend/src/components/SuiteResultsPanel.tsx` — Add Failure Summary panel
    - `frontend/src/types/index.ts` — Update `PlaywrightSuiteReportResponse` type
- **Linked Tasks**: None
- **Branch**: feature/FEAT-111-bolstered-failure-report
- **Created**: 2026-06-11
