---
legacy_id: FEAT-007
version: v1.1.0
linked_tasks: []
status: complete
---

### FEAT-007: Composite Action Types
- **Version**: v1.1.0
- **Status**: complete
- **Priority**: low
- **Complexity**: Level 2
- **Description**: The executor previously required separate planner iterations for compound interactions like fill-then-submit, click-then-wait, and select-then-verify, inflating action counts and wasting LLM calls. Added three composite action types to executor.py: (1) fill_and_submit — fill a field and either press Enter or click a named submit button in one atomic action, with FixtureManager stamping and child-input fallback inherited from the standard fill handler. (2) click_and_wait — click an element and wait up to 10s for a specified CSS selector to become visible or text to appear in the DOM, combining what previously required two separate planner iterations. (3) select_and_verify — select a dropdown option and verify the result by checking the dropdown's visible label or full page text content. Each composite action falls back gracefully to partial success if the compound sub-step fails (COMPOSITE_PARTIAL_SUCCESS diagnostic), preserving the first sub-action's result and letting the planner handle the second step separately. All three produce a single ExecutionStep in the audit log. Schema layer: 3 new action types in PlannerAction Literal + 5 new fields (submit_strategy, submit_name, wait_for_selector, wait_for_text, verify_text) + cross-field validators. Validator layer: 3 entries in _REQUIRED_FIELDS. Executor: composite types registered in LOCATOR_ACTIONS, transient capture, and network sync. PLANNER_TOOL_CONFIG auto-regenerates with new types at import time. 33 tests passing, 0 regressions.
- **Linked Tasks**: None
- **Branch**: feature/FEAT-007-composite-action-types
- **Created**: 2026-05-07
- **Completed**: 2026-05-08
