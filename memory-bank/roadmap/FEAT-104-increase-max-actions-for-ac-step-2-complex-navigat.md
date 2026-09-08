---
legacy_id: FEAT-104
version: v1.0.0-prod-readiness
linked_tasks: [production-readiness-kb-workflows-hitl-reminder-sales-exec-c, production-readiness-kb-workflows-hitl-reminder-sales-exec-c]
status: complete
---

### FEAT-104: Increase max_actions for AC Step 2 Complex Navigation
- **Version**: v1.0.0-prod-readiness
- **Status**: complete ✅
- **Priority**: medium
- **Complexity**: Level 2
- **Pillar**: P2 — AC Parsing & Execution Budget
- **Description**: The AC parser uses a default `_ac_cap = 15` max actions per step. For AC Step 2 scenarios involving complex navigation (e.g., locating a spot with a "View Script" link in the Files column, which may require scrolling through many rows), 15 actions is often insufficient. Add support for a `max_actions` override field in the structured AC step definition so that individual steps can declare a higher budget (e.g., `max_actions: 20`) without changing the global default.
- **Acceptance Criteria**:
  - AC-1: The `ACStep` schema (or equivalent dataclass in `ac_parser.py`) accepts an optional `max_actions: int` field.
  - AC-2: When `max_actions` is set on a step, the executor respects that step-level budget instead of the global `_ac_cap`.
  - AC-3: Step 2 of the QA-100 test plan is annotated with `max_actions: 20` in the generated TestPlan.
  - AC-4: The global default `_ac_cap` remains unchanged (no regression for steps that do not specify `max_actions`).
  - AC-5: A unit test verifies that step-level `max_actions` overrides the global cap correctly.
- **Key Files**:
  - `backend/engine/ac_parser.py`
  - `backend/engine/schemas.py`
  - `tests/unit/test_ac_parser.py`
- **Linked Tasks**: [production-readiness-kb-workflows-hitl-reminder-sales-exec-c](tasks/production-readiness-kb-workflows-hitl-reminder-sales-exec-c.md)
- **Branch**: feature/FEAT-104-step-max-actions-override
- **Created**: 2026-06-03
