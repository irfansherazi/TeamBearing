---
legacy_id: FEAT-081
version: v1.0.0-prod-readiness
linked_tasks: []
status: planned
---

### FEAT-081: PrimeNG p-sidebar Overlay Dismissal
- **Version**: v1.0.0-prod-readiness
- **Status**: planned
- **Priority**: low
- **Complexity**: Level 1
- **Pillar**: P2 — Execution Engine Reliability
- **Gap ID**: P2-C
- **Estimated Effort**: <1h
- **Description**: `_dismiss_overlays()` does not handle PrimeNG `p-sidebar` components, which block clicks and do not close on Escape. Fix: add a `p-sidebar` detection step that clicks the sidebar's close button (`button.p-sidebar-close`) before proceeding with the planned action.
- **Acceptance Criteria**:
  - AC-1: `_dismiss_overlays()` detects an open `p-sidebar` via `.p-sidebar:not(.ng-hide)` selector.
  - AC-2: When detected, it clicks `button.p-sidebar-close` to dismiss the sidebar.
  - AC-3: Falls back to clicking outside the sidebar bounds if the close button is not found.
  - AC-4: No regression on existing modal/toast/overlay dismissal flows.
- **Key Files**:
  - `backend/engine/executor.py` — `_dismiss_overlays()`
- **Linked Tasks**: None
- **Branch**: feature/FEAT-081-primeng-sidebar-dismissal
- **Created**: 2026-06-03
