---
legacy_id: FEAT-021
version: v2.0.0
linked_tasks: [per-step-iteration-budget]
status: complete
---

### FEAT-021: Per-Step Iteration Budget
- **Version**: v2.0.0
- **Status**: complete
- **Priority**: high
- **Complexity**: Level 2
- **Description**: Adaptive per-AC-step iteration allocation to prevent a single stuck step from consuming the entire run's iteration budget (FM-2). On entry to each AC step, allocate `min(30, remaining_budget / remaining_steps)` iterations. If a step exceeds its budget, mark it as SKIPPED (not FAILED) and advance. Reporter flags skipped steps for human review. Touches evaluator.py routing logic and config.py.
- **Linked Tasks**: per-step-iteration-budget (COMPLETE)
- **Branch**: feature/per-step-iteration-budget-per-step-budget
- **Created**: 2026-05-11
- **Completed**: 2026-05-11
