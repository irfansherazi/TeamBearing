---
legacy_id: FEAT-066
version: next
linked_tasks: [architectural-hardening-and-selector-integrity]
status: complete
---

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
