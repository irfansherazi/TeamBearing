---
legacy_id: fix-background-execution-of-test-suite-upon-page-refresh
---
# fix-background-execution-of-test-suite-upon-page-refresh: Fix background execution of test suite upon page refresh

**Complexity**: Level 2 (Backend + Frontend Coordination)
**Status**: REFLECTION_COMPLETE
**Jira Issue**: N/A
**Issue Type**: Bug / Reliability
**Priority**: High
**Branch**: hotfix/fix-background-execution-of-test-suite-upon-page-refresh-refresh-cancellation
**Worktree**: N/A
**Roadmap**: N/A

---

## Task Description

When a parallel Playwright test suite run (`/playwright/run-all`) is initiated, the backend spawns a background orchestrator task (`_run_suite_orchestrator`) which concurrently schedules tests using an `asyncio.Semaphore` to limit workers.

However, two critical bugs prevent clean cancellation and cleanup when the user refreshes or reloads the page:
1. **Queued Tests Bypass Stop/Cancel**: If a user stops the suite manually (or refreshes), running processes are killed. However, the other queued tests waiting on the semaphore are never checked for cancellation. Once a slot opens up, the queued tasks blindly wake up, set their state to `RUNNING` in the database, and spawn brand-new `npx playwright test` processes in the background.
2. **Refresh/Disconnect Left Orphaning Runs**: When the user reloads the browser, the React state is destroyed, but the backend keeps executing the background orchestrator and running test subprocesses to completion in the background, consuming substantial Fargate/local CPU and memory.

---

## Acceptance Criteria

### AC-1: Proactive Subprocess Check on Cancellation
- **Priority**: MUST
- **Success Criteria**:
  - In `backend/api/playwright_routes.py`, within `_run_single_suite_test`, verify the suite run status in the SQLite store before starting the subprocess (both before and after entering the semaphore block).
  - If the status is already marked as failed/stopped by the user, abort immediately without spawning any subprocess. Return a result indicating the test was stopped by the user.

### AC-2: Page Unload Suite Termination
- **Priority**: MUST
- **Success Criteria**:
  - In `frontend/src/pages/PlaywrightPage.tsx`, register a `beforeunload` or `unload` window event listener when a suite run is active.
  - On page unload/refresh, send a non-blocking, authenticated termination request to `${API_BASE_URL}/playwright/run-all/${suiteRunId}/stop`.
  - Use `fetch` with the `keepalive: true` flag and required authentication headers (`Authorization` SSO/App Token, `X-VQA-API-Key`) so that the HTTP request outlives the page lifecycle.

### AC-3: Heartbeat/Polling Inactivity Fallback (Optional / Hardening)
- **Priority**: SHOULD
- **Success Criteria**:
  - Maintain a lightweight in-memory cache of "last polled" timestamps for active suite runs.
  - In `backend/api/playwright_routes.py`, update `/run-all/{suite_run_id}/report` to update the "last polled" timestamp.
  - In the background orchestrator, or within individual test checks, if the suite run has not been polled for > 15 seconds, automatically invoke `stop_suite_run` to prevent orphaned background execution.
