---
legacy_id: FEAT-058
version: v3.0.0
linked_tasks: [feat-058-deterministic-execution-and-loop-prevention]
status: planned
---

### FEAT-058: Deterministic Execution & Loop Prevention
- **Version**: v3.0.0
- **Status**: planned
- **Priority**: high
- **Complexity**: Level 4
- **Description**: Eliminate the classes of "action succeeded, verifier rejected" infinite loops through three integrated strategies:
    1. **Prompt De-confliction**: Resolve direct contradictions between RECIPE MANDATE and P-SELECT EXCEPTION rules in the planner prompt (both currently marked highest priority). Nest exceptions inside the mandate to ensure deterministic behavior.
    2. **Verification Timing**: Add `post_action_wait_ms` to the TestStep schema so the verifier waits for Angular/PrimeNG re-renders before evaluating DOM state, eliminating race conditions in PrimeNG dropdowns.
    3. **Ambiguity Intelligence**: Implement an AC Ambiguity Pre-Check between Stage 1 and Stage 2 to flag untestable goals before execution; add `goal_satisfiable_check` in the verifier node to emit a clean SKIPPED verdict after 2 consecutive rejections instead of looping indefinitely. Ensure all schema changes are backward compatible.
- **Linked Tasks**: feat-058-deterministic-execution-and-loop-prevention
- **Branch**: feature/FEAT-058-deterministic-execution
- **Created**: 2026-05-29
