# Playwright Automation Execution Plan: JIRA QA Migration

## 1. Executive Summary & Velocity Goals
**Objective:** Transition 48 manual JIRA QA tests to automated Playwright scripts.
**Target Velocity:** 12 tests per quarter (48 per year, covering our current backlog with room for deep validation tasks like memory profiling).
**Current Status (End of Q1):** ~11 Working Tests.
**Q2 Goal:** +12 New Tests (Total 23).

### The "Exponential Velocity" Strategy
The plan is front-loaded with **"Lego Brick™" development**. By prioritizing core helpers (Login, Navigation, Search, Order Creation) in Q1, the complex E2E workflows in Q3/Q4 will be completed 3x faster because 90% of their logic will already exist as reusable functions. While Q1 velocity (11 tests) was slightly lower than raw ticket counts, the robust infrastructure built guarantees stability and faster delivery moving forward.

---

## 2. Q1 Roadmap (Completed)
**Focus:** Infrastructure, Auth, and High-Frequency UI Interactions.

| Priority    | Issue Key       | Task                  | Product UI Overlap                                 |
| :---        | :---            | :---                  | :---                                               |
| **DONE**    | **QA-298**      | Folder Logic          | Sidebar navigation, badge count scraping.          |
| **DONE**    | **QA-170**      | Search & Filtering    | Global search bar, result list verification.       |
| **DONE**    | **QA-204**      | New Client Order      | Creation and approval                              |
| **DONE**    | **QA-58/59**    | POC Assignments       | POC dropdowns within the List View grid.           |
| **DONE**    | **QA-46**       | Ad Type changes       | Ad Type and required fields                        |
| **DONE**    | **QA-247**      | Hover State           | Tooltip and metadata visibility on hover.          |
| **DONE**    | **QA-185**      | Saved Search Sharing  | Folder visibility and permissions.                 |
| **DONE**    | **QA-279**      | Email Function        | Sidebar checkboxes and "Send Email" modal.         |
| **DONE**    | **QA-175**      | Locked Spots          | Multi-session concurrency / editing locks.         |
| **DONE**    | **QA-254**      | Manual Archives       | Archive cleanup and legacy data handling.          |

---

## 3. Q2 Roadmap: Foundation Roll-Over & Functional Regression
**Focus:** Completing Q1 blockers and standard Business Rules.
**Goal:** 12 Tests (23 Cumulative).

| Priority    | Issue Key           | Task                      | Product UI Overlap                            |
| :---        | :---                | :---                      | :---                                          |
| **DONE**    | **QA-100**          | Library                   | Script Library                                |
| **DONE**    | **QA-101**          | Merging                   | Client Merging tools                          |
| **DONE**    | **QA-197**          | Revision Process          | Status transitions (Active -> Revision).      |
| **WIP**     | **VC2-8821/8983**   | Memory Leak Detection     | CDP heap profiling, repeat-action pattern.    |
| **BLOCKED** | **QA-203**          | Date Pickers              | Calendar widget and "Past Due" logic (Awaiting RC on QA). |
| **BLOCKED** | **QA-125**          | Auth / New User account   | Creation and approval /wizard / TD-256        |
| **To Do**   | **QA-113/115**      | Admin Roles               | DemoProdDirector & TrafficDirector views.     |
| **To Do**   | **QA-117/119**      | Specialist Roles          | DemoDigitalDir & DemoVoicer views.            |
| **To Do**   | **QA-157**          | Large Orders              | Performance/timeout testing for bulk orders.  |
| **To Do**   | **QA-166**          | Notifications             | Toast messages and in-app alerts.             |
| **Should**  | **QA-277**          | Browser Matrix            | Playwright Config for Safari/Edge/Firefox.    |
| **Nice**    | **QA-227**          | Labeling                  | Categorization and tagging UI.                |

---

## 4. Q3 Roadmap: Role Completions & Core Workflows
**Focus:** Remaining Role Dashboards and Core Multi-user E2E Workflows.
**Goal:** 12 Tests (35 Cumulative).

| Priority      | Issue Key       | Task                      | Complexity Factor                                |
| :---          | :---            | :---                      | :---                                             |
| **Must Do**   | **QA-120**      | User Roles                | DemoWriter view.                                 |
| **Must Do**   | **QA-122**      | User Roles                | DemoProdMan view.                                |
| **Must Do**   | **QA-123**      | User Roles                | DemoProdWoman view.                              |
| **Must Do**   | **QA-147**      | Client Workflows          | ALPS workflow.                                   |
| **Must Do**   | **QA-260**      | Firm Workflows            | Pillar/AccessMore/Radio Imaging                  |
| **Must Do**   | **QA-258**      | Firm Regression           | Pattison, Bell, Shark, CPR                       |
| **Must Do**   | **QA-172**      | View States               | Compact View and Saved Search persistence.       |
| **Must Do**   | **QA-253**      | Bulk Testing              | Mass status updates and batch actions.           |
| **Should**    | **QA-187**      | RC Features               | Release Candidate functionality checks.          |
| **Should**    | **QA-211**      | Autoscript                | Automated script generation validation.          |
| **Nice**      | **QA-193**      | Context Menus             | Right-click menu across the List View.           |
| **Nice**      | **QA-138**      | Admin Account             | Super-user permission and account checks.        |
| **Should**    | **QA-192**      | C/E/R Logic               | Complex Copy/Edit/Revise workflows.              |

---

## 5. Q4 Roadmap: Edge Cases & Integrations
**Focus:** External Integrations, Complex Workflows, and System Stress.
**Goal:** 11+ Tests (46+ Cumulative).

| Priority      | Issue Key       | Task                      | Complexity Factor                               |
| :---          | :---            | :---                      | :---                                            |
| **Must Do**   | **QA-186**      | Real-Time Updates         | WebSockets/SignalR verification (Live UI).      |
| **Should**    | **QA-205/207**  | Integrations              | Autodub and WideOrbit synchronization logic.    |
| **Should**    | **QA-62/63**    | Specialized Inbox         | Voice Requests and All Swim/Audition pools.     |
| **Must Do**   | **QA-284**      | Yaman/CCC                 | External URL hand-off (CCC -> vProMedia).       |
| **Should**    | **QA-202**      | Blog Function             | Comment threads and collaboration UI.           |
| **Should**    | **QA-241**      | User Station Mgmt         | Permission-based station updating logic.        |
| **Should**    | **QA-231**      | Migration Check           | vPPO to vProMedia file verification.            |
| **Nice**      | **QA-96/97**    | Settings                  | Account settings and OOO persistence.           |

---

## 6. Technical Strategy for Antigravity IDE
To maintain this velocity, the following **Page Object Model (POM)** structure should be maintained in your Playwright scaffolding:

### **Required Global Helpers (Phase 1 Build)**
1.  **`loginHelper.ts`**: Contains `login(page, username, password, baseURL)`, `logout()`, and `loginWithStoredSession(page, storageStatePath)`.
2.  **`NavHelper.ts`**: Contains `goToFolder(name)` and `openSpot(id)`.
3.  **`OrderHelper.ts`**: Contains `createBasicOrder(details)` and `submitOrder()`.
4.  **`ViewHelper.ts`**: Contains `getRowCount()`, `assignPOC(row, role, name)`, and `changeStatus(row, status)`.

### **Agent Interaction Prompting**
When using the Antigravity Agent, use the following context-injection:
> *"I am working on [Issue Key]. Please use the existing `OrderHelper` to create the initial spot, then use `AuthHelper.ghostAs()` to switch to the [Writer/Producer] role as described in the JIRA steps. Only write the test logic; the helper functions are already in the project."*

---

## 7. CI/CD & Concurrency Guardrails

### **Shared User Parallelism Risk**
Running tests across multiple browser families (Chromium, Firefox, Webkit) simultaneously with the same user account will trigger the **vSuite UI Lockout mechanism** for "Write" operations (Edits, Submissions, Archives).

> [!WARNING]
> **Project Collision:** Playwright runs `projects` in parallel by default. Workers on different browsers using the same `currentUser` will collide on row-level locks, leading to false-positive failures in CI.

### **Mitigation Strategies**
*   **Project Isolation**: In CI, run mutation-heavy suites (Orders, Status Changes) against a single project (e.g., `--project=chromium`) to ensure high reliability.
*   **Worker Restriction**: If cross-browser verification is required for a single user, force sequential execution: `npx playwright test --workers=1`.
*   **Account Sharding**: For large-scale parallel runs, assign unique test accounts to specific browser/worker instances.
*   **Read-Only Concurrency**: Tests that only perform "Read" operations (like folder count verification) are safe for parallel cross-browser execution.
