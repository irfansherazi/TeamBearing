# Reflection: feat-058-deterministic-execution-and-loop-prevention: FEAT-058: Deterministic Execution & Loop Prevention

## Summary
Successfully hardened the execution loop against the three most common causes of infinite "action-success/verification-fail" loops: framework re-render race conditions, vague/untestable Jira AC, and contradicting planner instructions.

## What Went Well
- **Deterministic Settle Time**: The introduction of `post_action_wait_ms` in the `StructuredACStep` schema provides a precise lever for handling Angular/PrimeNG animations and re-renders that previously required fragile `sleep` hacks or caused false negatives.
- **Clean Loop Termination**: The `goal_satisfiable_check` correctly identifies when the agent is "spinning its wheels" (action succeeds but state never satisfies the verifier). Moving to `SKIPPED` status after 3 attempts preserves the iteration budget and provides a clear audit trail.
- **Parser-Level Guarding**: The `_detect_step_ambiguity` check in `ac_parser.py` serves as a high-value quality gate, catching Jira tickets that are too vague to be grounded in the UI (e.g., "The table should sort correctly" without specifying the column) before any execution costs are incurred.

## Challenges & Learnings
- **Index Synchronization**: Discovered a critical desynchronization bug where `structured_step_index` (the position in the JSON plan) and `ac_step_index` (the position in the raw Jira list) drifted apart during re-runs. Fixed by making the `evaluator` the absolute source of truth for index advancement.
- **Prompt Conflict Resolution**: Learned that global "recipe mandates" in the planner can sometimes override specific "component exceptions" if not nested correctly. Refactored the prompt to use a hierarchical structure for rules.
- **Skipped vs Failed**: Defined `SKIPPED` as a first-class citizen in the `VerifierVerdict`. This distinction is vital for reporting — a "skipped" step indicates an intelligence/grounding gap, whereas a "failed" step indicates a potential product bug.

## Patterns & Rules to Update
- **systemPatterns.md**: Added "Deterministic Timing (post_action_wait_ms)" pattern.
- **systemPatterns.md**: Added "Anti-Loop Circuit Breaker (goal_satisfiable_check)" pattern.
- **systemPatterns.md**: Added "Ambiguity Pre-Check Quality Gate" pattern.
- **verification-patterns.md**: Added "Goal Satisfiability Check" for loop prevention.
- **verification-patterns.md**: Added "Framework Settle Time" for async UI.

## Next Steps
- Begin **FEAT-059: Prompt Engineering Hardening** to further reduce reasoning hallucinations.
- Monitor `SKIPPED` verdicts in the audit log to identify common ambiguity patterns for future AC generator training.
