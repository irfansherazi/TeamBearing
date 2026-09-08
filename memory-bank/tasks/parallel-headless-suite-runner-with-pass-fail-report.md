---
legacy_id: parallel-headless-suite-runner-with-pass-fail-report
---
# parallel-headless-suite-runner-with-pass-fail-report: Parallel Headless Suite Runner with Pass/Fail Report

**Complexity**: Level 3 (Intermediate)
**Status**: COMPLETED
**Roadmap Link**: [FEAT-109: Parallel Headless Suite Runner with Pass/Fail Report](../roadmap.md#feat-109-parallel-headless-suite-runner-with-pass-fail-report)
**Branch**: feature/FEAT-109-parallel-headless-runner
**Worktree**: N/A
**Interrogation Report**: [.agent-logs/interrogations/parallel-headless-suite-runner-with-pass-fail-report-interrogation-report.md](../../.agent-logs/interrogations/parallel-headless-suite-runner-with-pass-fail-report-interrogation-report.md)

---

## Task Description

Implement a **"▶ Run All Tests"** button on the Playwright dashboard that launches every test in the library simultaneously in headless mode (concurrency limited by `VQA_SUITE_WORKERS`, default: 4) and displays a consolidated pass/fail report at the end of the run inside the UI. This provides a streamlined version of a regression suite runner with zero dependencies on S3 or external live streams.

---

## User Story

**As a** Quality Assurance Engineer or Product Owner,
**I want** to execute all Playwright tests simultaneously and view a consolidated pass/fail report in the UI,
**So that** I can verify application-wide regressions in parallel without having to trigger and watch each test individually.

---

## Acceptance Criteria

### AC-1: "▶ Run All Tests" UI Trigger
- **Given** the Playwright Library page is loaded
- **When** looking at the UI next to the config controls
- **Then** a prominent, styled "▶ Run All Tests" button is visible and active.
- **And** the button is disabled while a suite run is already in progress.

### AC-2: Concurrency & Lock Guard
- **Given** a suite run is in progress
- **When** another request to `POST /api/playwright/run-all` is received (e.g. from clicking the button or another browser)
- **Then** the backend returns HTTP 429 ("Suite run already in progress").
- **And** the frontend shows a clear, non-intrusive warning/status indicating a run is already active.

### AC-3: Parallel Headless Subprocess Pool
- **Given** the "▶ Run All Tests" button is clicked
- **When** spawning the Playwright test runner processes
- **Then** all tests defined in `playwright_index.json` are discovered and spawned concurrently.
- **And** concurrency is strictly limited using an `asyncio.Semaphore` with size configured via `VQA_SUITE_WORKERS` (default: 4).
- **And** each subprocess is executed headlessly (`--headed=false` or no headed flag) using `asyncio.create_subprocess_exec` and registers its PID to `_playwright_pids` for clean SIGTERM cleanup on server shutdown.
- **And** each subprocess has a rigid per-test timeout of **180 seconds** (using `asyncio.wait_for`).

### AC-4: State Persistence & Reload Robustness
- **Given** a suite run is active or completed
- **When** the browser is reloaded or navigated away and back
- **Then** the frontend successfully polls `GET /api/playwright/run-all/{suite_run_id}/report` and restores the correct active/completed suite run state without losing data.

### AC-5: Aggregate Report API
- **Given** a suite run with ID `suite_run_id`
- **When** querying `GET /api/playwright/run-all/{suite_run_id}/report`
- **Then** the backend returns a structured JSON payload:
  ```json
  {
    "suite_run_id": "suite-xxxxxx",
    "status": "running" | "completed" | "failed",
    "started_at": "ISO-8601-timestamp",
    "completed_at": "ISO-8601-timestamp-or-null",
    "total": 5,
    "passed": 3,
    "failed": 2,
    "results": [
      {
        "test_id": "qa-172-sales",
        "name": "QA-172 Sales Test",
        "status": "PASS" | "FAIL",
        "duration_ms": 12500.0,
        "error_snippet": "TimeoutError: Execution exceeded 180 seconds"
      }
    ]
  }
  ```

### AC-6: Inline Results Panel rendering
- **Given** a completed suite run
- **When** rendering the `SuiteResultsPanel.tsx` component
- **Then** the UI displays:
  - An inline KPI summary card showing Total, Passed (green), Failed (red), and elapsed time.
  - A scrollable table of all executed tests showing their human-readable name (using `getTestDisplayName`), execution status badge, and duration.
  - Collapsible standard error/stderr snippets inline inside the table rows for failed tests, expandable on click.

---

## Technical Strategy

### State Management (Backend)
- Maintain a module-level dictionary in `backend/api/playwright_routes.py`:
  `_suite_runs: Dict[str, Any] = {}`
- Track the active suite run ID to enforce the single-suite concurrency limit:
  `_active_suite_run_id: Optional[str] = None`
- Enforce locking:
  ```python
  if _active_suite_run_id is not None:
      raise HTTPException(status_code=429, detail="Suite run already in progress")
  ```

### Background Suite Orchestration
- Launch parallel execution as a background task using `asyncio.create_task`.
- Implement parallel execution logic in `backend/playwright_runner.py`:
  - Fetch all tests from the registry.
  - Create `asyncio.Semaphore(int(os.getenv("VQA_SUITE_WORKERS", 4)))`.
  - For each test:
    - Spawn `npx playwright test <file> --project={browser}` with `--headed=false` (or simply without the `--headed` flag).
    - Capture stdout/stderr.
    - Wrap execution in `asyncio.wait_for(..., timeout=180.0)`.
    - If timeout occurs, terminate the process, record status as `FAIL`, and set `error_snippet` to `"TimeoutError: Execution exceeded 180 seconds"`.
    - If exit code != 0, parse the last 5 lines of stderr as the `error_snippet`.
    - Record elapsed duration.

### Frontend Integration
- Create `frontend/src/components/SuiteResultsPanel.tsx`.
- In `PlaywrightPage.tsx`:
  - Track `activeSuiteRunId`, `suiteReport` (of type `PlaywrightSuiteReport` or null), and `suiteRunStatus` ("idle" | "running" | "completed" | "failed").
  - On "Run All Tests" click, POST to `/api/playwright/run-all`, set `activeSuiteRunId`, `suiteRunStatus` to `"running"`, and start periodic polling (every 1.5s).
  - Swap the standard test/terminal panel view with the `SuiteResultsPanel` when `suiteRunStatus` is `"completed"` or `"failed"`, or when a run is active.
  - Provide a back/reset button to return to the normal terminal view and allow running single tests again.

---

## Testing Strategy

### Unit / Mock Tests
- Create `tests/test_playwright_suite_runner.py` asserting:
  - Parallel scheduling and concurrency throttling (using simulated mock subprocesses).
  - Proper handling of the active suite lock (HTTP 429).
  - Correct report JSON structure on completion, including error snippet parsing and timeout scenarios.
- Run tests via `pytest tests/test_playwright_suite_runner.py -v`.

### Frontend Component Tests
- Add a Vitest suite for `SuiteResultsPanel.tsx` in `frontend/src/components/__tests__/SuiteResultsPanel.test.tsx` verifying:
  - KPI summary elements render correct numbers.
  - Results table displays the tests and badges.
  - Collapsible error panel opens on clicking a failed row.

---

## Execution State
- **Build Status**: COMPLETE
- **Phase Being Built**: Single Phase
- **Build Completed**: 2026-06-09T18:30:00Z
- **UAT Status**: PASS
- **UAT Completed**: 2026-06-10T08:45:00Z
- **UAT Run ID**: e8f94c1a
