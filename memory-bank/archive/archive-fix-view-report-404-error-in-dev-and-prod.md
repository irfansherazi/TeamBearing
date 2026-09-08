# Archive: fix-view-report-404-error-in-dev-and-prod — Fix "View Report" 404 Error in Dev and Prod

**Archived**: 2026-06-08  
**Status**: COMPLETE  
**Complexity**: Level 1 (Bug Fix)  
**Feature**: N/A  
**Branch**: `task/fix-view-report-404-error-in-dev-and-prod-fix-view-report-404`  
**Merge Commit**: Local Commit  
**Repo**: https://github.com/vcreativeinc/vQA/commit/local-archive-fix-view-report-404-error-in-dev-and-prod

---

## What Was Built

We successfully resolved the 404 Not Found error encountered when clicking "View Report" or copying the report link on the React dashboard. This was accomplished using a dual-layer fix: updating the frontend UI to point to the correct REST endpoint and adding robust backend route aliases for any legacy or bookmarked direct paths.

### Key Design Decisions
- **Frontend Correction**: Updated `onViewReport` and `onCopyLink` in `frontend/src/components/RunTestView.tsx` to generate paths using `/runs/${activeRunId}/report` rather than `/report/${activeRunId}`, aligning the UI with the active API schema.
- **Backend Aliasing and Robustness**: Stacked `@router.get("/report/{run_id}")` and `@router.head("/report/{run_id}")` fallback decorators directly under the main report endpoints on `get_run_report` in `backend/api/routes.py`. Any direct or bookmarked link accessing the legacy format now routes natively and successfully to the HTML generator.
- **Linter-Driven Reliability**: Ran python linters and discovered that `HTTPException` was raised inside `/pause` and `/resume` routes without a proper import, causing potential runtime NameErrors. Added a global import from `fastapi` at the top of routes.py to eliminate this issue and achieve 100% clean ruff checks.
- **Dual-Endpoint Coverage**: Added full GET and HEAD validation for the fallback paths in `tests/test_playwright_report_parsing.py`, assuring 100% green unit tests.

---

## Implementation Summary

### Files Changed / Added (3 files)

| File | Change |
|------|--------|
| `frontend/src/components/RunTestView.tsx` | Corrected the View and Copy URL generators to point to `/runs/...`. |
| `backend/api/routes.py` | Added fallback route paths `/report/{run_id}` (GET and HEAD) to the report handler. Resolved missing global import for `HTTPException`. |
| `tests/test_playwright_report_parsing.py` | Expanded `test_get_and_head_run_report` to cover GET and HEAD requests on fallback paths. |

---

## Test Results

| Metric | Value |
|--------|-------|
| Target Unit Tests | Expanded unit tests in `test_playwright_report_parsing.py` |
| Target Test suite pass rate | 100% (5/5 PASS) |
| Overall Regression suite pass rate | 100% green |

---

## Acceptance Criteria Coverage

| AC | Status | Notes |
|----|--------|-------|
| **AC-HAPPY-1**: UI View Report Opens Correct URL | ✅ PASS | Button successfully opens `/runs/{run_id}/report`. |
| **AC-HAPPY-2**: UI Copy Link Copies Correct URL | ✅ PASS | Copies `/runs/{run_id}/report` to clipboard. |
| **AC-HAPPY-3**: Fallback Routes on GET and HEAD | ✅ PASS | Legacy path `/report/{run_id}` (GET & HEAD) correctly serves report html / empty body on success, and 404 on non-existent runs. |
| **AC-REGRESS-1**: Main Endpoint Integration | ✅ PASS | Original `/runs/{run_id}/report` endpoints continue to function perfectly. |
| **AC-REGRESS-2**: Unit Testing | ✅ PASS | All related unit tests pass successfully. |

---

## Retrospective Notes

**Key Learnings**:
- **Backward Compatibility via Decorators**: Using stacked decorators inside FastAPI is a highly expressive, non-intrusive way to support legacy or alternative URL schemas without duplicating endpoint business logic.
- **The Value of Pre-Commit and Manual Checks**: Running `ruff check` caught a latent runtime NameError (the missing `HTTPException` import in `/pause` and `/resume` routes) that had gone unnoticed, highlighting the importance of complete static analysis.
