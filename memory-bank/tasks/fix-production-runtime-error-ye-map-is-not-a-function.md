---
legacy_id: fix-production-runtime-error-ye-map-is-not-a-function
---
# fix-production-runtime-error-ye-map-is-not-a-function: Fix production runtime error "Ye.map is not a function"

**Complexity**: Level 1
**Status**: COMPLETED
**Jira Issue**: N/A
**Issue Type**: Bug
**Priority**: High
**Branch**: hotfix/fix-production-runtime-error-ye-map-is-not-a-function-ye-map-error
**Worktree**: N/A
**Roadmap**: N/A

---

## Task Description

A production runtime error was reported: `TypeError: Ye.map is not a function`. 
The stack trace points to minified React component code (`index-Dd4M5euu.js:14:2117`).
This error typically occurs when the frontend attempts to call `.map()` on a variable that is not an array (e.g., `null`, `undefined`, or an object).

Investigation identifies several components where data fetched from the API is mapped without sufficient safety checks:
- `AnalyticsDashboard`: `analytics.top_tickets.map`
- `ReportsArchive`: `reports.map`, `allRoles.map`, `group.rolesSeen.map`, `group.runs.map`
- `ReportsHistory`: `reports.map`, `allRoles.map`
- `TriagePanel`: `triage.steps.map`
- `ExecutionPanel`: `tickets.map`, `previewSteps.map`, `confirmedSteps.map`

---

## Acceptance Criteria

- AC-HAPPY-1: The application no longer crashes with "Ye.map is not a function" when API responses contain null or unexpected structures.
- AC-HAPPY-2: Safe fallbacks (empty arrays) are used for all mapped variables.
- AC-REGRESS-1: All dashboards (Run Test, Reports Archive, Analytics) still render correctly with valid data.
- AC-REGRESS-2: No regressions in existing functionality (rerun, triage, etc.).

---

## Open Questions

⚠️ **Review these before starting the build:**

- [x] Which specific component corresponds to `ha` in the minified trace? **ReportsHistory** (it is rendered on the main tab and had a top-level `.map` call on unvalidated state).
- [x] Should we also add a global Error Boundary to catch such crashes and show a user-friendly message? **Yes, implemented in `frontend/src/components/ErrorBoundary.tsx` and applied to Dashboard tabs.**

---

## Affected Components

- `frontend/src/components/AnalyticsDashboard.tsx` — `analytics.top_tickets` and `runs` mapping.
- `frontend/src/components/ReportsArchive.tsx` — `reports` and `groups` mapping.
- `frontend/src/components/ReportsHistory.tsx` — `reports` and `allRoles` mapping.
- `frontend/src/components/TriagePanel.tsx` — `triage.steps` mapping.
- `frontend/src/components/ExecutionPanel.tsx` — `tickets` and `previewSteps` mapping.

---

## Test Strategy

### Approach
- **Balanced**: Unit tests for the affected components with mocked invalid API data.
- **Target test count**: 5-7 tests.

### Test Targets
- `AnalyticsDashboard.tsx`
- `ReportsHistory.tsx`
- `ReportsArchive.tsx`
- `ExecutionPanel.tsx`

### What NOT to Test
- Backend API logic (already verified to be return empty lists on error, but frontend must be resilient).

---

## Implementation Roadmap
- [x] Phase 1: Add safety checks (`?.map` or `|| []`) to all vulnerable `.map` calls in the identified components.
- [x] Phase 2: Add unit tests to verify components don't crash with null/object data.
- [x] Phase 3: Implement a basic `ErrorBoundary` for the main dashboard tabs.

---

## Execution State

**Build Status**: COMPLETED
**Last Completed**: 2026-05-27
**Can Resume**: NO

### Active Sub-Agents
(none)

### Completed Steps
- Identified `ReportsHistory` as the likely crash source.
- Added safety checks to all vulnerable components.
- Implemented `ErrorBoundary` and wrapped dashboard tabs.
- Added unit tests for `ReportsHistory` invalid data scenarios.
