---
legacy_id: bolstered-failure-report-for-suite-runs
---
# bolstered-failure-report-for-suite-runs: Bolstered Failure Report for Suite Runs

**Complexity**: Level 2 (Intermediate)
**Status**: REFLECTION_COMPLETE
**Roadmap Link**: [FEAT-111: Bolstered Failure Report for Suite Runs](../roadmap.md#feat-111-bolstered-failure-report-for-suite-runs)
**Branch**: feature/FEAT-111-bolstered-failure-report
**Worktree**: N/A
**Interrogation Report**: [.agent-logs/interrogations/FEAT-111-interrogation-report.md](../../.agent-logs/interrogations/FEAT-111-interrogation-report.md)

---

## Task Description

After running the full Playwright test suite via "▶ Run All Tests", the end-of-run report should include a bolstered, prominent failure summary section that consolidates all failed tests and their failure reasons into one glanceable block — eliminating the need to click through each row individually.

This task enhances the parallel suite runner report with a structured failure digest served dynamically at read-time, and introduces a dedicated collapsible summary panel in the UI with copy-to-clipboard functionality and insecure-context fallbacks.

---

## User Story

**As a** Quality Assurance Engineer or Developer,
**I want** to see a consolidated and readable failure summary of all failed tests in a parallel suite run immediately after completion,
**So that** I can diagnose test failures at a glance without having to click through each test row in the results table.

---

## Acceptance Criteria

### AC-1: API Enhancement for Failure Digest
- **Given** a parallel suite run is completed or failed and has failed tests (`failed > 0`)
- **When** calling `GET /api/playwright/run-all/{suite_run_id}/report` or `POST /api/playwright/run-all/{suite_run_id}/stop`
- **Then** the response JSON includes a non-null `failure_digest` array.
- **And** the `failure_digest` field is omitted or `null` while the suite run is still in progress (`status === "running"`) to conserve CPU parsing overhead during polling.

### AC-2: Failure Digest Entry Structure
- **Given** a `failure_digest` entry for a failed test
- **When** parsed by the API
- **Then** it must contain exactly:
  - `test_id`: The ID of the test (e.g., `qa-102-test`).
  - `name`: The human-readable name of the test.
  - `error_summary`: A cleaned, one-line condensed description of the error.

### AC-3: Collapsible Failure Summary Panel in UI
- **Given** a parallel suite run report is completed or failed
- **When** the run has at least one failure (`failed > 0`)
- **Then** a prominent, styled "❌ Failure Summary" panel is rendered in `SuiteResultsPanel.tsx` positioned directly between the KPI summary cards and the results table.
- **And** the panel lists all failed tests in a numbered sequence showing: `#N — Test Name (test_id) — Error summary`.
- **And** the panel starts expanded by default so failures are immediately visible.

### AC-4: Clipboard Export with Fallbacks
- **Given** the "❌ Failure Summary" panel is visible
- **When** clicking the "📋 Copy Failure Summary" button in the panel header
- **Then** the plain-text list of failed tests and error reasons (formatted as `1. Test Name: Error summary`, one per line) is copied to the user's clipboard.
- **And** if `navigator.clipboard` is unavailable (e.g. in insecure HTTP local environments), the system falls back to a temporary off-screen textarea copy-selection hack, maintaining a seamless copy experience.
- **And** a temporary success notification ("Copied!") is shown near the button for 2 seconds.

### AC-5: Multi-Line Error & ANSI Stripping Validation
- **Given** raw Playwright execution stdout/stderr containing ANSI color codes and verbose stack traces
- **When** parsing the failure reason in `_clean_error_to_summary`
- **Then** all ANSI escape codes are completely stripped.
- **And** Playwright runner lines (such as `1) [chromium] › test.ts`) and stack trace lines (such as `at tests/...` or lines containing `node_modules/` or `playwright/`) are filtered out.
- **And** the first matching primary assertion line (containing `Error:`, `expect(`, or `timeout`) is chosen as the `error_summary`.
- **And** if no assertion line is found, the first non-header, non-trace line is used as a fallback.
- **And** the summary is truncated to a maximum of 120 characters (using trailing `...` if truncated).

---

## Technical Strategy

### Backend Enhancements (Python)

1. **`backend/api/schemas.py`**:
   - Define the `FailureDigestEntry` schema:
     ```python
     class FailureDigestEntry(BaseModel):
         test_id: str
         name: str
         error_summary: str
     ```
   - Update `PlaywrightSuiteReportResponse` with `failure_digest: list[FailureDigestEntry] | None = None`.

2. **`backend/api/playwright_routes.py`**:
   - Implement the `_clean_error_to_summary(error_snippet: str | None) -> str` parsing function matching the AC-5 logic.
   - Update `get_suite_run_report` and `stop_suite_run` to construct the `failure_digest` at response-time:
     ```python
     if run_data and run_data.get("status") in ("completed", "failed") and run_data.get("failed", 0) > 0:
         digest = []
         for r in run_data.get("results", []):
             if r.get("status") == "FAIL":
                 digest.append(FailureDigestEntry(
                     test_id=r["test_id"],
                     name=r["name"],
                     error_summary=_clean_error_to_summary(r.get("error_snippet"))
                 ))
         # Add to report
     ```

### Frontend Enhancements (React & TS)

1. **`frontend/src/types/index.ts`**:
   - Declare `FailureDigestEntry` interface:
     ```typescript
     export interface FailureDigestEntry {
       test_id: string;
       name: string;
       error_summary: string;
     }
     ```
   - Add `failure_digest?: FailureDigestEntry[];` to `PlaywrightSuiteReportResponse`.

2. **`frontend/src/components/SuiteResultsPanel.tsx`**:
   - Maintain state `isSummaryExpanded` (boolean, default `true`).
   - Add clipboard utility helper handling `navigator.clipboard` and `<textarea>` fallbacks with visual "Copied!" timeout state.
   - Inject the collapsible card container between `<div className="pw-kpi-summary"...>` and the results table container `<div style={{ overflowX: "auto"... }}>`.

---

## Testing Strategy

### 1. Backend Pytest Unit Tests
- Add a test case `test_suite_report_failure_digest` to `tests/test_playwright_suite_runner.py` that mocks a failed run with multi-line, ANSI-colorized, stack-traced error snippets.
- Verify that `failure_digest` is present in the response from `/report` and that the parsed `error_summary` correctly extracts the target assertion message (stripped of ANSI codes, stack traces, and Playwright run headers), capped at 120 chars.
- Assert that `failure_digest` is `None` while the suite is in progress.

### 2. Frontend Vitest Component Tests
- Update `frontend/src/components/__tests__/SuiteResultsPanel.test.tsx` to:
  - Verify that the "❌ Failure Summary" panel is rendered when `report.failed > 0` and `status === "completed"`.
  - Assert that clicking "📋 Copy Failure Summary" successfully calls `navigator.clipboard.writeText` with the correct formatted plain text block.
  - Verify that the panel starts expanded and can be toggled collapsed on click.

---

## Execution State
- **Build Status**: SUCCESS
- **Phase Being Built**: BUILD & VALIDATION
- **Phase Number**: N/A (BUILD_COMPLETE)
