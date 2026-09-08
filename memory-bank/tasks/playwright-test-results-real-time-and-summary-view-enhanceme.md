---
legacy_id: playwright-test-results-real-time-and-summary-view-enhanceme
---
# playwright-test-results-real-time-and-summary-view-enhanceme: Playwright Test Results Real-Time & Summary View Enhancement

**Status**: COMPLETE
**Complexity**: Level 2
**Roadmap Link**: N/A
**Branch**: feature/FEAT-110-playwright-results-enhancement
**Created**: 2026-06-08

---

## Description

When running a Playwright test from the "Run a Test" UI, the results view does not accurately communicate test outcomes to the end user. Step results stay stuck on "Waiting", the summary row is misleading ("0 passed, 0 failed, 1 skipped"), and test failures are invisible.

This task enhances the system to parse Playwright's JSON report output and stdout stream, map per-step status back to the frontend in real time, display detailed failure reasons (errors, assertion messages, stack traces) inline within the steps table, and ensure the top-level banner and summary counts are accurate.

---

## Specification

### User Story
**As a** QA Engineer or Product Team Member,
**I want** to see real-time step execution updates and accurate pass/fail counts when executing a Playwright test,
**So that** I can immediately understand which parts of a test failed and why without clicking through to raw HTML reports.

### Acceptance Criteria

#### Real-time & Terminal Progress
- **AC-1**: At the start of a Playwright test run, initialize and broadcast the full list of steps from the test's metadata with status `"pending"`.
- **AC-2**: Stream real-time step status updates (e.g. `"passed"`, `"failed"`, `"in_progress"`) over WebSocket during execution by parsing the stdout line streams.

#### Deterministic Completion Parsing
- **AC-3**: Configure Playwright to generate a structured JSON report file (e.g. `playwright/test-results/results-{run_id}.json`) at the end of the run.
- **AC-4**: Parse the completed JSON report to determine final step results, error messages, and failure details.
- **AC-5**: Map the parsed JSON results back to the original step names, ensuring skipped steps and error messages are correctly populated.
- **AC-6**: Broadcast final step statuses over WebSocket via `ac_progress` message before closing the run.

#### UI Presentation & Accuracy
- **AC-7**: The frontend `RunTestView` maps `acProgress` steps and binds step errors to the `reasoning` field of the step row so that they render inline in the table on failure.
- **AC-8**: The top banner (✅ PASSED / ❌ FAILED) and the summary row counts (`passed`, `failed`, `skipped`) derive their status and counts directly from the actual updated steps, reflecting the true execution outcome.

---

## Implementation Roadmap

### Phase 1: Research & Planning (Done)
- Explored `backend/api/playwright_routes.py` and `frontend/src/components/RunTestView.tsx`.
- Formulated the JSON report output and real-time regex parsing approach.

### Phase 2: Backend Development (BUILD)
- Add `--reporter=list,json` and `PLAYWRIGHT_JSON_OUTPUT_NAME` to subprocess execution in `backend/api/playwright_routes.py`.
- Implement `_parse_line_for_step_progress` real-time stdout parser.
- Implement post-run `_parse_playwright_json_report` JSON parser.
- Update `_broadcast_ac_progress` in `backend/api/routes.py` to support buffering of progress messages.

### Phase 3: Frontend Development (BUILD)
- Update `RunTestView.tsx` `acProgress` mapper to bind `ac.error` to `reasoning`.

### Phase 4: Verification & Testing (VALIDATE)
- Add backend unit tests in `tests/test_playwright_report_parsing.py`.
- Run frontend and backend tests to confirm zero regressions.
- Verify everything works seamlessly.
