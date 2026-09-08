# User Journey Design: auto-route-jira-cards-to-existing-playwright-tests Auto-Route Jira Cards to Existing Playwright Tests

**Created**: 2026-06-08
**Status**: DECIDED
**Decision Type**: User Journey
**Task**: auto-route-jira-cards-to-existing-playwright-tests / FEAT-108

## Journey Overview

**Feature**: FEAT-108: Auto-Route Jira Cards to Existing Playwright Tests
**Primary Persona**: QA Automation Engineer, Platform Operator
**Journey Type**: Functional End-to-End User Verification and Execution Shortcut
**Orchestration Pattern**: Interactive Dashboard Controls, Fast-path Run Execution

### Success Statement
> A QA Automation Engineer selects a JIRA card (like QA-170) on the run-test view. The dashboard instantly detects that a matching static Playwright test exists. Instead of transitioning immediately to step review and launching an AI run, the UI shows a beautiful banner offering to run the static test. The user clicks "Run Static Test," which skips the AI loop completely, launches the test runner subprocess via `POST /playwright/run`, and streams terminal output in real-time.

---

## Journey Maps

### Entry Points
| Entry | Context | User Intent |
|-------|---------|-------------|
| Ticket Dropdown Select | SelectView on `RunTestView` dashboard | Choose a ticket and find if a fast-path static test exists. |
| Match Banner Click | Playwright Match Banner inside `SelectView` | Launch the static test or fall back to the AI-driven agent execution. |

---

### Journey 1 — Ticket Mapped to Single Static Playwright Test (Happy Path)

```
[User opens Run a Test page]
  → SelectView is loaded, state is `uiMode = 'select'`
  
[User searches for and selects "QA-170"]
  → Calls `checkPlaywrightMatch("QA-170")` on ticket select in parallel with `runCredCheck`
  
[System matches 1 static test]
  → Backend returns `{ matched: true, tests: [{ id: "qa-170-search", file: "playwright/tests/search.ts", steps_count: 5, ... }] }`
  
[UI renders Match Banner]
  → Normal immediate redirect to REVIEW mode is suspended
  → An amber-blue banner displays: "🎭 Static Playwright test found for QA-170: qa-170-search.test"
  → Test details (name, description, step count) are shown
  
[User clicks "Run Static Test" button]
  → Calls `onStaticTestSelected("QA-170", "qa-170-search", config)` callback
  → Runs `POST /api/playwright/run` with `test_id: "qa-170-search"` and configuration details
  
[Execution Bypasses Review Mode]
  → `uiMode` transitions directly to `'running'`
  → WebSocket connects to the generated run ID and streams the terminal output of the test
```

---

### Journey 2 — Ticket Mapped to Multiple Static Playwright Tests (Multi-Match)

```
[User searches for and selects "QA-196" (mapped to 8 tests)]
  → Calls `checkPlaywrightMatch("QA-196")`
  
[System matches multiple tests]
  → Backend returns `{ matched: true, tests: [test1, test2, test3, ...] }` (list of 8 tests)
  
[UI renders Match Selection List]
  → Match Banner displays: "🎭 8 Static Playwright tests found for QA-196"
  → A scrollable list of the 8 tests is rendered inside the banner
  → The first test is selected by default
  
[User clicks on the 3rd test item ("order-edit-price.test")]
  → The selected item active state moves to order-edit-price
  
[User clicks "Run Selected Static Test" button]
  → Launches `POST /api/playwright/run` with `test_id: "order-edit-price"`
  → UI transitions directly to RUNNING mode streaming terminal output
```

---

### Journey 3 — Fallback to AI Agent (Optional Bypass)

```
[User selects mapped ticket "QA-170"]
  → Match banner is shown for "qa-170-search.test"
  
[User wants exploratory/AI-driven run instead]
  → User clicks "Use AI Agent Instead" secondary link
  
[System transitions to Review Mode]
  → Match banner is dismissed
  → System calls `onTicketSelected("QA-170", config)`
  → UI transitions to `uiMode = 'review'` (normal AI agent path)
```

---

### Journey 4 — Ticket with No Mapped Tests (Silent No-Match)

```
[User selects ticket "VC2-9999" (no maps exist)]
  → Calls `checkPlaywrightMatch("VC2-9999")`
  
[System matches 0 tests]
  → Backend returns `{ matched: false, tests: [] }`
  
[System transitions silently]
  → No banner is shown, zero UI flicker
  → System immediately calls `onTicketSelected("VC2-9999", config)`
  → UI transitions to `uiMode = 'review'` as per existing behavior
```

---

### Journey 5 — Network/API Resiliency

```
[User selects mapped ticket "QA-170"]
  → System calls `checkPlaywrightMatch("QA-170")`
  → The match endpoint fails (e.g., 500 error or network offline)
  
[UI falls back safely]
  → Error is silently caught in the catch block of SelectView
  → System automatically falls back to normal AI agent flow: immediately triggers `onTicketSelected`
  → UI transitions to `uiMode = 'review'` seamlessly
```
