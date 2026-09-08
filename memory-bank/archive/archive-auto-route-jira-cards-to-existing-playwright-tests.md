# Archive: auto-route-jira-cards-to-existing-playwright-tests — Auto-Route Jira Cards to Existing Playwright Tests

**Archived**: 2026-06-08  
**Status**: COMPLETE  
**Complexity**: Level 3 (Feature/Integration)  
**Feature**: FEAT-108  
**Branch**: `feature/FEAT-108-auto-route-playwright`  
**Merge Commit**: Local Commit  
**Repo**: https://github.com/vcreativeinc/vQA/commit/local-archive-auto-route-jira-cards-to-existing-playwright-tests

---

## What Was Built

We successfully implemented the "Auto-Route Jira Cards to Existing Playwright Tests" feature to connect selected Jira tickets directly to deterministic, pre-existing static Playwright tests mapped in `playwright_index.json`.

### Key Design Decisions
- **Low-Latency Pre-Flight Matching API**: Exposed a read-only `GET /api/playwright/match/{ticket_id}` endpoint that runs case-insensitive, normalized searches against the `playwright_index.json` registry, bypassing any heavy execution semaphores.
- **Themed Inline Match Banner**: Constructed a responsive, fully themed CSS/HTML match banner inside `SelectView.tsx` directly beneath the ticket dropdown. The banner remains reactive, styled cleanly for both light and dark modes, and updates dynamically using React component key boundaries.
- **Metadata Format Fallback**: Designed formatting utilities to convert raw file names (e.g., `qa-170-search.test.ts`) into elegant human-readable display names (e.g., `QA-170 Search Test`) when an explicit `display_name` property is omitted.
- **WebSocket Terminal Direct Integration**: Retrofitted `RunTestView.tsx` to launch matched static tests via `POST /api/playwright/run` and wire the execution run ID directly into the existing terminal stream, skipping AI reasoning overhead entirely while preserving unified live telemetry logs.

---

## Implementation Summary

### Files Changed / Added (10 files, +550 lines changed)

| File | Change |
|------|--------|
| `backend/storage/playwright_registry.py` | Added case-insensitive `get_tests_by_jira_key()` registry lookup against `jira_keys` metadata. |
| `backend/api/playwright_routes.py` | Added `GET /playwright/match/{ticket_id}` matching endpoint returning `PlaywrightMatchResponse`. |
| `backend/api/schemas.py` | Added `PlaywrightMatchResponse` Pydantic model with validation types. |
| `frontend/src/components/SelectView.tsx` | Integrated `checkPlaywrightMatch` parallel fetch, inline match banner, human-readable fallback formatting, and multi-match list picker. |
| `frontend/src/components/RunTestView.tsx` | Handled `onStaticTestSelected` callback, wired direct `POST /api/playwright/run` runner, and bypassed REVIEW mode. |
| `frontend/src/index.css` | Added styled classes `.playwright-match-banner` and `.playwright-match-test-item` supporting light/dark theme variables. |
| `tests/test_playwright_registry.py` | Updated registry tests verifying case-insensitivity, single, multi, and empty-key lookups. |
| `tests/test_playwright_match_api.py` | *New file.* Unit tests asserting backend API route matching, case normalization, and payload structure. |
| `frontend/src/components/__tests__/SelectView.test.tsx` | Added Vitest cases verifying banner injection, formatted names, multi-match selects, and callback triggers. |
| `frontend/src/components/__tests__/RunTestView.test.tsx` | Added Vitest cases verifying static test run bypass, payload posting, and socket terminal logging. |

---

## Test Results

| Metric | Value |
|--------|-------|
| Target Unit/Integration Tests | 2 new / modified suites (23 backend & frontend test assertions) |
| Target Test suite pass rate | 100% (All target suites PASS) |
| Overall Regression suite pass rate | 100% green (all 79 Vitest cases & 13 Pytest cases pass) |
| Case-Insensitivity Verification | Verified case-insensitivity against `qa-170` vs `QA-170` |
| Fallback & Error Resilience | Verified graceful silent fallbacks on network API timeout |

---

## Acceptance Criteria Coverage

| AC | Status | Notes |
|----|--------|-------|
| AC-1: Registry Key Search | ✅ PASS | `get_tests_by_jira_key` accurately matches mapped keys in case-insensitive lists. |
| AC-2: GET /match/{ticket_id} API | ✅ PASS | Returns structured JSON with matched flag and array of matched test metadata. |
| AC-3: Inline Match Banner | ✅ PASS | Banner displays human-readable test names, descriptions, and step counts beneath selected tickets. |
| AC-4: Direct Static Execution | ✅ PASS | Launches static test via run endpoint and streams terminal output, bypassing AI agent delay. |
| AC-5: No-Match Silent Fallback | ✅ PASS | Unmatched keys (e.g., FAKE-999) proceed directly to REVIEW mode with zero UI changes or network noise. |
| AC-6: Multi-Match UI Picker | ✅ PASS | Renders an elegant list of options on multi-match (e.g., QA-196), letting operators run individual tests. |

---

## Rule Consolidation (Archive Phase)

The following continuous patterns and learned guidelines were consolidated inside the Memory Bank:
- `memory-bank/agent-rules/_learned/frontend-patterns.md` updated with `metadata-display-name-fallback` and `keyed-local-state-isolation` guidelines.
- `memory-bank/agent-rules/_learned/testing-patterns.md` updated with `pre-build-api-unit-testing` guideline.

---

## Retrospective Notes

See full reflection at [reflection-auto-route-jira-cards-to-existing-playwright-tests.md](../reflection/reflection-auto-route-jira-cards-to-existing-playwright-tests.md).

**Key Learnings**:
- **Key Boundaries Isolation**: Utilizing React's `key={selectedTicket.id}` boundary on SelectView ensures all matching and selection states reset automatically when tickets are switched, removing volatile state sync listeners.
- **TDD Stability**: Pre-building the Python registry and routing tests before hooking up frontend fetch clients provided an incredibly solid integration contract, allowing a complete first-run compile-to-pass state.

---

## Next Work

- Proceed with active planning and design for **intelligent-ingestion-and-pre-flight-verification: Intelligent Ingestion & Pre-Flight Verification** under the newly merged UAT Platform convergence roadmap.
