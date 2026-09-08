---
legacy_id: FEAT-108
version: next
linked_tasks: [auto-route-jira-cards-to-existing-playwright-tests, auto-route-jira-cards-to-existing-playwright-tests]
status: complete
---

  ### FEAT-108: Auto-Route Jira Cards to Existing Playwright Tests
- **Version**: next
- **Status**: completed
- **Priority**: high
- **Complexity**: Level 3
- **Description**: When a user selects a Jira card in the "Run a Test" flow, the system should check if there's already a static Playwright test mapped to that card via `playwright_index.json`. If so, skip the AI agent entirely and run the existing test via `POST /playwright/run`. The pieces (index file, registry, schema `execution_engine: "static"`) already exist but are not wired together.
    1. **Backend Test-Match Lookup**: Add `get_tests_by_jira_key(key)` to `PlaywrightRegistry` and expose a new `GET /playwright/match/{ticket_id}` endpoint that returns `{ matched: bool, tests: [...] }` for lightweight, read-only ticket-to-test lookups.
    2. **Frontend Auto-Detection**: In `SelectView.handleSelectTicket()`, call the match endpoint after the user clicks a ticket. If a match is found, show a banner ("🎭 Static Playwright test found") with a "Run Static Test" action.
    3. **Static Test Execution Routing**: When the user opts for the static test, skip the REVIEW/AI agent flow entirely and launch via `POST /playwright/run` with the matched test ID. Stream output via the existing WebSocket terminal.
- **Acceptance Criteria**:
    - AC-1: `PlaywrightRegistry.get_tests_by_jira_key(key)` returns all tests whose `jira_keys` array contains the given key.
    - AC-2: `GET /api/playwright/match/{ticket_id}` returns `{ matched: true, tests: [...] }` when a static test exists, `{ matched: false, tests: [] }` when none.
    - AC-3: Selecting a Jira card with a mapped static test (e.g., QA-170) shows a banner offering to run the static test directly.
    - AC-4: Clicking "Run Static Test" launches the test via `POST /playwright/run` and streams output through the existing WebSocket terminal — no AI agent involved.
    - AC-5: Selecting a Jira card with NO mapped static test proceeds to the existing AI agent flow with zero changes.
    - AC-6: Cards with multiple mapped tests (e.g., QA-196) display all matched tests for selection.
- **Open Questions**:
    - **UX Decision**: Run inline (same page, new UI mode) vs. redirect to Playwright Library vs. choice banner (static test or AI agent)?
    - **Dual-coverage cards**: Cards with both a static test AND AI-testable ACs — always prefer static, let user choose, or run static first then fall back to AI?
- **Key Files**:
    - `backend/storage/playwright_registry.py` (Modify — add `get_tests_by_jira_key`)
    - `backend/api/playwright_routes.py` (Modify — add `/match/{ticket_id}` endpoint)
    - `frontend/src/components/SelectView.tsx` (Modify — auto-detect + banner)
    - `frontend/src/components/RunTestView.tsx` (Modify — static test execution mode)
    - `playwright/playwright_index.json` (Read-only — existing test-to-Jira mapping)
- **Linked Tasks**: [auto-route-jira-cards-to-existing-playwright-tests](tasks/auto-route-jira-cards-to-existing-playwright-tests.md)
- **Branch**: feature/FEAT-108-auto-route-playwright
- **Created**: 2026-06-08
