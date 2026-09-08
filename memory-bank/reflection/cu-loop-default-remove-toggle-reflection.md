# Reflection: cu-loop-default-remove-toggle - Make Computer-Use loop the default for all runs and remove the toggle checkbox

**Date**: 2026-08-11
**Task Complexity**: Level 1
**Total Phases**: 1
**Duration**: 2026-08-11T11:01 to 2026-08-11T11:12 (approx. 11 minutes wall-clock)

## Executive Summary

This was a clean UI-removal task: unconditionally route all ticket runs through POST `/execute-cu` and delete the `useComputerUseLoop` toggle from `RunTestView.tsx`. The change surface was intentionally confined to a single file, and the out-of-scope fence (leaving `useExecution.ts`, the `/execute` backend route, and static-test replay untouched) held throughout the build.

The implementation went well. The diff was a net deletion (-159 lines of production code, +71 lines in tests), TypeScript compiled clean, and all 6 `RunTestView` tests passed. The 165/171 full-suite result was correctly characterized as pre-existing failures unrelated to this change. The guard commit log shows `PASS` with no re-invocations — a clean build.

The one interesting methodological question this task surfaces is whether the TDD RED/GREEN ceremony was the right adaptation for a code-deletion task, and whether the Level 1 fast-path was properly matched to a single-file UI removal. Both are worth examining for the ecosystem dimension.

---

## Dimension 1: Task Implementation Quality

### Requirements Achievement

**Status**: All Met

Every concrete requirement from the task description was satisfied:

- `useComputerUseLoop` state and its `localStorage` persistence effect: deleted
- Toggle checkbox JSX (`id=cu-loop-toggle`): deleted
- CU branch in the run handler unconditionally taken: confirmed (startComputerUseExecution is now the only path)
- Legacy LangGraph pipeline block (POST `/execute` call site in `RunTestView`): deleted
- `useComputerUseLoop` removed from all `useEffect` and `useCallback` dependency arrays: done
- Terminal-message effect simplified (dropped `useComputerUseLoop &&` guard): done
- `startExecution` removed from useExecution destructure in `RunTestView`: done (noted in commit — also cleaned up transitively unused variables: `ExecuteRequest` import, `pendingGuidance` state, `finalGuidance` local)

The commit message explicitly calls out that the transitively unused variable cleanup was done alongside the required deletions. This is a sound call: when deleting a code path, cleaning up its dead dependents in the same commit keeps the diff coherent and avoids follow-up noise commits.

The deliberately out-of-scope items were not touched:
- `useExecution.ts` `startExecution` export: left in place
- `backend/api/routes.py` `/execute` endpoint: untouched
- Static-test replay (`handleStaticTestSelected`): untouched
- `isStaticRunRef` gating: untouched

### Code Quality Assessment

**Overall Rating**: Good

- **Maintainability**: The removal is clean. A net -159 lines on a component that was already large is a meaningful improvement. No stubs or feature-flag remnants were left behind.
- **Architecture**: Correct choice to leave `startExecution` in the hook rather than delete it. The task description accurately predicted that other callers may exist, and this boundary was respected.
- **Error Handling**: Not applicable — no new error-handling paths were introduced; the CU path's existing error handling was preserved.
- **Testing**: The mock update (replacing `startExecution` with `startComputerUseExecution`, adding `pauseExecution`, `resumeExecution`, `ghostCredentialsMessage`, `wsSocket`) correctly reflects the actual hook interface after the change. The updated `onTicketSelected` config in the SelectView mock (with `useCustomCreds`, `customEmail`, `customPassword`) shows the test author understood that the CU path requires admin credentials in the config object — a non-obvious dependency that was properly surfaced.

One minor quality note: the commit message claims the test suite is "6/6 PASS" referring to RunTestView tests specifically. The full suite is 165/171. It would be marginally cleaner if the commit message or task state had explicitly listed which 4 pre-existing test files are failing, so a future reviewer does not need to re-establish that baseline. This is a documentation nit, not a code issue.

### Technical Decisions

**Key Decisions:**

1. **Delete the legacy pipeline call site entirely rather than dead-code it** — Rationale: leaving `if (false) { ... }` blocks is misleading and triggers linters in stricter configurations. Deleting is correct. Outcome: clean diff.

2. **Leave `startExecution` in `useExecution.ts`** — Rationale: the task correctly identified that the hook may be consumed elsewhere; a removal-only task should not cascade into other consumers. Outcome: safe; no regressions in hook consumers.

3. **Use regression guard tests instead of behavioral RED/GREEN** — Rationale: there is no new behavior to specify; the meaningful invariant is that the deleted UI elements stay deleted. Outcome: appropriate; discussed further in Dimension 2.

**Trade-offs:**

- **Scope fence vs. thorough cleanup**: Leaving `/execute` in the backend and `startExecution` in the hook means tech debt remains. The task file explicitly logs this as a planned follow-up. The trade-off — a Level 1 stays Level 1 and ships fast — is defensible.
- **Regression guard tests vs. behavioral tests**: Guards are brittle in one direction (they fail if the UI element comes back, which is the goal), but they provide no positive coverage of the CU path's behavioral correctness. This was the right trade-off for a deletion task, but it means RunTestView behavioral coverage of the CU flow is only as strong as whatever tests existed before.

### What Went Well

1. The task description was concrete and surgical: it named specific line numbers, specific variable names, and specific deletion targets. This left no ambiguity for the build agent.
2. The out-of-scope fence held perfectly — no scope creep into `useExecution.ts`, the backend, or static-test replay.
3. The transitively unused variable cleanup (`ExecuteRequest`, `pendingGuidance`, `finalGuidance`) was bundled into the same commit rather than deferred as noise. This is the right instinct for a removal task.
4. TypeScript type-checking served as an effective verification layer: a clean `tsc --noEmit` confirms no dangling references to deleted identifiers.
5. Commit-guard PASS on the first attempt — no recovery ladder needed.

### Challenges Encountered

1. **Mock interface drift** — The `useExecution` and `useWebSocket` mock objects in the test file were stale (missing `pauseExecution`, `resumeExecution`, `ghostCredentialsMessage`, `wsSocket`). The TDD agent caught and resolved this during the RED phase. This is a recurring challenge in React hook mocking: as hooks grow, co-located mocks fall behind.

2. **CU path credential dependency** — The `onTicketSelected` config in the test's SelectView mock needed `useCustomCreds: true` and credential fields to satisfy the CU code path. This was a non-obvious dependency correctly identified by the build agent.

### Technical Debt & Future Work

- **`startExecution` in `useExecution.ts`**: Now unused from the ticket-run flow. A follow-up Level 1 should verify whether any other consumer calls it; if not, delete it and the corresponding `/execute` backend route.
- **4 pre-existing test failures**: Not introduced by this change, but they exist in the full suite. Their root cause should be documented somewhere (not just implied by "pre-existing").
- **No lint script in `frontend/package.json`**: Noted by the verifier as N/A. This is an ecosystem gap (see Dimension 2).

---

## Dimension 2: Claude Code Ecosystem Effectiveness

### Build Session Analysis

**Build Sessions**: 1 (single-phase Level 1)
**Sub-Agents Spawned**: not measurable — task-scoped log directory (`.agent-logs/claude/by-task/cu-loop-default-remove-toggle/`) was missing/empty. Metrics below are inferred from task file state and commit diff.

Note: Session logs not task-indexed for this task. The by-task directory was absent. Run `/bmb:init` or check agent-log symlinking to upgrade if needed.

**Errors Recovered**: 0 (guard PASS on first attempt)

#### Tool Utilization

Inferred from the diff and task execution steps — exact counts unavailable due to missing logs.

| Tool | Estimated Count | Notes |
|------|-----------------|-------|
| Read | ~5-8 | Task file, RunTestView.tsx, test file |
| Edit | ~2-3 | RunTestView.tsx deletions, test file updates |
| Bash | ~4-6 | TypeScript build check, test run |
| Write | ~1 | Task state update |

#### Sub-Agent Performance

The Level 1 fast-path does not spawn separate named sub-agents — the TDD work is done inline by the build orchestrator. This is appropriate for a single-file, single-phase task.

### Command Workflow Evaluation

**Commands Used**: `/bmb:task` (task creation), `/bmb:build` (implementation), `/bmb:reflect` (this document)

**Workflow Efficiency**: Good for Level 1; one minor structural question

**Assessment**:

The Level 1 fast-path (`/bmb:task` → `/bmb:build` → `/bmb:reflect`) was appropriate for this change. The task was genuinely a single-file UI deletion with no new business logic, no API contract changes, and no cross-service coordination.

However, one workflow question is worth noting: the TDD ceremony (RED test → implementation → GREEN) was adapted for a deletion task by writing "regression guard" tests rather than behavioral specs. This is a reasonable adaptation, but it raises a question about whether the TDD framing is the best mental model for deletion tasks. A simpler framing — "write a test that will fail if this UI element ever comes back, then delete the element" — is equivalent, but the RED/GREEN language implies a feature-addition context that can create slight friction when the task is subtractive. This is a low-priority workflow design question, not a failure.

**Level 1 vs. Level 2 call**: Level 1 was correct. The task description correctly scoped the change to a single file with no new behavior. The decision to leave `startExecution` in the hook and the backend route untouched was the right call to keep this Level 1.

### Context File Effectiveness

**Files relevant to this task**: `memory-bank/tasks/cu-loop-default-remove-toggle.md` (only file needed)

**Assessment**:

- **Helpful**: The task file's "Implementation Notes" section was unusually precise — it cited line number ranges, named specific variables, and explicitly listed what was out of scope. This level of specificity eliminated ambiguity and likely contributed to the clean single-commit build.
- **Gaps**: None material for this task. The Level 1 context is intentionally lean.
- **Redundancy**: None.

### Memory Bank Organization

**Assessment**:

- **Structure**: Appropriate. The task file carried all necessary context without needing roadmap features or creative docs.
- **Navigation**: N/A for Level 1 — single task file is the only artifact.
- **Completeness**: Adequate. The follow-up task note ("file a follow-up Level 1 to sweep unused `startExecution` / `/execute`") is correctly recorded in the task file rather than a separate roadmap entry.

### Memory-Bank Corrections (from Guardrail Misses)

None — no guardrail misses this build. The commit-guard PASS log confirms: `prod=1 (RunTestView.tsx), test=1 (RunTestView.test.tsx)`.

### Suggested Improvements to Claude Code System

**High Priority**:

1. **Lint gap in build verifier** — The build verifier reported "lint: N/A" because `frontend/package.json` has no `lint` script. The verifier should detect the absence of a lint script and flag it as a project configuration gap (distinct from a lint failure), not silently skip. A `WARN: no lint script found in frontend/package.json — consider adding eslint` message would prompt the team to wire it up rather than leaving the gap invisible.

2. **Task-scoped agent log symlinking** — The by-task log directory for this task was absent, making metrics derivation impossible. If the `/bmb:build` command creates log symlinks under `.agent-logs/claude/by-task/<slug>/` only when sub-agents are spawned (not for inline Level 1 builds), that gap should be documented or the symlinking should also cover the orchestrator's own session log.

**Medium Priority**:

3. **Deletion task TDD framing** — For tasks whose primary deliverable is removal of code (toggle deletion, flag deprecation, dead-code sweep), the TDD ceremony guidance could explicitly offer a "regression guard" pattern as the idiomatic RED step, rather than implying a feature-specification framing. A one-paragraph note in the build agent context file would suffice.

4. **Pre-existing failure baseline** — The build verifier accepts a 165/171 result without surfacing which 6 tests are in the failure set. A persistent "known-failing tests" list (even just a comment in the task file or a project-level config) would let future builds confirm that the same 4/6 failures are pre-existing rather than requiring manual re-disambiguation each time.

**Low Priority / Nice to Have**:

5. **Commit message full-suite breakdown** — Encourage (or template-enforce) that commit messages include the full pass/fail counts when referencing pre-existing failures, e.g., "Full suite: 165/171 PASS (4 pre-existing failures in X, Y, Z; unrelated to this change)" rather than just the RunTestView count.

---

## Key Learnings

### Extractable Learnings (for Continuous Learning)

- **testing-patterns** (`*.test.tsx`, `*.test.ts`): For UI-deletion tasks, write regression guard tests that assert the deleted element's selector (id, data-testid, or label text) is ABSENT — these serve as living documentation of the invariant and catch re-introduction regressions in code review.

- **scope-discipline** (`frontend/src/components/`): When a UI removal has transitively unused variables (imports, state, locals), bundle their deletion into the same commit as the primary removal — this keeps the diff coherent and avoids a "clean up unused vars" follow-up commit that obscures the original intent.

Level 1 limit: 1-2 learnings max — stopping here.

### Learned Rules Applied

Reviewing the `_learned/` directory for rules relevant to this task:

- **testing-patterns.md**: The existing rules cover Python test patterns, state machine factories, and cross-component integration tests. None directly address React component deletion tests. Loaded but not applicable to this specific case — the new regression-guard learning above is a novel addition to this file.
- **frontend-patterns.md**: Likely relevant but the content was not loaded for this reflection (lean context). If it covers React hook mock maintenance, the "mock interface drift" challenge would be covered.

No other learned rules were directly applicable to a single-file UI deletion.

### For Claude Code Workflow

1. **Regression guard pattern for deletion tasks** — When the task deliverable is removal of a UI element, "write a test asserting the element is absent" is the correct RED step. This should be codified in the build agent's TDD guidance as a named pattern.

2. **Lint script absence is a team signal, not a silent skip** — A missing lint script in `package.json` means the project has no automated style enforcement. This deserves a visible warning from the verifier, not a transparent N/A.

3. **Pre-existing failure baseline disambiguation** — Any full-suite run that isn't 100% should record which tests are failing and why they are considered pre-existing, not just the count. A one-line annotation in the task execution state is sufficient.

---

## Conclusion

This was a textbook Level 1 deletion task: surgical, well-scoped, and executed cleanly in a single commit. The implementation matched the task description precisely, the TypeScript compiler served as an effective completeness check, and the guard PASS confirms no recovery was needed. The regression guard test pattern — adapting RED/GREEN for a deletion rather than an addition — was the right call and produced two durable invariant tests that will catch re-introduction.

The main ecosystem signal from this task is not a failure but a gap: the verifier's silent "lint: N/A" for a missing lint script, and the absent task-scoped agent log directory, both reduce the diagnostic value of the post-build verification step for Level 1 tasks.

**Overall Task Success**: Success

**Overall Workflow Effectiveness**: Moderately Effective (Level 1 fast-path worked well; two instrumentation gaps noted)

**Recommendation**: Ready to archive
