---
legacy_id: FEAT-072
version: next
linked_tasks: [verification-and-bridging-to-static-code, verification-and-bridging-to-static-code]
status: complete
---

  ### FEAT-072: Verification & Bridging to Static Code
- **Version**: next
- **Status**: complete
- **Priority**: high
- **Complexity**: Level 4
- **Description**: Automatically bridge autonomous AI-explored paths into deterministic, static Playwright integration test files (`.spec.ts`) and add predictive fast-fail assertions.
    1. **AI-to-Code Test Synthesis**: When the Layer 4 Feedback Loop successfully synthesizes a winning sequence of actions, route the structured JSON macro to an LLM-compiler. The compiler translates the JSON macro directly into a structured, type-safe Playwright integration test (`.spec.ts`), registers the test in the repository, and opens a Pull Request.
    2. **Predictive State Verification**: When the `planner.py` issues an action, have it output a brief State Expectation (e.g., "Modal X should appear with text Y"). The `executor.py` compares this prediction against the post-action DOM delta. If they do not match, the executor triggers self-healing immediately, rather than waiting for standard 30-second Playwright timeouts to expire.
- **Acceptance Criteria**:
    - AC-1: Build an LLM-compiler that translates successful JSON action macros from autonomous runs into fully typed, standard Playwright integration tests (`.spec.ts`).
    - AC-2: The compiler automatically registers the synthesized `.spec.ts` test in the repository and creates a branch and PR.
    - AC-3: Ensure the planner outputs brief State Expectations with each action.
    - AC-4: Implement Predictive State Verification in `executor.py` that compares State Expectations with post-action DOM deltas and triggers immediate self-healing on mismatch, bypassing Playwright's 30s timeout.
- **Key Files**:
    - `backend/engine/planner.py`
    - `backend/engine/executor.py`
    - `backend/engine/verifier.py`
    - `backend/kb/test_synthesis_compiler.py` (New file)
- **Linked Tasks**: [verification-and-bridging-to-static-code](tasks/verification-and-bridging-to-static-code.md)
- **Branch**: feature/FEAT-072-static-test-synthesis
- **Created**: 2026-06-02
