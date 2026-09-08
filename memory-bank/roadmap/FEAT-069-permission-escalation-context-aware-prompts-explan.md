---
legacy_id: FEAT-069
version: next
linked_tasks: []
status: planned
---

  ### FEAT-069: Permission Escalation, Context-Aware Prompts & Explanation Capture
- **Version**: next
- **Status**: planning
- **Priority**: high
- **Complexity**: Level 3
- **Description**: Add immediate escalation on permission errors, context-aware instructions on takeover, and captured explanation persistence when skipping steps.
    1. **Immediate Escalation on Permission Errors**: Add a "fast-path" circuit breaker in `evaluator_node` (in `evaluator.py`). If an action fails and the error message contains keywords like "permission", "unauthorized", "forbidden", or "access denied", immediately pause the agent and escalate to Human Takeover, preventing the agent from wasting retries on an unrecoverable state.
    2. **Context-Aware User Prompting**: Update the `human_takeover_node` (in `human_takeover.py`). If the error was permission-related, the instructions sent to the frontend will specifically ask the user: "This step may have failed because the current role lacks required permissions. Do you know why this action cannot be completed? Please describe the permission constraint in the Explanation field so the agent can learn it."
    3. **Capture Explanation on Skip**: Update `/human-takeover/done` endpoint and `skip_takeover` function to capture and persist the user's explanation even when skipping, rather than ignoring it.
    4. **Persist Knowledge**: Update the resume logic in `human_takeover_node`. If the user skipped with an explanation, save that explanation directly to `knowledge/human_guidance.md` using the combined HITL KB entry saving logic.
- **Acceptance Criteria**:
    - AC-1: Action failures with keywords "permission", "unauthorized", "forbidden", or "access denied" trigger immediate escalation to Human Takeover from `evaluator_node` without wasting retry loops.
    - AC-2: Permission-related takeovers send customized, context-aware instructions asking the user to describe the permission constraint.
    - AC-3: Skip actions on the done endpoint (`/human-takeover/done` with `skip=true`) capture the user's explanation and pass it to `skip_takeover`.
    - AC-4: Skip explanations are persisted directly to `knowledge/human_guidance.md` using the existing combined HITL KB entry saving logic.
- **Key Files**:
    - `backend/engine/evaluator.py`
    - `backend/engine/human_takeover.py`
    - `backend/api/routes.py`
    - `knowledge/human_guidance.md`
- **Linked Tasks**: None
- **Branch**: feature/FEAT-069-permission-escalation
- **Created**: 2026-06-02
