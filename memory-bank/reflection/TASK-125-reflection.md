# Reflection: Ghost Login — Admin Credential Prompt & Ghost Panel Interaction

**Task**: TASK-125
**Feature**: FEAT-116
**Date**: 2026-07-22
**Complexity**: Level 2 (Simple Enhancement)
**Total Phases**: 2
**Branch**: feature/FEAT-116-ghost-login-credential-prompt

---

## Summary

TASK-125 fixed two root causes that together prevented the ghost-login HITL credential prompt from reliably surfacing to the operator during test runs. Phase 1 broadened the AC parser's ghost keyword detection in `backend/engine/prompts.py` from the narrow "Ghost In As [user]" phrasing to any case-insensitive mention of the word "ghost." Phase 2 confirmed (and tested) that `GhostCredentialPanel.tsx` on this branch already presented the manual credential form immediately on mount — the SSO auto-submit fast-path described in the task brief existed only on a different branch, not on FEAT-115/FEAT-116. Both phases completed clean: no guard failures, no re-invocations, 8/8 target tests GREEN.

---

## What Went Well

- **Phase 1 prompt change was surgical and accurate.** Extending `BDD_NORMALIZER_PROMPT` Rule 8 with an explicit broadened detection sentence ("treat ANY mention of the word 'ghost' (case-insensitive) as a ghost-login trigger") and adding a corresponding `ghost_panel` target_component instruction to `JSON_COMPILER_PROMPT` covered all AC-ENTRY acceptance criteria in a single, traceable edit. The pre-existing test `test_ac_parser_emits_ghost_login_step` also went from FAIL to PASS as a bonus — the prompt change fixed a real regression that had gone undetected.

- **TDD as specification worked cleanly for prompt-level tests.** Writing 5 prompt-level unit tests (static string assertions against the imported prompt text) provided fast, cost-free, CI-safe verification without any LLM calls or browser sessions. This approach is directly reusable for any future prompt modification.

- **Guard passed first try on both phases.** No recovery ladder invocations. The commit guard (prod=1 test=1 per phase) PASSed on the initial attempt both times, indicating the implementation scope was correctly scoped and the test plan was complete before implementation began.

- **Integration suite improvement, not regression.** The backend test count went from 55 pre-existing failures to 53 after Phase 1 — two tests that were already failing on `main` were fixed as a side-effect of the prompt broadening. Net result: 1488 GREEN.

- **Frontend suite was additive and clean.** Phase 2 added 3 tests to `GhostCredentialPanel.test.tsx` and the full suite went from 103 to 106 passing. The 4 pre-existing failures (AppShell, SelectView, ExecutionLog) are unrelated and pre-dated this branch.

---

## Challenges

- **Phase 2 false-alarm: SSO fast-path was not present on this branch.** The task brief identified a `useEffect` SSO auto-submit fast-path in `GhostCredentialPanel.tsx` that needed to be removed. On investigation, the component on FEAT-115/FEAT-116 never had this code — it existed only on a different branch. This meant Phase 2's code-change objective became a no-op and the phase instead verified the "correct-by-construction" state through tests. The agent handled this gracefully, writing tests that would catch any future regression of the SSO path being re-introduced, and the phase still delivered 3/3 GREEN tests with a clean guard PASS. However, the planned unit-of-work did not match reality.

  **Root cause**: The task description was written referencing the FEAT-115 branch behavior, but FEAT-116 branched from a state where the SSO fast-path had never been merged in. Cross-branch feature dependency descriptions in task briefs can misrepresent what code is actually present in the target worktree.

---

## Lessons Learned

Reviewing the existing `prompt-engineering.md` learned rules: the "Prompt Audit Checklist Standard," "Hierarchical Anchoring," and "Pre-Pipeline Detection Over LLM Call" rules were all relevant. The ghost detection change is in the "rules over pipeline" category — it extends an existing LLM instruction rather than adding a new pipeline stage, consistent with the Pre-Pipeline Detection pattern. The existing rule is applicable and was implicitly followed. No new rules are needed in that file.

---

## Action Items

- **Cross-branch feature descriptions need a "current-branch status" note.** When a task brief says "remove the SSO fast-path from GhostCredentialPanel," it should explicitly state which branch that code exists on and whether it has been merged to the target feature branch yet. A simple "Present on branch X, NOT yet on feature/FEAT-116" annotation in the task's Scope Boundaries section would prevent agents from spending Phase 2 searching for code that does not exist in their worktree.

- **GhostCredentialPanel.test.tsx coverage is now in place.** If/when the FEAT-115 SSO fast-path ever merges, the Phase 2 tests will immediately catch any auto-submit on mount, making the guard reliable without a human needing to remember the regression risk.

---

## Claude Code Ecosystem Observations

### What Worked Well

- **`/bmb:build` orchestrator sub-agent (Sonnet)**: Handled both phases efficiently with a single dispatch per phase. The structured return contract (`PHASE_COMPLETE` → `BUILD_COMPLETE`) gave the calling command a clear signal without requiring re-verification by the outer loop. Phase 1 duration was ~19 minutes (1171 seconds for 100 tool calls), which is appropriate for a backend Python prompt edit with full integration suite verification.

- **Task file as source-of-truth**: The `TASK-125.md` execution state section was updated after each step, making the phase-by-phase completion auditable after the fact. The `Guard & Recovery Log` being empty is a clear, visible signal that no recovery was needed.

- **Prompt-level testing pattern**: Writing unit tests that do `from backend.engine.prompts import BDD_NORMALIZER_PROMPT` and assert on string content (presence of rule text, sectional anchoring) is a powerful, fast, CI-safe way to lock down prompt behavior. This pattern complements the existing `prompt_audit_checklist.md` approach without replacing it.

- **2-phase structure was right for this task.** Separating backend (Python/prompts) from frontend (React/TSX) into distinct phases gave the agent a clean context boundary and made each phase's test surface obvious. A single monolithic phase would have mixed Python and TypeScript test tooling in one context window.

### Friction Points

- **Only one session log was produced for a two-phase build.** The agent log at `.agent-logs/claude/by-task/TASK-125/` contains only the Phase 1 session (`1120__661ce566-ca50-4398-bcc2-f9ff6458eec9.md`). Phase 2's session was not captured there — either it ran in the same session (the log only covers up to Phase 1 complete) or the by-task symlink was not created for Phase 2. This made build session analysis for Phase 2 rely on the task file's Execution State rather than a direct log audit.

- **Phase 2 work description did not match the branch state.** The task brief described removing code that was never present on FEAT-116. An agent that had not read the actual component file would have searched fruitlessly. The orchestrator resolved this correctly by inspecting the component first, but the mismatch added investigation overhead.

### Suggestions for Improvement

> Note: These are suggestions only. Do NOT implement these changes.

- **Task brief cross-branch validation at plan time**: When a task description references code on a named branch (e.g., "on the FEAT-115 branch, GhostCredentialPanel added a useEffect..."), `/bmb:plan` could add a validation step that checks whether that code is present in the current worktree and annotates the plan with "PRESENT / NOT-PRESENT on target branch." This would let the build orchestrator know upfront whether Phase 2 is a removal task or a verification task.

- **Phase 2 session logs missing**: The by-task log symlink creation appears to have only fired once (Phase 1). If each `/bmb:build` invocation should produce a separate session log linked in `by-task/<slug>/`, confirm the hook runs per invocation and not once per task lifecycle.

---

## Guardrail Misses & Root-Cause Analysis

None — no guardrail misses this build. Guard PASSed first try on both phases.

## Memory-Bank Corrections (from Guardrail Misses)

None — no guardrail misses this build.

---

## Extractable Learnings

- **testing-patterns** (`tests/test_*.py`, `backend/engine/prompts.py`): For LLM system prompt modifications, write prompt-level unit tests that import the prompt string and assert on section-anchored substring presence — this catches prompt regressions at O(1) cost with zero LLM calls and runs safely in CI.

- **cross-branch-dependencies** (`memory-bank/tasks/*.md`): When a task description references code that "exists on branch X," verify its presence in the target worktree at the start of the relevant phase before spending time on removal or modification; if absent, pivot to writing regression tests that would catch reintroduction.

---

## Learned Rules Applied

- **prompt-engineering.md — Pre-Pipeline Detection Over LLM Call**: The ghost detection fix followed this pattern — extending an LLM instruction in the existing prompt rather than adding a new pipeline stage. Applicable and implicitly followed.
- **prompt-engineering.md — Hierarchical Anchoring**: The ghost detection rule was placed in `<RULES>` section (mid-prompt) and the existing `CRITICAL_REMINDER` anchor already covers emission correctness. Applicable; no changes needed.
- **frontend-patterns.md**: Rules loaded but not applicable to Phase 1 (Python only). Phase 2 relied on existing component structure (no new patterns introduced).

---

## Conclusion

TASK-125 successfully delivered both acceptance criteria entry points (AC-ENTRY-1 and AC-ENTRY-2 for ghost keyword detection) and confirmed the HITL credential form path (AC-HAPPY-1 and AC-HAPPY-2 confirmed by tests). The implementation was lean: one prompt rule addition, one new test file, one test addition to the frontend suite. The most notable observation is the cross-branch dependency mismatch in the task brief — Phase 2 targeted code that did not exist on the feature branch. The agent handled this gracefully but the planning artifact should have been more precise. All 8 target tests GREEN, 0 guard failures, ready to archive.

**Overall Task Success**: Success

**Overall Workflow Effectiveness**: Highly Effective

**Recommendation**: Ready to archive
