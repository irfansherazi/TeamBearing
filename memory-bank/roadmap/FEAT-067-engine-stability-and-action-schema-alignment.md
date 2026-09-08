---
legacy_id: FEAT-067
version: next
linked_tasks: [engine-stability-and-action-schema-alignment]
status: complete
---

### FEAT-067: Engine Stability and Action Schema Alignment
  - **Version**: next
  - **Status**: complete ✅
  - **Priority**: high
  - **Complexity**: Level 3
  - **Description**: Fix engine stability issues by aligning schemas and verifier logic:
    1. **Stagnant UI Exemptions**: Exempt `scroll`, `press_key`, and `coordinate_action` from stagnant UI delta checks in `verifier.py` to prevent circuit breaker loops.
    2. **Schema Alignment**: Add `window` and `coordinate_action` to the `PlannerAction.strategy` literal in `schemas.py`.
    3. **Executor Robustness**: Ensure `executor.py` gracefully ignores `window` and `coordinate_action` during locator resolution to prevent RAG validation failures.
  - **Acceptance Criteria**:
    - `scroll`, `press_key`, and `coordinate_action` do not trigger "STAGNANT UI" errors in `verifier.py`.
    - `PlannerAction.strategy` in `schemas.py` includes `window` and `coordinate_action`.
    - `executor.py` handles `window` and `coordinate_action` without RAG locator resolution errors.
  - **Key Files**:
    - `backend/engine/verifier.py`
    - `backend/engine/schemas.py`
    - `backend/engine/executor.py`
  - **Linked Tasks**: engine-stability-and-action-schema-alignment
  - **Branch**: feature/FEAT-067-engine-stability
  - **Created**: 2026-06-01

  ### FEAT-066: Architectural Hardening & Selector Integrity
- **Version**: next
- **Status**: complete ✅
- **Priority**: critical
- **Complexity**: Level 4
- **Description**: Fix core issues causing flakiness, infinite loops, and hidden takeover prompts by hardening model escalation, selector logic, and the HITL UI.
    1. **Model Escalation on Verifier Rejections**: Escalate to Sonnet immediately on `retry_count >= 1` for `VERIFIER_REJECTED` and route complex visual checks to Sonnet.
    2. **Selector Integrity**: Ban dynamic framework IDs and deep-DOM selectors in planner prompts; enforce `getByRole`, `getByText`, and `vqa_id`.
    3. **HITL Overlay Restoration**: Wrap `TakeoverPanel` in an overlay with background blur for immediate visibility.
- **Acceptance Criteria**:
    - Escalation to Sonnet triggers on first verifier rejection.
    - Planner prompt explicitly forbids dynamic IDs (e.g., `ui-tabpanel-\d+`).
    - Planner prompt prioritizes semantic and `vqa_id` selectors.
    - HITL panel is centered and overlays the screen with a blurred background.
- **Key Files**:
    - `backend/engine/planner.py`
    - `backend/engine/verifier.py`
    - `frontend/src/components/RunTestView.tsx`
- **Linked Tasks**: architectural-hardening-and-selector-integrity
- **Branch**: feature/FEAT-066-architectural-hardening
- **Created**: 2026-06-01
