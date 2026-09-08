# Reflection: hitl-threshold-tuning - HITL Threshold Tuning

**Date**: 2026-05-12
**Task Complexity**: Level 2
**Total Phases**: 3

## Executive Summary
hitl-threshold-tuning successfully refined the Human-In-The-Loop (HITL) escalation logic in the vQA engine. The previous static threshold was replaced with a failure-type aware system that escalates early for unrecoverable errors while providing more headroom for transient or ambiguous UI states.

The implementation involved updating the central configuration and surgically modifying the evaluator node's routing logic. All 5 new unit tests passed, confirming that the system now correctly discriminates between error categories (INTERCEPTED, STRICT_MODE, and General) when deciding whether to trigger a human takeover. This change significantly improves the "patience" of the agent in complex scenarios while maintaining responsiveness to hard blocks.

---

## Dimension 1: Task Implementation Quality

### Requirements Achievement
**Status**: ✅ All Met

- **AC-HAPPY-1**: Default HITL threshold is correctly set to 4 in `config.py` and applied in `evaluator.py`.
- **AC-HAPPY-2**: `INTERCEPTED` failures now trigger HITL after 2 failures, preventing wasted retries on blocked UI elements.
- **AC-HAPPY-3**: `STRICT_MODE` failures trigger HITL after 3 failures, allowing for a few disambiguation attempts before asking for help.
- **AC-HAPPY-4**: All thresholds are fully configurable via the Pydantic `Settings` class in `config.py`.
- **AC-REGRESS-1/2**: `retry_count` and `action_fail_count` tracking remain intact, ensuring existing circuit breakers and vision escalation still work as intended.

### Code Quality Assessment
**Overall Rating**: Excellent

- **Maintainability**: The use of `Settings` for thresholds makes the system easy to tune without code changes.
- **Architecture**: The logic leverages the existing `_classify_error` helper in `evaluator.py`, avoiding redundant parsing of error messages.
- **Error Handling**: The implementation is robust, falling back to the `general` threshold if an error doesn't match specific intercepted/strict patterns.
- **Testing**: Test coverage is excellent for the new logic, with unit tests specifically targeting the boundary conditions of each threshold using mocked settings.

### Technical Decisions
**Key Decisions:**
1. **Reuse of `_classify_error`** - Instead of using the more complex `failure_classifier.py`, the implementation uses the lighter `_classify_error` helper already inside `evaluator.py`. This reduces cross-module dependency for a core routing decision and keeps the logic close to where it's used.
2. **`action_fail_count` Target** - The implementation correctly targets `action_fail_count` (Playwright-level failures) rather than `retry_count` (which includes verifier rejections). This ensures that escalation is based on the agent's inability to interact with the page, not the app's inability to reach a target state.

**Trade-offs:**
- **Simplicity vs Granularity**: The implementation uses 3 primary threshold categories rather than a 1:1 mapping for every possible error category. This provides the most value (fast-fail for blocks) with minimal configuration overhead.

### What Went Well
1. **Surgical Implementation**: The changes to `evaluator.py` were localized and did not disturb the complex state-management logic around it.
2. **Config Centralization**: Adding the thresholds to `config.py` follows the project's established patterns for environment-driven behavior.

### Challenges Encountered
1. **Vision Escalation Interaction**: Testing higher thresholds required bypassing the default "vision escalation" at 2 failures. This was correctly identified and handled in the test suite by forcing `vision_mode="som_coordinates"`.

### Technical Debt & Future Work
- **`failure_classifier.py` Redundancy**: The `RETRY_BUDGETS` and `get_retry_budget` in `failure_classifier.py` are now redundant and unused. These should be removed in a future cleanup task to avoid confusion.
- **Dynamic Tuning**: Future iterations could allow these thresholds to be adjusted dynamically based on the complexity of the current AC step.

---

## Dimension 2: Antigravity Ecosystem Effectiveness

### Build Session Analysis
**Build Sessions**: 1 total
**Sub-Agents Spawned**: 0 agents

#### Sub-Agent Performance
*No sub-agents were used for this Level 2 task, which was handled efficiently by the primary agent.*

### Command Workflow Evaluation
**Commands Used**: `/vc-task`, `/vc-plan`, `/vc-build`
**Workflow Efficiency**: Excellent

**Assessment**:
- The workflow was smooth for a Level 2 task. The inline TDD approach (write tests → implement → verify) worked perfectly here.
- The `INITIALIZED` status in `tasks.md` vs `COMPLETE` in `hitl-threshold-tuning.md` indicates a minor manual sync gap in the workflow's final steps.

### Context File Effectiveness
**Files Loaded**: `backend/config.py`, `backend/engine/evaluator.py`, `backend/engine/failure_classifier.py`

**Assessment**:
- **Helpful**: `evaluator.py` comments were excellent for understanding the branching logic.
- **Gaps**: None identified for this task scope.

### Suggested Improvements to Antigravity System
**High Priority**:
1. **Task Registry Auto-Sync** - A tool or hook to ensure `tasks.md` status matches the individual task file status would prevent the minor "INITIALIZED" vs "COMPLETE" discrepancy.

---

## Key Learnings

### Extractable Learnings (for Continuous Learning)

- **configuration** (`backend/config.py`): Use Pydantic `Field` with `ge` and `le` validators for numeric thresholds to enforce valid system constraints at startup.
- **error-handling** (`backend/engine/evaluator.py`): Decouple Playwright-level failure budgets from semantic verifier budgets to allow for different "patience" levels across different failure modes.

### Learned Rules Applied
- `memory-bank/agent-rules/_learned/evaluator-routing.md`: Loaded and applied during logic integration.

---

## Conclusion
hitl-threshold-tuning is a high-quality improvement that makes the vQA agent more resilient and less likely to trigger premature human intervention. The implementation is clean, well-tested, and adheres to project standards.

**Overall Task Success**: ✅ Success
**Overall Workflow Effectiveness**: ✅ Highly Effective
**Recommendation**: Ready to archive.
