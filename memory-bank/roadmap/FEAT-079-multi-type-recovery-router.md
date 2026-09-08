---
legacy_id: FEAT-079
version: v1.0.0-prod-readiness
linked_tasks: [multi-type-recovery-router-feat-079, multi-type-recovery-router-feat-079]
status: complete
---

### FEAT-079: Multi-Type Recovery Router
- **Version**: v1.0.0-prod-readiness
- **Status**: completed
- **Priority**: critical
- **Complexity**: Level 3
- **Pillar**: P2 — Execution Engine Reliability
- **Gap ID**: P2-A
- **Estimated Effort**: ~3h
- **Description**: The recovery router is currently one-shot per AC step — after one recovery attempt the agent falls into HITL escalation even when a different recovery strategy would succeed. Root cause: `recovery_attempted: bool` flag prevents any further recovery once set. Fix: replace `recovery_attempted: bool` with `recovery_attempted_types: set[str]` and update the recovery router to check whether the proposed recovery type has already been tried.
- **Acceptance Criteria**:
  - AC-1: `VQAState` replaces `recovery_attempted: bool` with `recovery_attempted_types: set[str]`.
  - AC-2: The recovery router checks `recovery_type not in recovery_attempted_types` before routing; only escalates when all applicable recovery types are exhausted.
  - AC-3: Each attempted recovery type is added to `recovery_attempted_types` after dispatch.
  - AC-4: Backward-compatible migration: no existing VQAState serializations break on upgrade.
  - AC-5: Unit tests verify that two distinct recovery types can fire on the same AC step before HITL escalation.
- **Key Files**:
  - `backend/engine/state.py` — `VQAState`
  - `backend/engine/evaluator.py` — recovery router
  - `tests/unit/test_recovery_router.py` (new)
- **Linked Tasks**: [multi-type-recovery-router-feat-079: Multi-Type Recovery Router](tasks/multi-type-recovery-router-feat-079.md)
- **Branch**: feature/FEAT-079-multi-type-recovery-router
- **Created**: 2026-06-03
