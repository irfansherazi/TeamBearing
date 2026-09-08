---
legacy_id: auto-route-jira-cards-to-existing-playwright-tests
---
# auto-route-jira-cards-to-existing-playwright-tests: Auto-Route Jira Cards to Existing Playwright Tests

**Status**: COMPLETE
**Complexity**: Level 3
**Roadmap Link**: FEAT-108
**Branch**: feature/FEAT-108-auto-route-playwright
**Created**: 2026-06-08

---

## Description

When a user selects a Jira card (e.g., QA-170) in the "Run a Test" flow, the system should check if there's already a static Playwright test mapped to that card via `playwright_index.json`. If so, offer to skip the AI agent entirely and run the existing test directly via `POST /playwright/run`.

The infrastructure pieces already exist but are not wired together:

| Component | Status | What it does |
|-----------|--------|-------------|
| `playwright_index.json` | ✅ Exists | Maps `jira_keys` → test files |
| `PlaywrightRegistry` | ✅ Exists | Can look up tests by ID, missing `get_by_jira_key()` |
| `ExecuteRequest.execution_engine` | ✅ Exists | Schema supports `"static"` + `playwright_test_id` |
| `SelectView.handleSelectTicket()` | ❌ No matching | Immediately transitions to REVIEW → AI agent |
| Backend ticket→test lookup API | ❌ Missing | No endpoint to check if a ticket has a static test |

---

## Specification

### User Story
**As a** QA engineer using the vQA dashboard,
**I want** the system to automatically detect when a Jira card has a mapped static Playwright test,
**So that** I can run the deterministic test directly without waiting for the AI agent to parse and execute.

### Entry Point
- **Page**: Run a Test (`/` or RunTestView)
- **Trigger**: User selects a Jira ticket in the SelectView ticket dropdown

### Happy Path
1. User opens the Run a Test page
2. User searches for and clicks a Jira ticket (e.g., QA-170)
3. Frontend calls `GET /api/playwright/match/{ticket_id}` in parallel with `runCredCheck`
4. Backend finds 1+ matching tests in `playwright_index.json`
5. UI shows a match banner: "🎭 Static Playwright test found for QA-170"
   - Human-readable test name displayed (e.g., "QA-170 Search Test", NOT `qa-170-search.test.ts`)
   - Step count displayed
   - "Run Static Test" primary action button
   - "Use AI Agent Instead" secondary link
6. User clicks "Run Static Test"
7. Frontend calls `POST /api/playwright/run` with the matched test ID
8. WebSocket terminal streams real-time output
9. User sees pass/fail result

### No-Match Path
1. User selects a Jira ticket with no mapped tests (e.g., VC2-9999)
2. Frontend calls `GET /api/playwright/match/{ticket_id}`
3. Backend returns `{ matched: false, tests: [] }`
4. UI proceeds directly to REVIEW mode (existing flow — zero changes)

### Multi-Match Path
1. User selects a Jira ticket with multiple tests (e.g., QA-196 → 8 tests)
2. Backend returns `{ matched: true, tests: [...] }` with all 8 entries
3. UI shows all matched tests in a selectable list
4. User picks one or uses "Run All Sequentially" option
5. Execution proceeds per happy path

### Acceptance Criteria

#### Entry
- AC-ENTRY-1: `GET /api/playwright/match/{ticket_id}` returns correct match status for any Jira key

#### Happy Path
- AC-HAPPY-1: Selecting QA-170 shows a "Static test found" banner with test details
- AC-HAPPY-2: Clicking "Run Static Test" launches via `POST /playwright/run` and streams terminal output
- AC-HAPPY-3: Selecting QA-196 shows all 8+ matched tests for selection
- AC-HAPPY-4: Test names are displayed in human-readable format (e.g., "QA-170 Search Test"), not raw filenames (e.g., `qa-170-search.test.ts`). Derived from `display_name` in `playwright_index.json` if present, otherwise auto-formatted from the filename.

#### Negative Path
- AC-NEG-1: Selecting a ticket with no static tests (e.g., VC2-9999) proceeds to REVIEW mode with zero UI changes
- AC-NEG-2: User can always choose "Use AI Agent Instead" to skip the static test and use the AI agent

#### Edge Cases
- AC-EDGE-1: Tickets with keys in mixed case (e.g., "qa-170" vs "QA-170") match correctly (case-insensitive)
- AC-EDGE-2: If the `/match` endpoint fails (network error), the UI silently falls back to the existing AI agent flow

---

## Implementation Roadmap

### Phase 1: Backend — Registry & API (foundation)

- [x] **1.1** Add `get_tests_by_jira_key(key: str) -> list[dict]` to `PlaywrightRegistry`
  - Case-insensitive match against each test's `jira_keys` array
  - Returns full test metadata dicts for all matches
  - **File**: `backend/storage/playwright_registry.py`

- [x] **1.2** Add `GET /playwright/match/{ticket_id}` endpoint to `playwright_routes.py`
  - Response schema: `{ matched: bool, tests: list[PlaywrightTestMetadata] }`
  - Normalize `ticket_id` to uppercase before lookup
  - Lightweight, read-only — no semaphore, no auth dependency beyond the parent router
  - **File**: `backend/api/playwright_routes.py`

- [x] **1.3** Add `PlaywrightMatchResponse` Pydantic model
  - `matched: bool`, `tests: list[PlaywrightTestMetadata]`
  - **File**: `backend/api/schemas.py`

### Phase 2: Frontend — Detection & Banner UI

- [x] **2.1** Add `checkPlaywrightMatch` API call to `SelectView.tsx`
  - Call `GET /api/playwright/match/{ticket_id}` in `handleSelectTicket` (parallel with `runCredCheck`)
  - Store result in component state: `playwrightMatch: { matched: bool, tests: PlaywrightTestMeta[] } | null`
  - **File**: `frontend/src/components/SelectView.tsx`

- [x] **2.2** Add match banner UI to `SelectView.tsx`
  - Rendered conditionally when `playwrightMatch?.matched === true`
  - Shows **human-readable** test name (e.g., "QA-170 Search Test"), description, step count
  - Display name sourced from `display_name` field in test metadata; fallback: auto-format filename (`qa-170-search.test.ts` → `QA-170 Search Test`)
  - "Run Static Test" button (primary) — calls new `onStaticTestSelected` prop
  - "Use AI Agent Instead" link — proceeds to existing `onTicketSelected` flow
  - Multi-match: render a selectable list of tests with human-readable names
  - **File**: `frontend/src/components/SelectView.tsx`

- [x] **2.3** Update `SelectView` props interface
  - Add `onStaticTestSelected: (ticket, testId, config) => void` callback prop
  - **File**: `frontend/src/components/SelectView.tsx`

- [x] **2.4** Add CSS for the match banner
  - `.playwright-match-banner` — themed via CSS custom properties (light/dark)
  - `.playwright-match-test-item` — for multi-match list items
  - **File**: `frontend/src/index.css`

### Phase 3: Frontend — Execution Wiring in RunTestView

- [x] **3.1** Handle `onStaticTestSelected` in `RunTestView.tsx`
  - New handler: `handleStaticTestSelected(ticket, testId, config)`
  - Calls `POST /api/playwright/run` with the test ID
  - On response: sets `uiMode = 'running'`, connects WebSocket to `response.run_id`
  - Skips REVIEW mode entirely — goes directly SELECT → RUNNING
  - **File**: `frontend/src/components/RunTestView.tsx`

- [x] **3.2** Wire `onStaticTestSelected` prop from `RunTestView` → `SelectView`
  - Pass the handler down as a prop
  - **File**: `frontend/src/components/RunTestView.tsx`

---

## Test Strategy

### Backend Unit Tests

- `tests/test_playwright_registry.py`:
  - `test_get_tests_by_jira_key_single_match` — QA-170 returns 1 test
  - `test_get_tests_by_jira_key_multi_match` — QA-196 returns 8+ tests
  - `test_get_tests_by_jira_key_no_match` — VC2-9999 returns empty list
  - `test_get_tests_by_jira_key_case_insensitive` — "qa-170" matches "QA-170"
  - `test_get_tests_by_jira_key_empty_key` — empty string returns empty list

- `tests/test_playwright_routes.py`:
  - `test_match_endpoint_found` — GET /playwright/match/QA-170 returns matched=true
  - `test_match_endpoint_not_found` — GET /playwright/match/FAKE-999 returns matched=false
  - `test_match_endpoint_case_insensitive` — GET /playwright/match/qa-170 works

### Manual Verification
1. Select QA-170 in the dashboard → banner appears with "QA-170 Search Test" (human-readable name)
2. Click "Run Static Test" → terminal streams Playwright output
3. Select a random VC2-XXXX → proceeds to REVIEW mode normally
4. Select QA-196 → shows all matched tests with human-readable names
5. Click "Use AI Agent Instead" → REVIEW mode as before
6. Open Playwright Library page → all card headers show human-readable names (e.g., "QA-172 Sales Test"), not raw filenames

---

## Creative Phases

- [x] Architecture design: NOT REQUIRED — straightforward extension of existing patterns
- [x] UI/UX design: RECOMMENDED — banner layout and multi-match list UX (completed in auto-route-jira-cards-to-existing-playwright-tests-uiux.md and auto-route-jira-cards-to-existing-playwright-tests-user-journey.md)

---

## Execution State

**Build Status**: IDLE
**Current Phase**: BUILD
**Can Resume**: YES
5 - Report Completion - COMPLETE
**Can Resume**: YES
