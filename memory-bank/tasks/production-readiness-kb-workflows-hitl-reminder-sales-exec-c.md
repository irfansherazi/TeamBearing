---
legacy_id: production-readiness-kb-workflows-hitl-reminder-sales-exec-c
---
# production-readiness-kb-workflows-hitl-reminder-sales-exec-c — Production Readiness: KB Workflows, HITL Reminder, Sales Exec Creds, max_actions Override

## Task Metadata
- **ID**: production-readiness-kb-workflows-hitl-reminder-sales-exec-c
- **FEAT IDs**: FEAT-100, FEAT-101, FEAT-102, FEAT-103, FEAT-104
- **Complexity**: Level 2
- **Status**: COMPLETE
- **Created**: 2026-06-03
- **Build Status**: IDLE
- **Branch**: feature/production-readiness-kb-workflows-hitl-reminder-sales-exec-c-prod-readiness-bundle

## Objective

Implement and document five essential production-readiness enhancements within a single consolidated task bundle to harden the end-to-end regression and knowledge base capabilities of the vQA application:

1. **FEAT-100** — KB Workflow: "View Script" link in the Files column of the Production Orders table (`knowledge/vSuite-actions.md`).
2. **FEAT-101** — KB Workflow: Script Template Library navigation, templates table, and role differences (`knowledge/vSuite-actions.md`).
3. **FEAT-102** — HITL DOM Capture Reminder: Display a warning banner in `TakeoverPanel.tsx` when no DOM actions are captured but explanation text is typed.
4. **FEAT-103** — Sales Exec credentials entry: Register `ROLE_EMAIL_SALES_EXEC` in `.env` and `.env.example`.
5. **FEAT-104** — Increase default `max_actions` in `StructuredACStep` from 8 → 15; raise evaluator fallback limit to 20 to prevent premature circuit breaking during long/complex flows.

---

## Detailed Specification

### FEAT-100: "View Script" KB Workflow
- **Context**: The "View Script" link is rendered dynamically within the Files column for specific Production Orders that have attached text scripts. Clicking this opens a slide-out panel on the right with the raw script copy and a "Send Script to library" utility.
- **Selector Strategy**: Must use `get_by_text("View Script")` combined with a `use_first: true` modifier, as multiple rows in the same view may display this link simultaneously. 
- **Verification**: Verify that the panel opens by checking for the visible heading/label containing "Script".

### FEAT-101: Script Template Library KB Workflow
- **Context**: The Script Template Library stores reusable pre-recorded copy templates. Navigated via the left sidebar under the "Production" section.
- **Roles & Permissions**: 
  - `ProductionDir`: Has full read/write/edit and Delete capabilities.
  - `Sales Exec`: Has create/apply template capabilities but CANNOT edit or delete existing ones (Delete button is hidden).
- **Form Fields**: New templates require `Name`, `Category`, `Tags` (optional), and the `Script text` copy block.

### FEAT-102: HITL DOM Capture Reminder Banner
- **Context**: Operators occasionally type an explanation in the takeover text area and click Done without actually demonstrating the workflow in the interactive VNC window. This results in zero captured DOM actions (`hitlActions.length === 0`), causing the agent's learning loop to stall.
- **UI Logic**:
  - Show a stylized amber banner in `TakeoverPanel.tsx` when `explanation` is not empty, `hitlActions.length === 0`, and the reminder has not been explicitly dismissed.
  - Support manual banner dismissal via a `✕` button that sets `domReminderDismissed` to true.
  - Automatically clear the banner if the operator interacts with the browser and `hitlActions.length > 0`.
- **CSS Classes**: Enforce consistent, theme-compliant branding using specific classes (`.takeover-dom-capture-reminder`, `.takeover-dom-capture-reminder-icon`, `.takeover-dom-capture-reminder-text`, `.takeover-dom-capture-reminder-dismiss`).

### FEAT-103: Sales Exec Credentials in Environment
- **Context**: Role-switching steps 6-9 in multi-persona regression runs require authentication as a Sales Executive.
- **Changes**: Document and default `ROLE_EMAIL_SALES_EXEC` variable in `.env.example` and register it in `.env` with a placeholder fallback comment.

### FEAT-104: Raise max_actions Limits
- **Context**: Multi-persona navigation, long data entries, and paginated scroll checks frequently exceed the default limit of 8 actions per AC step, leading to premature human takeovers.
- **Changes**:
  - In `backend/engine/schemas.py`, update `StructuredACStep.max_actions` default to `15`. Update model docstrings.
  - In `backend/engine/evaluator.py`, update fallback `_ac_cap` limit to `20` (from `15`) when no structured test plan exists.

---

## Implementation Roadmap

1. **Phase 1: Knowledge Base Documents**
   - Add detailed `## WORKFLOW: Locate a Spot with a Raw Script in the Files Column` section in `knowledge/vSuite-actions.md`.
   - Add detailed `## WORKFLOW: Script Template Library Navigation` section in `knowledge/vSuite-actions.md`.
   
2. **Phase 2: Frontend HITL Panel Enhancement**
   - In `frontend/src/components/TakeoverPanel.tsx`, add state hooks `showDomCaptureReminder` and `domReminderDismissed`.
   - Update `onChange` on the explanation textarea to call `handleExplanationChange`.
   - Insert banner JSX above the textarea with role="alert" and manual dismiss button.
   - Define layout styling in `frontend/src/index.css`.

3. **Phase 3: Credentials and Config**
   - Add placeholder `ROLE_EMAIL_SALES_EXEC` setting in `.env` and `.env.example`.

4. **Phase 4: Backend Schemas and Evaluator Caps**
   - Update `max_actions: int = Field(default=15, ...)` in `StructuredACStep` in `backend/engine/schemas.py`.
   - Set fallback `_ac_cap = 20` in `evaluator_node` in `backend/engine/evaluator.py`.
   - Add `__test__ = False` to `TestPlan` in `backend/engine/schemas.py` to silence Pytest warnings.

---

## Testing & Verification Strategy

### Automated Unit Testing
- Create `tests/test_task_103_max_actions.py` to assert correct defaults and custom configurations:
  - Test that `StructuredACStep` defaults `max_actions` to `15` and correctly stores overrides.
  - Mock state inside `evaluator_node` to verify that at `19` actions (below fallback limit of 20), no human takeover is triggered.
  - Verify that at `20` actions (at fallback limit of 20), the AC-level circuit breaker fires and redirects to `human_takeover`.
  - Verify that if a step specifies a custom plan limit (e.g. `25`), the evaluator respects it (takeover at `25`, passes at `24`).

### Static Validation
- Run TypeScript compile check: `npx tsc --noEmit`
- Run Python lint check: `ruff check backend/engine/schemas.py backend/engine/evaluator.py`
- Run Pytest suite: `pytest tests/test_task_103_max_actions.py -v`

---

## Acceptance Criteria

### FEAT-100
- [x] New WORKFLOW section in `vSuite-actions.md` with keywords matching "view script", "raw script", "files column"
- [x] Documents `use_first: true` requirement for `get_by_text("View Script")`
- [x] Explains the slide-out panel behavior after click

### FEAT-101
- [x] New WORKFLOW section in `vSuite-actions.md` for Script Template Library navigation
- [x] Keywords match "script template", "library", "template library"
- [x] Documents the nav path to reach the library

### FEAT-102
- [x] Warning banner renders in TakeoverPanel when `hitlActions.length === 0` and operator focuses/types in the explanation textarea
- [x] Banner prompts operator to interact with the browser before submitting
- [x] Banner is dismissible or auto-clears when `hitlActions.length > 0`

### FEAT-103
- [x] `ROLE_EMAIL_SALES_EXEC=` entry in `.env` with a placeholder comment
- [x] `.env.example` also updated

### FEAT-104
- [x] `StructuredACStep.max_actions` default raised from 8 → 15
- [x] Evaluator fallback raised from 15 → 20 when no test_plan exists
- [x] Schema docstring updated to reflect new default

---

## Implementation Progress

- [x] FEAT-100 — vSuite-actions.md: "View Script" Files column workflow added (with `use_first` warning)
- [x] FEAT-101 — vSuite-actions.md: Script Template Library navigation workflow added
- [x] FEAT-102 — TakeoverPanel.tsx: DOM capture reminder banner + CSS in index.css
- [x] FEAT-103 — .env + .env.example: ROLE_EMAIL_SALES_EXEC entry with explanatory comments
- [x] FEAT-104 — schemas.py: max_actions default 8→15; evaluator.py fallback 15→20
- [x] Technical Debt — schemas.py: Added `__test__ = False` on `TestPlan` to eliminate Pytest warnings

---

## Verification Results

- **TypeScript compilation**: `npx tsc --noEmit` — ✅ Passed (No errors)
- **Python linter**: `ruff check` — ✅ Passed (No warnings)
- **Automated pytest run**: `pytest tests/test_task_103_max_actions.py -v` — ✅ Passed (5/5 tests green, 0 warnings)

---

## Execution State
- **Build Status**: COMPLETE
- **Phase Being Built**: Single Phase (all 5 features)
- **Build Completed**: 2026-06-03T20:25:00Z
- **UAT Status**: PASS
- **UAT Completed**: 2026-06-04T12:45:00Z
- **UAT Run ID**: 8f4b2a1c

