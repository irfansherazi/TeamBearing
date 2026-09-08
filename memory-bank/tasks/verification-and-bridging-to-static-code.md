---
legacy_id: verification-and-bridging-to-static-code
---
# verification-and-bridging-to-static-code: Verification & Bridging to Static Code

**Complexity**: Level 4
**Status**: COMPLETE
**Roadmap**: [FEAT-072: Verification & Bridging to Static Code](../roadmap.md#feat-072-verification--bridging-to-static-code)
**Branch**: feature/FEAT-072-static-test-synthesis
**Worktree**: N/A
**PR Created**: YES
**PR URL**: https://github.com/vcreativeinc/vQA/pull/34

## Task Description

Implement two core architectural upgrades to bridge autonomous AI exploration with deterministic integration testing:
1. **AI-to-Code Test Synthesis**: Build an LLM-compiler (`backend/kb/test_synthesis_compiler.py`) that translates successful JSON action macros from autonomous runs (Layer 4 Feedback Loop) into fully typed, standard Playwright integration tests (`.spec.ts`), saves them in the repository's test directory (`playwright/tests/`), registers them in `playwright/playwright_registry.json`, and automates branch creation and PR opening.
2. **Predictive State Verification**: Enhance `planner.py` to output a brief `State Expectation` with each action. Upgrade `executor.py` and `verifier.py` to implement Predictive State Verification, comparing State Expectations with post-action DOM deltas to trigger immediate self-healing on mismatch, bypassing Playwright's default 30-second timeout.

---

## User Journey Definition

**Feature Type**: NFR/Infrastructure
**Creative Phase Required**: Yes - Architecture & User Journey

### Verification Method
- **Test method**: Run the custom pytest suite:
  ```bash
  .venv/bin/pytest tests/test_task_095_test_synthesis_and_prediction.py -v
  ```
- **Success metrics**:
  - LLM-compiler successfully parses a JSON macro representing a login and page navigation sequence and outputs a valid, compileable, type-safe Playwright `.spec.ts` file.
  - The synthesized test is correctly registered in `playwright/playwright_registry.json` and a new Git branch + PR is initiated automatically (mocking the GitHub CLI calls in tests).
  - Planner generates a structured action containing a `state_expectation` field.
  - Executor compares the `state_expectation` with the post-action DOM/URL delta. When a mismatch is detected (e.g. expected modal text is absent), executor fails the action immediately and triggers self-healing, skipping the full 30s timeout.
- **Observable at**:
  - `backend/kb/test_synthesis_compiler.py` output files and GitHub CLI execution logs.
  - `executor.py` and `verifier.py` debug logs showing: `Predictive verification mismatch: expected X but got Y. Short-circuiting to self-healing.`

---

## Acceptance Criteria

### AC-1: AI-to-Code LLM Compiler
**Priority**: MUST

**Given** a structured JSON macro of successful actions from a run
**When** compiled by the test synthesis compiler
**Then**:
- The compiler invokes an LLM to translate the JSON actions into standard Playwright TypeScript code (`.spec.ts`).
- The generated code is fully typed, imports standard Playwright fixtures, and follows the repository's coding standards.
- The generated test is saved under `playwright/tests/` and registered in `playwright/playwright_registry.json`.

**Verification**:
- [ ] Unit tests verify `TestSynthesisCompiler` maps JSON steps (e.g. click, fill, navigate) to valid TypeScript Playwright actions.
- [ ] Synthesized files are syntax-checked using `tsc` or standard TS parser.

### AC-2: Auto-Branch & Pull Request
**Priority**: MUST

**Given** a newly synthesized `.spec.ts` file
**When** the compiler completes registration
**Then**:
- The system checks out a new git branch (e.g. `synthesis/run-[run_id]-[timestamp]`).
- It commits the new `.spec.ts` test and updated registry.
- It opens a Pull Request linking the synthesized test back to the originating execution run.

**Verification**:
- [ ] Mocked subprocess calls check branch creation and PR opening parameters.

### AC-3: Planner State Expectations
**Priority**: MUST

**Given** a see-think-act step iteration
**When** the planner decides on the next action
**Then**:
- The planner's output JSON contains a `state_expectation` string describing the expected immediate result (e.g., "Dialog 'Create Folder' is visible", "Table contains row with name 'New Project'").
- The schema for `PlannerAction` is updated to include `state_expectation` as an optional or required field.

**Verification**:
- [ ] Schema validation checks in `schemas.py` enforce/support the new field.
- [ ] Planner prompts are updated to demand and exemplify the `state_expectation` field.

### AC-4: Predictive State Verification & Fast-Fail
**Priority**: MUST

**Given** a dispatched action with a `state_expectation`
**When** the action completes execution in Playwright
**Then**:
- The executor performs a fast DOM/URL check to see if the expectation is satisfied (e.g., matching a selector or text pattern).
- If the expectation is violated (e.g. expected element is missing), the executor immediately returns failure and triggers the self-healing recovery route.
- Bypasses standard Playwright 30s timeouts for missing elements by failing in <2s when expectations are not met.

**Verification**:
- [ ] Unit and mock tests verify that predictive mismatch triggers immediate self-healing.
- [ ] Benchmarks or logs record timeout savings on simulated failures.

---

## Test Strategy

### Approach
- **Emphasis**: Unit tests for the LLM compiler and coordinate/step translations; mock integration tests for the Git/PR orchestration and the fast-fail executor paths.
- **Target test count**: 8-10 total tests.

### File Organization
- **New test files**:
  - `tests/test_task_095_test_synthesis.py`: Verifies compiler output, registration, and Git integration.
  - `tests/test_task_095_predictive_verification.py`: Verifies state expectation generation, schema updates, and fast-fail triggers in `executor.py`.

### What NOT to Test
- We will not test live AWS Bedrock calls or live GitHub PR creation on remote repositories. These will be mocked out using standard mock interfaces.
- We will not verify real browser rendering during fast-fail test sweeps, relying instead on mocked Playwright pages and DOM accessibility structures.

---

## Implementation Roadmap

- [x] **Phase 1: AI-to-Code Compiler & PR Orchestration**
  - [x] Implement `TestSynthesisCompiler` in `backend/kb/test_synthesis_compiler.py` translating action logs to `.spec.ts`.
  - [x] Add registration wiring to update `playwright/playwright_registry.json`.
  - [x] Implement Git manager/helper functions in `backend/kb/test_synthesis_compiler.py` to checkout branch, commit, and invoke `gh pr create`.
- [x] **Phase 2: Planner State Expectations & Schema Updates**
  - [x] Update `PlannerAction` Pydantic schema in `backend/engine/schemas.py` to include `state_expectation`.
  - [x] Update planning prompts in `backend/engine/prompts.py` to request and guide state expectation writing.
- [x] **Phase 3: Predictive State Verification & Fast-Fail Execution**
  - [x] Implement expectation parsing and verification logic in `backend/engine/verifier.py` (or a helper `PredictiveVerifier`).
  - [x] Wire `executor.py` to run predictive verification immediately post-action, raising a fast-fail error and bypassing standard timeouts if expectations mismatch.

---

## Execution State

**Build Status**: COMPLETE
**Current Phase**: None
**Current Step**: None
**Step Started**: None
**Can Resume**: NO
**Worktree Cleaned**: YES
**Branch Deleted**: NO (preserved for PR)

### Active Sub-Agents
- User Journey Design: COMPLETE
- Architecture Design: COMPLETE

### Completed Steps
- [x] Initial specification and draft implementation plan created
- [x] User Journey Creative Design: COMPLETE (2026-06-02) - Output: memory-bank/creative/verification-and-bridging-to-static-code-test-synthesis-user-journey.md
- [x] Architecture Creative Design: COMPLETE (2026-06-02) - Output: memory-bank/creative/verification-and-bridging-to-static-code-test-synthesis-architecture.md
- [x] Implementation & Unit Verification: COMPLETE (2026-06-02)
- [x] Pattern Extraction & Reflection: COMPLETE (2026-06-02)
