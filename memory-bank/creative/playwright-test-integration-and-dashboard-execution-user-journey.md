# playwright-test-integration-and-dashboard-execution: Playwright Test Integration User Journey

## User Persona: Quality Engineer (QE)
A QE wants to run a specific, high-reliability smoke test script before performing more exploratory AI-driven testing.

## Journey Steps

### 1. Selection & Configuration
1. User navigates to the vQA Dashboard.
2. User clicks the **"Execution Mode"** toggle in the sidebar.
3. User selects **"Playwright (Static)"**.
4. The **Playwright Library** appears.
5. User types "Quick Order" into the search bar.
6. User clicks **"Select"** on the "Login & Quick Order Smoke Test" item.
7. User selects a **Target Environment** (e.g., "QA196").
8. (Optional) User enters a **Jira Ticket ID** to link the run history.

### 2. Execution Initiation
1. User clicks the **"Run Static Test"** button.
2. The UI transitions to the **Execution View**.
3. The sidebar collapses, and the main workspace splits between the **Live Browser (VNC)** and the **Terminal Log**.

### 3. Monitoring the Run
1. User observes the **Live Browser** as Playwright navigates to the login page, fills credentials, and creates a Quick Order.
2. Simultaneously, the **Terminal Log** streams the familiar `npx playwright test` output, showing test counts, durations, and step completion.
3. User sees "✓ 1 passed (12s)" in the terminal.

### 4. Completion & Reporting
1. The run finishes.
2. The **Status Banner** at the top turns green: **"Playwright Test Passed"**.
3. User clicks **"View Full Report"**.
4. The report shows the terminal output as the "Execution Log" and includes the session recording.
5. The run is saved in the history, linked to the Jira ticket if provided.

### 5. Failure Path
1. If the test fails (e.g., a timeout), the **Terminal Log** displays the failure stack trace.
2. The **Status Banner** turns red: **"Playwright Test Failed"**.
3. User can review the log and the VNC state (which remains open at the point of failure) to triage the issue.
4. User clicks **"Rerun"** after fixing the environment/configuration.
