---
legacy_id: FEAT-001
version: v1.1.0
linked_tasks: []
status: complete
---

### FEAT-001: AC Quality Gate & Vague-AC Detection
- **Version**: v1.1.0
- **Status**: complete
- **Priority**: high
- **Complexity**: Level 3
- **Description**: Pre-parse AC quality scorer that evaluates raw Acceptance Criteria text BEFORE Stage 1 BDD normalization. Scores five quality dimensions (specificity, observable outcome, actionability, precondition clarity, scope atomicity) on a 0-2 scale each (max 10 total). Quality grades: GOOD (7-10) = proceed, FAIR (4-6) = warn, POOR (0-3) = hard reject with user prompt to refine. Stage 1 BDD prompt hardened to reject silent invention (rules 9-10: NEVER INVENT + `<inferred>` tags). Semantic validators added to validators.py (component-specificity gate + observable-outcome gate). Quality signals surfaced in HTML audit report (quality banner + per-step badges). 38 tests passing, 0 regressions.
- **Linked Tasks**: None
- **Branch**: feature/FEAT-001-ac-quality-gate
- **Created**: 2026-05-07
- **Completed**: 2026-05-08
