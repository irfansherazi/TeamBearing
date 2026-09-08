# feat-058-deterministic-execution-and-loop-prevention: FEAT-058: Deterministic Execution & Loop Prevention

**Complexity**: Level 4
**Status**: BUILDING
**Jira Issue**: FEAT-058
**Issue Type**: Feature
**Priority**: High
**Branch**: feature/FEAT-058-deterministic-execution
**Worktree**: /Users/joshschauer/Documents/vProMedia/vQA/.worktrees/FEAT-058
**Roadmap**: [FEAT-058: Deterministic Execution & Loop Prevention](../roadmap.md#feat-058-deterministic-execution--loop-prevention)

---

## Task Description

Eliminate the classes of "action succeeded, verifier rejected" infinite loops that currently cause vQA sessions to burn their iteration budget without progress. This task implements three integrated strategies to harden the see-think-act loop.

1.  **Prompt De-confliction**: Resolve direct contradictions in the planner system prompt between RECIPE MANDATE and P-SELECT EXCEPTION rules.
2.  **Verification Timing**: Introduce a configurable post-action wait time to account for Angular/PrimeNG re-renders before verification.
3.  **Ambiguity Intelligence**: Add a pre-check to the AC parser to flag untestable goals and a "satisfiable" check to the verifier to break infinite loops with a clean SKIPPED status.

---

## Acceptance Criteria

### AC-1: Prompt De-confliction (Hardening)
- [x] AC-1.1: `backend/engine/planner.py` updated to nest P-SELECT EXCEPTION rules inside the RECIPE MANDATE block.
- [x] AC-1.2: The planner system prompt explicitly states that recipes are FORBIDDEN for p-select components, even if a recipe matches the target.
- [x] AC-1.3: Verify via log analysis that the planner no longer attempts recipes on `p-select#header-sort-drop-down-*` elements.

### AC-2: Verification Timing (TestStep Schema)
- [x] AC-2.1: `StructuredACStep` in `backend/engine/schemas.py` updated with `post_action_wait_ms: int = 0`.
- [x] AC-2.2: `JSON_COMPILER_PROMPT` in `backend/engine/prompts.py` updated to instruct the LLM on when to set `post_action_wait_ms` (e.g., PrimeNG sorting/dropdown re-renders).
- [x] AC-2.3: `_run_programmatic_verifications` in `backend/engine/verifier.py` implements the wait logic before executing DOM checks.
- [x] AC-2.4: Backward compatibility maintained: existing test plans without the field default to `0ms`.

### AC-3: Ambiguity Intelligence (Parser & Verifier)
- [x] AC-3.1: `backend/engine/ac_parser.py` implements an `Ambiguity Pre-Check` between Stage 1 and Stage 2.
- [x] AC-3.2: Vague goals like "The table should sort correctly" (without column/direction) are flagged and blocked with a clear diagnostic if they cannot be grounded.
- [x] AC-3.3: `verifier.py` (Tier 1) and `verifier_node.py` (Tier 2) implement `goal_satisfiable_check`.
- [x] AC-3.4: After 2 consecutive `NOT_YET` verdicts for the same AC step where the action succeeded but verification failed, the verifier emits a `SKIPPED` verdict if no progress is detected.
- [x] AC-3.5: `evaluator.py` correctly handles the `SKIPPED` verdict by advancing the AC step index and logging a warning in the audit report.

---

## Technical Strategy

### Phase 1: Schema & Prompt Hardening
- Add `post_action_wait_ms` to `StructuredACStep`.
- Refactor `RECIPE MANDATE` in `planner.py` to be deterministic regarding exceptions.
- Update `JSON_COMPILER_PROMPT` to support the new timing field.
- **Update**: Detailed plan in `.agent-logs/2026-05-29-FEAT-058-plan-detailed.md`.

### Phase 2: Verifier Timing & Loop Prevention
- Implement the sleep logic in `verifier.py`.
- Implement `goal_satisfiable_check` logic. This will likely involve tracking consecutive `NOT_YET` states in `VQAState`.
- Introduce `SKIPPED` verdict to the `VerifierVerdict` literal.

### Phase 3: AC Ambiguity Pre-Check
- Create a new utility function for ambiguity detection.
- Integrate it into the `ac_parser` pipeline.
- Define a threshold for "untestable" goals.

---

## Implementation Roadmap

- [x] Phase 0: Memory Bank Sync
- [x] Phase 1: Schema & Prompt Hardening
- [x] Phase 2: Verifier Timing & Loop Prevention
- [x] Phase 3: AC Ambiguity Pre-Check
- [x] Phase 4: Integration & Regression Testing

---

## Execution State

**Build Status**: COMPLETED
**Last Completed**: 2026-05-29
**Can Resume**: YES

### Completed Steps
- Planning initialized.
- feat-058-deterministic-execution-and-loop-prevention linked to FEAT-058.
- Detailed technical strategy and test plan drafted.
- Implementation of `post_action_wait_ms` in schemas and verifier.
- Implementation of `goal_satisfiable_check` and `skipped` verdict for loop prevention.
- Implementation of `_detect_step_ambiguity` in AC parser.
- Added Rule 16 (Anti-Loop) to planner.
- Fixed state synchronization bug (structured_step_index) identified during code review.
- Verified with 5 new test suites and 17 regression tests.
- Mandatory code review completed via `codebase_investigator`.
