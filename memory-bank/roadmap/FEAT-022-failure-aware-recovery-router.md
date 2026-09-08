---
legacy_id: FEAT-022
version: v2.0.0
linked_tasks: [failure-aware-recovery-router]
status: complete
---

### FEAT-022: Failure-Aware Recovery Router
- **Version**: v2.0.0
- **Status**: complete
- **Priority**: high
- **Complexity**: Level 4
- **Description**: Type-specific recovery strategies in the evaluator that replace the current one-size-fits-all retry→HITL→abort pipeline (FM-4, FM-5). STRICT_MODE auto-injects container_selector from DOM context. TIMEOUT increases wait and checks for spinner. NOT_VISIBLE opens parent accordion/tab/sidebar via DOM traversal. DETACHED waits 500ms for Angular re-render. INTERCEPTED auto-presses Escape or clicks overlay backdrop. Each strategy is feature-flagged for safe rollout. Requires evaluator routing refactor, executor auto-recovery hooks, state schema changes, and per-failure-type recovery handlers. Phased implementation needed.
- **Linked Tasks**: failure-aware-recovery-router (COMPLETE)
- **Branch**: feature/failure-aware-recovery-router-failure-aware-recovery
- **Created**: 2026-05-11
- **Completed**: 2026-05-11
