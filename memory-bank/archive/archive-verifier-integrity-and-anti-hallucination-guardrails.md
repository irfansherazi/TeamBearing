# verifier-integrity-and-anti-hallucination-guardrails: Verifier Integrity & Anti-Hallucination Guardrails

**Feature**: FEAT-063  
**Phase**: ARCHIVE  
**Status**: COMPLETE  
**Created**: 2026-05-31  
**Complexity**: Level 4  
**Branch**: feature/FEAT-063-verifier-integrity-guardrails

---

## Problem Statement

The vQA verifier currently suffers from a systemic trust issue where it can mark AC steps as SATISFIED incorrectly (hallucination). This happens because:
1. **Stale State**: Programmatic checks evaluate stale or pre-action page state.
2. **Missing Gates**: Evaluator routes failed executor actions directly to the verifier.
3. **No Delta Validation**: Verifier cannot distinguish "already passing" from "action caused passing".
4. **No Operator Feedback**: No mechanism for humans to flag false positives and retrain the agent mid-run.
5. **Theme Compliance**: Dropdowns fail to respect the selected light/dark theme.

---

## Acceptance Criteria

| # | Criterion |
|---|-----------|
| AC-1 | Executor failures (TIMEOUT, ERROR, STRICT_MODE_VIOLATION) MUST gate verifier routing; verifier is only invoked on mechanical success. |
| AC-2 | Verifier must always fetch and use a fresh post-action ARIA/DOM snapshot for evaluation. |
| AC-3 | Implement "State Change Verification" (Delta Checks): Verifier must confirm the action actually changed the page state toward the goal. |
| AC-4 | Implement "Human Correction Loop": Operator can pause a run, flag a step as "False Positive", and provide corrective context. |
| AC-5 | All dropdown components (PrimeNG/standard) must respect the active UI theme (light/dark). |
| AC-6 | Comprehensive test suite verifying guardrails against known hallucination patterns. |

---

## Test Strategy

### Unit Tests
- `tests/engine/test_verifier_guardrails.py`:
  - `test_verifier_refuses_failed_executor_action`
  - `test_verifier_uses_fresh_snapshot`
  - `test_state_change_detection_logic`
- `tests/frontend/test_theme_compliance.py`:
  - `test_dropdown_styles_in_light_mode`
  - `test_dropdown_styles_in_dark_mode`

### Integration Tests
- `tests/integration/test_hallucination_prevention.py`:
  - Simulate "already satisfied" state and verify verifier detects no change.
  - Simulate executor timeout and verify verifier is bypassed.

---

## Proposed Changes

### 1. Evaluator Routing Guard
- Modify `evaluator_node` to check `step.success` before routing to `verifier_node`.
- If `success` is False, route to `planner` (retry) or `human_takeover` (escalate) directly.

### 2. Fresh Snapshot Enforcement
- In `verifier_node`, ensure `PageStateTracker.capture()` is called immediately before LLM/programmatic checks.

### 3. State Change Logic
- Add `pre_action_state` to `VQAState`.
- Executor captures state BEFORE action.
- Verifier compares `post_action_state` with `pre_action_state`.

### 4. Human Correction UI
- Add "Flag False Positive" button to `StepTable` in frontend.
- Implement WebSocket message to inject correction into `VQAState`.

### 5. Dropdown Theme Fix
- Update `GlobalStyles.css` or component-specific CSS to scope dropdown colors to `[data-theme]`.
