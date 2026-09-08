---
legacy_id: FEAT-109
version: next
linked_tasks: []
status: planned
---

  ### FEAT-109: Parallel Headless Suite Runner with Pass/Fail Report
- **Version**: next
- **Status**: planned
- **Priority**: high
- **Complexity**: Level 3
- **Description**: Add a "▶ Run All Tests" button to the Playwright Test UI that runs every test in the library simultaneously in headless mode and displays a consolidated pass/fail report at the end of the run. This is a focused, streamlined version of the full Regression Suite Runner concept (see FEAT-053) with a simpler scope: no S3 upload, no live streaming — just parallel execution and a clean end-of-run summary table.
    1. **Frontend — Button**: Add a prominent "▶ Run All Tests" button to the Playwright Library page (`PlaywrightLibrary.tsx`), visually distinct from the per-test "Run" button. Button is disabled while a suite run is already in progress. Clicking shows a loading/running state with a spinner and elapsed timer.
    2. **Backend — Parallel Execution**: New `POST /playwright/run-all` endpoint that discovers all tests from `playwright_index.json`, spawns each as an independent `npx playwright test <file> --headed=false` child process, and runs them concurrently up to a configurable worker pool size (default: 4 concurrent). Each test process captures stdout/stderr. Returns a `suite_run_id` immediately; results are collected as processes finish.
    3. **Backend — Result Aggregation**: After all processes complete, aggregate results into a structured JSON summary: `{ suite_run_id, started_at, completed_at, total, passed, failed, results: [{ test_id, name, status: "PASS"|"FAIL", duration_ms, error_snippet? }] }`. Expose via `GET /playwright/run-all/{suite_run_id}/report`.
    4. **Frontend — Report**: On completion, replace the loading state with a compact summary card showing: Total / ✅ Passed / ❌ Failed counts and elapsed time. Below the summary, render a scrollable results table with one row per test showing its name, status badge (green PASS / red FAIL), and duration. If a test failed, show a collapsed error snippet expandable on click. No external report link required — the report is inline in the UI.
    5. **Concurrency Guard**: HTTP 429 if a suite run is already in progress. Only one suite run allowed at a time.
- **Acceptance Criteria**:
    - AC-1: "▶ Run All Tests" button is visible on the Playwright Library page and disabled while a run is active.
    - AC-2: Clicking the button initiates parallel headless execution of all tests in `playwright_index.json` via `POST /playwright/run-all`.
    - AC-3: Tests run simultaneously (up to pool size), not sequentially. Total duration is bounded by the slowest test, not sum of all.
    - AC-4: After all tests complete, `GET /playwright/run-all/{suite_run_id}/report` returns a structured JSON with per-test PASS/FAIL status, duration, and error snippet.
    - AC-5: The UI renders a summary card (Total / Passed / Failed / Duration) and a scrollable per-test results table without requiring a page reload.
    - AC-6: Failed tests display a collapsible error snippet inline in the results table.
    - AC-7: A second "▶ Run All Tests" click while a run is in progress returns HTTP 429 and the UI shows a "Run already in progress" message.
- **Key Files**:
    - `frontend/src/components/PlaywrightLibrary.tsx` — button + report UI
    - `frontend/src/components/SuiteResultsPanel.tsx` (New file) — results table component
    - `backend/api/routes.py` — `POST /playwright/run-all`, `GET /playwright/run-all/{suite_run_id}/report`
    - `backend/playwright_runner.py` (New file) — parallel process pool orchestrator
- **Related Features**: FEAT-053 (full Regression Suite Runner with live streaming + S3 upload — superset of this feature)
- **Linked Tasks**: None
- **Branch**: feature/FEAT-109-parallel-headless-runner
- **Created**: 2026-06-09
