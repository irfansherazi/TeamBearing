# User Journey Design: parallel-headless-suite-runner-with-pass-fail-report Parallel Headless Suite Runner

**Created**: 2026-06-09
**Status**: DECIDED
**Decision Type**: User Journey
**Task**: parallel-headless-suite-runner-with-pass-fail-report / FEAT-109

---

## Journey Overview

**Feature**: FEAT-109: Parallel Headless Suite Runner with Pass/Fail Report
**Primary Persona**: QA Automation Engineer, Release Manager, Product Owner
**Journey Type**: Interactive Dashboard Flow
**Orchestration Pattern**: Dashboard Suite Trigger + Asynchronous Polling + Expandable Error Inspection

### Success Statement
> A Quality Assurance Engineer lands on the Playwright Library page, clicks "▶ Run All Tests", and watches the dashboard instantly transition to a rich, dynamic suite execution workspace. The system executes all 40+ tests concurrently, strictly bounded by server thread limits. While running, the engineer can inspect real-time progress. On completion, the engineer can instantly identify failed tests at the top of the table, expand them to read exact error traces, and diagnose failures without ever needing SSH access, command-line runs, or S3 bucket exploration.

---

## Persona Context

### Primary Persona: QA Automation Engineer
- **Who**: Writes, manages, and executes the regression test library.
- **Goal**: Quickly verify entire application-wide regressions before staging a deployment.
- **Pain Points**: Running tests one by one is tedious; watching command-line suites requires terminal access; raw log exploration is time-consuming.
- **Needs**: An automated, parallel, headless runner directly in the UI that spits out clean, structured errors for failures.

### Secondary Persona: Product Owner / Release Manager
- **Who**: Evaluates product readiness and signs off on release candidate builds.
- **Goal**: See a green "regression passed" indicator with high confidence.
- **Needs**: High-level KPI summary metrics (Total, Passed, Failed) that are easy to digest in a single glance.

---

## Journey Maps

### Journey 1: Launching and Monitoring the Suite

```
[QA Engineer lands on Playwright Library Page]
  │
  ├──► Views list of 41 tests on the left and standard single-test runner on the right
  │
  ▼
[Click "▶ Run All Tests" in the right column]
  │
  ├──(1) UI instantly hides test selection, config controls, and terminal logs
  ├──(2) Right-hand panel transitions to <SuiteResultsPanel />
  ├──(3) In-memory timer begins counting up (e.g. "0:01", "0:02"...)
  ├──(4) Summary KPI card renders: Total: 41 | Passed: 0 | Failed: 0
  ├──(5) Table lists all 41 tests in a gray "Pending..." state
  │
  ▼
[Background workers start running]
  │
  ├──(1) 4 concurrent workers spin up headless Playwright subprocesses
  ├──(2) Mapped rows transition to amber "Running..." badges
  ├──(3) As tests finish:
  │         ├──► PASS ──► Row flashes green, badge turns green "PASS", Passed KPI increments
  │         └──► FAIL ──► Row flashes red, badge turns red "FAIL", Failed KPI increments, row floats to top
  │
  ▼
[Suite completes execution]
  │
  ├──► Timer stops and highlights total elapsed time
  └──► Green / Red result summary banner displayed
```

---

### Journey 2: Error Triaging and Root Cause Diagnosis

```
[Suite Execution completes with failures (e.g. 39 Passed, 2 Failed)]
  │
  ▼
[Identify failures]
  │
  ├──► Failed tests are automatically sorted to the top of the list with a red left border
  │
  ▼
[Inspect first failure: Click on "QA-101: Client Merging" row]
  │
  ├──► Row expands downwards in an accordion fashion
  ├──► Renders a nested terminal code-block displaying the error traceback:
  │      "TimeoutError: Execution exceeded 180 seconds"
  │
  ▼
[Inspect second failure: Click on "QA-172: Sales Test" row]
  │
  ├──► Row expands downwards
  ├──► Renders error block with exact assertion exception:
  │      "AssertionError: Expected element 'button#submit-order' to be visible, but got hidden instead."
  │
  ▼
[QA Engineer completes triage]
  │
  ├──► Engineer now knows exactly which ticket workflows failed and why
  ├──► Click "◀ Back to Terminal" to reset suite state and resume individual test executions
```

---

### Journey 3: Browser Reload and Persistence Protection

```
[Suite is running at 50% progress (e.g. 20/41 completed)]
  │
  ▼
[User triggers browser reload or navigates to "Sessions" and back]
  │
  ▼
[PlaywrightPage mounts]
  │
  ├──(1) React hook reads `activeSuiteRunId` (restored from state or session variables)
  ├──(2) Component sends a GET request to `/api/playwright/run-all/{suite_run_id}/report`
  ├──(3) Backend returns the active run-report JSON showing "status": "running"
  │
  ▼
[UI seamlessly restores state]
  │
  ├──► Swaps view directly to <SuiteResultsPanel /> in "running" state
  ├──► Restores correct elapsed timer value
  └──► Increments passed/failed KPIs and resumes active 1.5s periodic polling
```

---

## State Transition Map

```
                     +---------------------------------------+
                     |                 IDLE                  |
                     +---------------------------------------+
                                         │
                                         │ Click "Run All" / POST /run-all
                                         ▼
                     +---------------------------------------+
                     |               RUNNING                 |◄────────┐
                     +---------------------------------------+         │
                                         │                             │ Page Reload /
                                         │ All background tests finish │ Poll GET /report
                                         ▼                             │
+-------------------+      +---------------------------------+         │
|   BACK TO IDLE    |◄──── |      COMPLETED / FAILED         |─────────┘
|  (Click "Back")   |      +---------------------------------+
+-------------------+
```
