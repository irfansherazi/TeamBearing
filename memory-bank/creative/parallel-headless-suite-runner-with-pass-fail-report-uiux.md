# UI/UX Design: parallel-headless-suite-runner-with-pass-fail-report Parallel Headless Suite Runner

**Created**: 2026-06-09
**Status**: DECIDED
**Decision Type**: UI/UX Design
**Task**: parallel-headless-suite-runner-with-pass-fail-report / FEAT-109

---

## Overview

parallel-headless-suite-runner-with-pass-fail-report introduces a full suite execution interface inside the Playwright Standard Library page. Since executing 40+ tests in parallel is a dense process, the UI/UX must guide the user clearly:
1. Provide a prominent trigger button that respects lock states.
2. Replace the individual test log stream panel with a consolidated results dashboard (`SuiteResultsPanel`) that is clear, interactive, and fast.
3. Allow digging into failures without leaving the page.

---

## Layout and Placement

The Playwright Library page (`PlaywrightPage.tsx`) has a two-column layout:
- **Left Column**: The list of available tests and the search bar.
- **Right Column**: The execution configuration panel, single-run button, and terminal logs.

When a suite run is triggered, the right column's standard controls are replaced by the `SuiteResultsPanel` to maximize visibility of the aggregate results and avoid visual clutter.

```
+-------------------------------------------------------------------------+
|  🎭 Playwright Library                       📋 Test Library  🔐 Sessions|
+------------------------------------+------------------------------------+
| 🔍 Filter tests... (41 tests)       |  📊 SUITE EXECUTION ACTIVE: Running|
+------------------------------------+------------------------------------+
|  [🎭 QA-100: Script Library    ]   |  +------------------------------+  |
|  [🎭 QA-101: Client Merging    ]   |  | Total: 41 | Passed: 15 (Grn) |  |
|  [🎭 QA-102: Ghost Login       ]   |  | Failed: 1 (Red) | Time: 45s  |  |
|                                    |  +------------------------------+  |
|                                    |                                    |
|                                    |  Executed Tests:                   |
|                                    |  +------------------------------+  |
|                                    |  | QA-100 Script Lib   14s [PASS]|  |
|                                    |  +------------------------------+  |
|                                    |  | QA-101 Client Merge 32s [FAIL]|  |
|                                    |  | > TimeoutError: Execution   |  |
|                                    |  |   exceeded 180 seconds       |  |
|                                    |  +------------------------------+  |
|                                    |  | QA-102 Ghost Login  Pending… |  |
|                                    |  +------------------------------+  |
|                                    |                                    |
|                                    |  [⏹ Stop Suite Run]               |
+------------------------------------+------------------------------------+
```

---

## UI Components & Interactive Elements

### 1. "▶ Run All Tests" Trigger Button
- **Placement**: Nested inside the `pw-run-controls` block, next to the single test run button.
- **Visual styling**: Prominent accent color (`background-color: var(--primary)` or a bold primary button style) to indicate it runs the entire suite.
- **State mapping**:
  - **Idle**: Active and clickable. Text reads `▶ Run All Tests`.
  - **Suite Running**: Active and styled with a secondary color. Text reads `⏹ Stop Suite`.
  - **Single Test Running**: Disabled (`opacity: 0.5; cursor: not-allowed`).
  - **Hover state**: Light scaling delta and hover feedback.

### 2. Suite Summary Header Card
A responsive, high-contrast KPI banner that appears at the top of the results panel. It presents four key metrics in separate flex boxes:
- **Total Tests**: Total count discovered (e.g. `41`).
- **Passed**: The number of passing tests, highlighted with a vibrant green (`color: var(--success)`).
- **Failed**: The number of failing tests, highlighted in crimson red (`color: var(--error)`).
- **Elapsed Time**: Animated timer updated in real-time while running, indicating minutes and seconds elapsed since clicking the button.

### 3. Scrollable Results Table
A robust table displaying every executed test in the suite.
- **Filtering**: Automatically sorted so that **Failed** tests float to the top for immediate triaging, followed by running, passed, and pending tests.
- **Row Columns**:
  - **Name & ID**: Uses `getTestDisplayName` as the primary text, with the raw test ID (e.g., `qa-101.test.ts`) rendered underneath in smaller muted font.
  - **Duration**: Displayed in seconds with decimal points (e.g., `12.5 s`).
  - **Status Badge**:
    - `PASS`: Solid green capsule badge (`background: rgba(16, 185, 129, 0.15); color: #10b981;`).
    - `FAIL`: Solid red capsule badge (`background: rgba(239, 68, 68, 0.15); color: #ef4444;`).
    - `RUNNING`: Pulser amber badge (`background: rgba(245, 158, 11, 0.15); color: #f59e0b;`).
    - `PENDING`: Light gray badge.

### 4. Collapsible Error Panel
- **Behavior**: When a test result row fails, it becomes an expandable accordion. Clicking anywhere on the failed row toggles the accordion open.
- **Visual Presentation**: Expands to show a nested dark code-block (`background: #0f172a; border-radius: 4px; border: 1px solid #334155; margin-top: 8px; font-family: monospace;`) with the exact CLI error snippet/stderr tail scrubbed of passwords.
- **Pointer feedback**: Row shows a pointer cursor and a small arrow icon `▼` next to the status badge to denote expandability.

### 5. "◀ Back to Terminal" Reset Control
- **Purpose**: When the suite run is completed or failed, the panel displays a clean exit button.
- **Action**: Resets `suiteRunStatus` back to `idle`, returning the right-hand column to the standard single-run test selection, config panel, and terminal logs.

---

## Design System Tokens & Classes

To maintain visual cohesion with the vQA dark-themed dashboard, we define the following styling tokens in `frontend/src/index.css`:

```css
/* Suite Results Panel Wrapper */
.suite-results-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  gap: var(--spacing-md, 16px);
}

/* KPI Container */
.suite-kpi-container {
  display: flex;
  gap: var(--spacing-sm, 12px);
  width: 100%;
}

.suite-kpi-card {
  flex: 1;
  background: var(--bg-card, #1e293b);
  border: 1px solid var(--border, #334155);
  border-radius: var(--radius-md, 8px);
  padding: 12px;
  text-align: center;
}

.suite-kpi-card .value {
  font-size: 1.5rem;
  font-weight: 700;
  margin-top: 4px;
}

/* Scrollable Results List */
.suite-results-scroll {
  flex: 1;
  overflow-y: auto;
  border: 1px solid var(--border, #334155);
  border-radius: var(--radius-md, 8px);
  background: var(--bg-terminal, #0b0f19);
  max-height: 450px;
}

.suite-row {
  display: flex;
  flex-direction: column;
  border-bottom: 1px solid var(--border-light, #1e293b);
  padding: 12px;
  transition: background 0.15s ease;
}

.suite-row.fail {
  border-left: 3px solid var(--error, #ef4444);
}

.suite-row.pass {
  border-left: 3px solid var(--success, #10b981);
}

.suite-row-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  cursor: pointer;
}

/* Error Code Block */
.suite-error-block {
  background: #090d16;
  border: 1px solid #ef444430;
  border-radius: 4px;
  padding: 10px;
  margin-top: 8px;
  font-family: var(--font-mono, monospace);
  font-size: 0.8rem;
  color: #fca5a5;
  white-space: pre-wrap;
  word-break: break-all;
}
```
