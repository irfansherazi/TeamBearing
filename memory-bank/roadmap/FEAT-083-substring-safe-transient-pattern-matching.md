---
legacy_id: FEAT-083
version: v1.0.0-prod-readiness
linked_tasks: []
status: planned
---

### FEAT-083: Substring-Safe Transient Pattern Matching
- **Version**: v1.0.0-prod-readiness
- **Status**: planned
- **Priority**: medium
- **Complexity**: Level 1
- **Pillar**: P2 — Execution Engine Reliability
- **Gap ID**: P2-E
- **Estimated Effort**: ~1h
- **Description**: The transient pattern `.active` is matched as a substring, incorrectly auto-satisfying verifications for `.active-tab`, `.active-row`, and `.active-user` elements. Fix: change all transient pattern lookups to use whole-class boundary matching (regex word boundary) instead of substring `in` checks.
- **Acceptance Criteria**:
  - AC-1: Pattern `.active` does not match elements whose class includes `active-tab`, `active-row`, or `active-user`.
  - AC-2: Pattern `.active` still matches elements with exactly `active` in their class list.
  - AC-3: All transient pattern checks in the verifier use boundary-aware regex (not raw substring `in`).
  - AC-4: Unit tests cover true-positive and false-positive cases for all existing transient patterns.
- **Key Files**:
  - `backend/engine/verifier.py` — transient pattern checker
- **Linked Tasks**: None
- **Branch**: feature/FEAT-083-substring-safe-pattern-matching
- **Created**: 2026-06-03
