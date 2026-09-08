---
legacy_id: FEAT-086
version: v1.0.0-prod-readiness
linked_tasks: []
status: planned
---

### FEAT-086: HITL Skip Reason Report Persistence
- **Version**: v1.0.0-prod-readiness
- **Status**: planned
- **Priority**: low
- **Complexity**: Level 1
- **Pillar**: P3 — AC Review / HITL UX
- **Gap ID**: P3-C
- **Estimated Effort**: <1h
- **Description**: The HITL skip reason is not written to the run report, making it impossible for human reviewers to distinguish `OPERATOR_SKIP` from budget-exhaustion skips in audit reports. Fix: persist the skip reason enum value and the operator-provided explanation text to the step result in the run report.
- **Acceptance Criteria**:
  - AC-1: Step results include a `skip_reason` field with values `OPERATOR_SKIP`, `BUDGET_EXHAUSTED`, or `TIMEOUT`.
  - AC-2: For `OPERATOR_SKIP`, the operator's explanation text is also persisted in `skip_explanation`.
  - AC-3: The HTML audit report renders the skip reason and explanation for skipped steps.
- **Key Files**:
  - `backend/engine/human_takeover.py` — `skip_takeover()`
  - `backend/engine/reporter.py` — step result schema
- **Linked Tasks**: None
- **Branch**: feature/FEAT-086-hitl-skip-reason-report
- **Created**: 2026-06-03
