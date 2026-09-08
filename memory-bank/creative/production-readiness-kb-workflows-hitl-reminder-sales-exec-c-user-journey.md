# User Journey Design: production-readiness-kb-workflows-hitl-reminder-sales-exec-c Production Readiness Bundle

**Created**: 2026-06-04
**Status**: DECIDED
**Decision Type**: User Journey
**Task**: production-readiness-kb-workflows-hitl-reminder-sales-exec-c / FEAT-100, FEAT-101, FEAT-102, FEAT-103, FEAT-104

## Journey Overview

**Feature**: FEAT-100, FEAT-101, FEAT-102, FEAT-103, FEAT-104: Production Readiness Bundle
**Primary Persona**: QA Automation Engineer, QA Lead, Platform Operator, Sales Executive
**Journey Type**: Functional End-to-End User Verification
**Orchestration Pattern**: Interactive Dashboard Controls, Interactive Takeover Stream, Role-Based Access Control, Raised Execution Caps

### Success Statement
> A Platform Operator or QA Automation Engineer runs the regression suite in production-ready mode. They can seamlessly view text scripts in the files column via slide-out panels, manage Script Template Libraries with appropriate role-based restrictions, receive real-time UI reminders if they forget to demonstrate actions during human-in-the-loop takeovers, and execute deep user-flows with a higher action limit of 15 actions before triggering circuit breakers.

---

## Persona Context

### Primary User: Platform Operator / QA Automation Engineer
- **Who**: Monitors and triages active runs, manages the Knowledge Base, and ensures overall pipeline health.
- **Goal**: Hardened production execution with minimal false interruptions and clear guidance rules.
- **Context**: Working on the vQA dashboard during interactive runs or configuring credentials.

### Secondary User: Sales Executive / Production Director
- **Who**: App users under test within the vSuite system.
- **Goal**: Create and utilize script templates based on role privileges.
- **Different needs**: Production Directors require full read/write privileges, while Sales Executives can only create/apply templates without editing/deleting.

---

## Journey Maps

### Entry Points
| Entry | Context | User Intent |
|-------|---------|-------------|
| "View Script" Link | Files column in JIRA/Production Orders table | Open slide-out drawer with script copy and library utility. |
| "Production" -> "Script Template Library" sidebar | Main navigation rail | View, search, and manage reusable pre-recorded template libraries. |
| Takeover Area Explanation Textbox | Interactive normal HITL panel | Operators typing an explanation without capturing DOM actions receive a reminder. |

---

### Journey 1 — JIRA Production Orders "View Script" Workflow (FEAT-100)

```
[Operator views Production Orders table]
  → Locates any order with a raw script attached in the Files column
  → Clicks on the "View Script" link (matches get_by_text("View Script") with use_first: true)
  
[System state transitions]
  → Slide-out panel slides open from the right side of the screen
  → Panel displays the raw script copy and a "Send Script to library" utility button
  → Verified by checking visibility of panel heading containing the word "Script"
```

---

### Journey 2 — Script Template Library Role Restrictions (FEAT-101)

```
[User navigates to Script Template Library]
  → Click "Production" section in the left sidebar
  → Click "Script Template Library" sub-menu item
  → System renders the library templates table containing Name, Category, Tags, and Script text columns

[Role-Based Authorization Gate Checks]
  → IF logged in as "ProductionDir":
    - Can view all template items
    - Can Create, Edit, and Delete templates (Delete button is fully visible)
  → IF logged in as "Sales Exec":
    - Can view all template items
    - Can Create and Apply templates
    - CANNOT Edit or Delete existing templates (Delete button is hidden)
```

---

### Journey 3 — Human-in-the-Loop DOM Capture Reminder (FEAT-102)

```
[Agent gets stuck during execution]
  → State machine transitions to `human_takeover`
  → System opens the <TakeoverPanel /> on the dashboard

[Operator enters takeover sequence]
  → Operator clicks in the explanation text area and types a text explanation
  → Operator does NOT click/drag/type in the VNC window (hitlActions.length === 0)
  
[Reminder Banner triggers]
  → Stylized amber warning banner appears above the textarea
  → Class: `.takeover-dom-capture-reminder` with warning icon and text:
    "⚠️ Warning: You typed an explanation but have not demonstrated any browser actions. 
     Please interact with the VNC stream above or click Done if this is an explanation-only step."

[Operator interaction branches]
  → Branch A: Operator clicks '✕' dismissal button (.takeover-dom-capture-reminder-dismiss)
    - Banner is hidden and `domReminderDismissed` is set to true
  → Branch B: Operator clicks inside VNC window to perform a click/drag
    - Browser captures DOM action (hitlActions.length > 0)
    - Warning banner is automatically cleared
```

---

### Journey 4 — Sales Executive Credential Provisioning (FEAT-103)

```
[System loads configuration parameters]
  → Reads credentials vault and active .env configuration
  → Resolves Sales Executive user role (`sales_exec`) login credentials
  → Utilizes `ROLE_EMAIL_SALES_EXEC` as specified in the environment
```

---

### Journey 5 — Robust Multi-Step Execution Limits (FEAT-104)

```
[Agent executes complex multi-persona flow]
  → Structured AC step progresses beyond standard action thresholds
  → `StructuredACStep.max_actions` default is raised to 15 to allow deep steps
  → Fallback evaluator cap checks the step actions at 19 (below fallback threshold of 20)
  → Run continues without triggering an early circuit-breaker takeover
  → If action count reaches exactly 20, evaluator triggers human_takeover safely
```
