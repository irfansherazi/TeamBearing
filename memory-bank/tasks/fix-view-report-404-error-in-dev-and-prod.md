---
legacy_id: fix-view-report-404-error-in-dev-and-prod
---
# fix-view-report-404-error-in-dev-and-prod: Fix "View Report" 404 Error in Dev and Prod

**Complexity**: Level 1
**Status**: COMPLETE
**Jira Issue**: N/A
**Issue Type**: Bug
**Priority**: High
**Branch**: task/fix-view-report-404-error-in-dev-and-prod-fix-view-report-404
**Worktree**: N/A
**Roadmap**: N/A

---

## Task Description

Currently, when clicking "View Report" in the `CompleteView` or copying the report link after a test completes, the frontend attempts to open or copy a URL containing `/report/{run_id}` (e.g. `${API_BASE_URL}/report/{run_id}`).

However, the backend serves the HTML audit report on the `/runs/{run_id}/report` path, resulting in a `{"detail":"Not Found"}` 404 response on the `/report/{run_id}` path.

We need to fix this so that "View Report" works flawlessly in both dev and production environments.

### Proposed Solution:
1. **Frontend Update**:
   - Update `frontend/src/components/RunTestView.tsx` to use `${API_BASE_URL}/runs/${activeRunId}/report` for `onViewReport` and `onCopyLink`, matching the correct backend URL pattern.
2. **Backend Robustness (Stacked Decorators)**:
   - Add stacked `@router.get("/report/{run_id}")` and `@router.head("/report/{run_id}")` decorators in `backend/api/routes.py` to map `/report/{run_id}` directly to `get_run_report` as a robust fallback. This ensures any legacy, direct, or bookmarked links to `/report/{run_id}` still work beautifully.

---

## Acceptance Criteria

- **AC-HAPPY-1**: Clicking "View Report" on the UI successfully opens the correct audit report URL (`/api/runs/{run_id}/report`) in a new tab.
- **AC-HAPPY-2**: Copying the report link on the UI copies the correct direct audit report URL to the clipboard.
- **AC-HAPPY-3**: Navigating directly to `/report/{run_id}` or probing it via HTTP `HEAD` on the backend correctly resolves to the HTML audit report, ensuring backward compatibility.
- **AC-REGRESS-1**: The existing `/runs/{run_id}/report` endpoints (GET and HEAD) continue to function identically.
- **AC-REGRESS-2**: All related unit tests pass successfully.

---

## Open Questions

- None — task is well-defined. The double-fix (frontend correction + backend alias routing) provides high reliability and prevents regressions.

---

## Affected Components

- `frontend/src/components/RunTestView.tsx` — View/copy report link generation.
- `backend/api/routes.py` — Added `/report/{run_id}` route paths to the `get_run_report` handler.
- `tests/test_playwright_report_parsing.py` — Add test coverage for the fallback GET/HEAD `/report/{run_id}` endpoint.

---

## Test Strategy

### Approach
- **Emphasis**: Backend and Frontend Unit/Integration Verification
- **Target test count**: 1 backend test file expanded (`test_playwright_report_parsing.py`)

---

## Implementation Roadmap

- [x] Phase 1: Update frontend `RunTestView.tsx` to point to `/runs/${activeRunId}/report`.
- [x] Phase 2: Add stacked `/report/{run_id}` fallback route paths in backend `routes.py`.
- [x] Phase 3: Expand unit tests in `tests/test_playwright_report_parsing.py` to verify the fallback routes, and run verification.

---

## Execution State

**Build Status**: COMPLETE
**Last Completed**: 2026-06-08
**Can Resume**: NO

### Active Sub-Agents
(none)

### Completed Steps
1. Updated `frontend/src/components/RunTestView.tsx` to point to the correct backend endpoint `/runs/${activeRunId}/report` for `onViewReport` and `onCopyLink`.
2. Stacked fallback routing paths `/report/{run_id}` (GET and HEAD) directly under `/runs/{run_id}/report` in `backend/api/routes.py` to maintain backward-compatibility.
3. Expanded unit tests in `tests/test_playwright_report_parsing.py` to assert correct responses on fallback paths.
4. Ran all 5 unit tests and confirmed they pass flawlessly.
