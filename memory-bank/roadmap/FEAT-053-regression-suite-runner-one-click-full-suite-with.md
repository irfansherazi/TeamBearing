---
legacy_id: FEAT-053
version: next
linked_tasks: []
status: planned
---

### FEAT-053: Regression Suite Runner — One-Click Full Suite with Live Progress & HTML Report
- **Version**: next
- **Status**: planned
- **Priority**: high
- **Complexity**: Level 3
- **Description**: Add a "⚡ Run Regression Suite" button to the Playwright Library page that executes ALL tests in `playwright_index.json` in headless mode and produces a consolidated HTML report. This is a one-click full-suite regression tool. Key requirements:
    1. **BACKEND**: New `POST /playwright/run-suite` endpoint — shells out `npx playwright test` (no file arg = all tests) in headless mode with `--reporter=html,json`. Respects `STORAGE_DIR` so authenticated sessions are used. Concurrency guard: HTTP 429 if a suite run is already in progress. Only one suite run allowed at a time.
    2. **WEBSOCKET STREAMING**: Real-time progress via WebSocket — broadcasts running test count, current test name, and live pass/fail counters as tests execute. Final message includes the permanent S3 report URL.
    3. **S3 UPLOAD**: On suite completion, upload the full `playwright-report/` directory tree to S3 using the existing `upload_file()` pattern from `backend/storage/s3.py`. Key layout: `{s3_prefix}/playwright-suite-reports/{suite_run_id}/` — mirroring the `/reports/{run_id}/` layout used for vQA audit reports. The `index.html` S3 URL is returned in the final WebSocket message and stored with the run record. All report links point to S3 (no local filesystem links exposed to the frontend).
    4. **FRONTEND**: Prominent "⚡ Run Regression Suite" button on the Playwright Library page, visually distinct from the single-test "Run Test" button. Progress UI shows: running count (N/total), live pass/fail counters, elapsed time. Completion UI: summary card (total / passed / failed / duration) with a "View Full Report" button linking to the **S3 report URL**.
    5. **CONSTRAINTS**: No headless toggle — suite always runs headless for speed. Suite run is independent of single-test run infra (separate concurrency guard and run state).
- **Linked Tasks**: None
- **Branch**: feature/FEAT-053-regression-suite-runner
- **Created**: 2026-05-27
