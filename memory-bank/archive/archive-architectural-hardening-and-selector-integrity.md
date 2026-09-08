# architectural-hardening-and-selector-integrity: Architectural Hardening & Selector Integrity

## Status
- **Phase**: BUILD
- **Status**: COMPLETE
- **Feature**: FEAT-066
- **Priority**: critical
- **Complexity**: Level 4

## Creative Design Outputs
- [Architecture Design](creative/architectural-hardening-and-selector-integrity-architecture.md)
- [Algorithm Design](creative/architectural-hardening-and-selector-integrity-algorithm.md)
- [UI/UX Design](creative/architectural-hardening-and-selector-integrity-uiux.md)

## Problem Statement
vQA is suffering from flakiness, infinite loops, and hidden takeover prompts. These are caused by:
1.  Slow escalation to capable models when verification fails.
2.  The planner using unstable dynamic selectors or fragile deep-DOM chains.
3.  The Human-In-The-Loop (HITL) takeover panel being obscured by other UI elements or not being sufficiently visible to the operator.

## Acceptance Criteria
1.  **Model Escalation**:
    - `backend/engine/planner.py`: Escalate to Sonnet (heavy model) when `retry_count >= 1` AND the previous state was `VERIFIER_REJECTED`.
    - `backend/engine/verifier.py`: Complex visual checks route to Sonnet instead of Haiku.
2.  **Selector Integrity**:
    - Planner system prompt updated to explicitly BAN dynamic IDs (e.g., matching `ui-tabpanel-\d+`).
    - Planner system prompt updated to explicitly BAN deep-DOM chains (e.g., `div:nth-child(...)`).
    - Planner system prompt updated to MANDATE semantic role selectors (`getByRole`, `getByText`) and `vqa_id` attributes.
3.  **HITL Overlay**:
    - `frontend/src/components/RunTestView.tsx`: `<TakeoverPanel>` is wrapped in a `<div className="takeover-overlay">`.
    - CSS ensures the overlay is centered with a blurred background.

## Technical Plan
### Phase 1: Model Escalation
- [x] Modify `backend/engine/planner.py`: `_invoke_planner_with_tools` to check `retry_count` and `VERIFIER_REJECTED` state.
- [x] Modify `backend/engine/verifier.py`: `_get_verifier_llm` to use Sonnet for complex visual tasks.

### Phase 2: Selector Constraints
- [x] Update `backend/engine/planner.py` (or prompt files): Inject BAN rules into the system prompt.
- [x] Update `backend/engine/planner.py` (or prompt files): Inject MANDATE rules for semantic selectors.

### Phase 3: HITL Overlay
- [x] Modify `frontend/src/components/RunTestView.tsx`: Add the overlay wrapper.
- [x] Update `frontend/src/index.css` (if needed) or check existing `takeover-overlay` styles.

## Verification Plan
### Automated Tests
- [x] Unit test for planner escalation logic.
- [x] Unit test for verifier model selection.
- [x] Snapshot/Component test for frontend overlay.

### Manual Verification
- [x] Trigger a verifier rejection and confirm model switch in logs.
- [x] Observe planner logs to ensure no dynamic/deep selectors are generated.
- [x] Trigger a human takeover and verify the overlay visibility.
