# UI/UX Decision: auto-route-jira-cards-to-existing-playwright-tests Auto-Route Jira Cards to Existing Playwright Tests

**Created**: 2026-06-08
**Status**: DECIDED
**Decision Type**: UI/UX

## User Context

### Target Users
- **Primary**: QA Automation Engineer / Developer - Running tests against known issues or regression suites on the vQA dashboard.
- **Secondary**: Platform Operator - Triggering validation runs to check stability.

### User Goals
1. **Speed & Efficiency**: Avoid waiting for the AI agent (which takes minutes to plan, reason, execute, and evaluate) when a deterministic, fast static Playwright script already exists for the ticket under test.
2. **Clarity**: Immediately see when a static option exists and understand exactly which script(s) are mapped.
3. **Control**: Retain the freedom to run the AI agent instead if the static test is outdated or if a more exploratory run is desired.
4. **Visual Consistency**: The match banner and multi-match UI must integrate seamlessly with the existing dark/light theme and design language established in the UI overhaul (ui-ux-overhaul-and-progressive-disclosure).

### Use Cases
| Use Case | User | Goal | Frequency |
|----------|------|------|-----------|
| **Single-Match Selection** | Operator | Sees 1 test found, launches it immediately in 1 click | Common |
| **Multi-Match Selection** | Operator | Sees multiple tests found (e.g. QA-196), picks the right one to run | Occasional |
| **AI Fallback** | Operator | Chooses to bypass the static test to let the AI agent explore | Occasional |
| **Silent No-Match** | Operator | Selects a card without mapped tests; proceeds to normal AI review flow without visual interruption | Always |

### Constraints
- **Devices**: Desktop only (primary focus).
- **Accessibility**: WCAG AA. Keyboard focusable buttons, visible outline states, and proper screen reader descriptions for test steps.
- **Ecosystem Style**: Must utilize CSS variables from `index.css` (e.g., `--bg-surface`, `--color-primary`, `--border-color`, `--text-secondary`).

---

## Layout & Visual Designs

### Option 1: Inline Match Banner inside SelectView (CHOSEN)
- **Approach**: Insert a dedicated match banner dynamically below the Ticket Dropdown and above the Run Configuration Form inside `SelectView.tsx`.
- **Why**: Keeps the user in the context of configuration, providing an immediate choice right after ticket selection without forcing a mode transition.
- **Wireframe/Layout — Single Match**:
  ```
  ┌────────────────────────────────────────────────────────┐
  │ Ticket Selection Dropdown: [ QA-170: Search bar...  ] │
  ├────────────────────────────────────────────────────────┤
  │                                                        │
  │  ┌──────────────────────────────────────────────────┐  │
  │  │ 🎭 Static Playwright Test Found!                 │  │
  │  │                                                  │  │
  │  │  qa-170-search.test (playwright/tests/search.ts) │  │
  │  │  "Verifies keyword search and pagination filters" │  │
  │  │  Steps: 5 steps mapped                          │  │
  │  │                                                  │  │
  │  │  [ RUN STATIC TEST (Primary) ]                  │  │
  │  │  or Use AI Agent Instead (Secondary Link)        │  │
  │  └──────────────────────────────────────────────────┘  │
  │                                                        │
  │  [ Role: Account Executive  ]  [ Target URL: ... ]    │
  │  ...                                                   │
  └────────────────────────────────────────────────────────┘
  ```

- **Wireframe/Layout — Multi-Match List**:
  ```
  ┌────────────────────────────────────────────────────────┐
  │ Ticket Selection Dropdown: [ QA-196: Orders...     ]  │
  ├────────────────────────────────────────────────────────┤
  │                                                        │
  │  ┌──────────────────────────────────────────────────┐  │
  │  │ 🎭 8 Static Playwright Tests Found for QA-196    │  │
  │  │  Select a test script to execute:                 │  │
  │  │                                                  │  │
  │  │  ┌──────────────────────────────────────────────┐ │  │
  │  │  │ ◉ order-creation.test (6 steps)            │ │  │
  │  │  │   "Verifies quick order entry and dispatch" │ │  │
  │  │  ├──────────────────────────────────────────────┤ │  │
  │  │  │ ◯ order-cancel.test (4 steps)              │ │  │
  │  │  │   "Test workflow cancellation path"         │ │  │
  │  │  ├──────────────────────────────────────────────┤ │  │
  │  │  │ ◯ order-edit-price.test (3 steps)          │ │  │
  │  │  │   "Edit prices and check totals validation" │ │  │
  │  │  └──────────────────────────────────────────────┘ │  │
  │  │                                                  │  │
  │  │  [ RUN SELECTED STATIC TEST (Primary) ]          │  │
  │  │  or Use AI Agent Instead (Secondary Link)        │  │
  │  └──────────────────────────────────────────────────┘  │
  │                                                        │
  │  [ Role: Account Executive  ]  [ Target URL: ... ]    │
  │  ...                                                   │
  └────────────────────────────────────────────────────────┘
  ```

---

## Styling & Theme Adaptation

### Dark Mode CSS Specification
```css
.playwright-match-banner {
  background-color: rgba(30, 41, 59, 0.7); /* slate-800 with transparency */
  border: 1px solid #3b82f6;               /* vibrant blue border */
  border-radius: 8px;
  padding: 16px;
  margin: 16px 0;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
}

.playwright-match-title {
  color: #3b82f6;
  font-weight: 600;
  font-size: 1.05rem;
  display: flex;
  align-items: center;
  gap: 8px;
}

.playwright-match-test-item {
  background-color: rgba(15, 23, 42, 0.6);  /* slate-900 */
  border: 1px solid #334155;                 /* slate-700 */
  border-radius: 6px;
  padding: 12px;
  margin-top: 8px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.playwright-match-test-item:hover {
  border-color: #3b82f6;
  background-color: rgba(59, 130, 246, 0.05);
}

.playwright-match-test-item.selected {
  border-color: #3b82f6;
  background-color: rgba(59, 130, 246, 0.1);
  box-shadow: 0 0 0 1px #3b82f6;
}
```

### Light Mode CSS Specification
```css
.light-mode .playwright-match-banner {
  background-color: #f0f7ff;                /* extremely light blue */
  border: 1px solid #1d4ed8;                /* royal blue border */
  box-shadow: 0 4px 12px rgba(29, 78, 216, 0.08);
}

.light-mode .playwright-match-title {
  color: #1d4ed8;
}

.light-mode .playwright-match-test-item {
  background-color: #ffffff;
  border: 1px solid #e2e8f0;
}

.light-mode .playwright-match-test-item:hover {
  border-color: #1d4ed8;
  background-color: rgba(29, 78, 216, 0.02);
}

.light-mode .playwright-match-test-item.selected {
  border-color: #1d4ed8;
  background-color: rgba(29, 78, 216, 0.05);
  box-shadow: 0 0 0 1px #1d4ed8;
}
```

---

## Interactive State Transitions

1. **Ticket Dropdown Changed**: Trigger `checkPlaywrightMatch(ticket.id)`. Show a subtle loading pulse in the banner container area if match takes >200ms.
2. **Endpoint Returns Matched=True**: Dropdown closes, banner slides open smoothly (`max-height: 0` to `max-height: 500px` CSS transition). Focus is programmatically placed on the "Run Static Test" button.
3. **Single Test**: Directly highlights the test. Clicking "Run Static Test" immediately bypasses review and starts the run.
4. **Multiple Tests**: Defaults selection to the first test. User can click any test card to change selection. Highlight ring updates dynamically.
5. **Dismiss / Fallback**: Clicking "Use AI Agent Instead" clears the banner and immediately triggers the `onTicketSelected` callback, proceeding to the existing REVIEW state machine mode.
