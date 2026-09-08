---
legacy_id: FEAT-020
version: v2.0.0
linked_tasks: [action-history-buffer]
status: complete
---

### FEAT-020: Action History Buffer
- **Version**: v2.0.0
- **Status**: complete
- **Priority**: high
- **Complexity**: Level 3
- **Description**: Structured rolling window of the last N actions (with outcomes) injected as a `<past_actions>` XML block into the planner system prompt. Hard constraint: "NEVER repeat a strategy that appears in <past_actions> with outcome=FAILED." Eliminates amnesic retry loops (FM-1) where the planner forgets what it already tried and re-uses the same broken locator. Buffer capped at 5 entries, only failed actions included. Touches planner prompt assembly, evaluator state tracking, and VQAState schema.
- **Linked Tasks**: action-history-buffer (COMPLETE)
- **Branch**: feature/action-history-buffer-action-history-buffer
- **Created**: 2026-05-11
- **Completed**: 2026-05-11
