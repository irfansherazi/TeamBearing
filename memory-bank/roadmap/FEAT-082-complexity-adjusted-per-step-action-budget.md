---
legacy_id: FEAT-082
version: v1.0.0-prod-readiness
linked_tasks: []
status: planned
---

### FEAT-082: Complexity-Adjusted Per-Step Action Budget
- **Version**: v1.0.0-prod-readiness
- **Status**: planned
- **Priority**: high
- **Complexity**: Level 2
- **Pillar**: P2 — Execution Engine Reliability
- **Gap ID**: P2-D
- **Estimated Effort**: ~2h
- **Description**: `per_step_budget_max` is hardcoded to 15 regardless of AC complexity, causing multi-field form steps to exhaust the budget before verification completes. Fix: compute `max_actions = 5 + (3 × field_count)` in the JSON Compiler prompt, where `field_count` is derived from the number of distinct form field interactions in the AC step plan.
- **Acceptance Criteria**:
  - AC-1: The JSON Compiler prompt includes a `field_count` estimation heuristic that counts distinct fill/select actions in the step plan.
  - AC-2: `max_actions` is computed as `5 + (3 × field_count)` with a hard cap of 40.
  - AC-3: Single-action steps (click, navigate) retain a budget of 8 (5 + 3×1).
  - AC-4: 5-field form steps receive a budget of 20 (5 + 3×5).
  - AC-5: The computed budget is logged per-step in the run audit trail.
- **Key Files**:
  - `backend/engine/planner.py` — JSON Compiler prompt
  - `backend/engine/state.py` — `per_step_budget_max` field
- **Linked Tasks**: None
- **Branch**: feature/FEAT-082-complexity-adjusted-budget
- **Created**: 2026-06-03
