# Reflection: prompt-engineering-hardening-feat-059 — Prompt Engineering Hardening (FEAT-059)

**Date**: 2026-05-29
**Complexity**: Level 3
**Branch**: feature/FEAT-059-prompt-hardening
**Commit**: d48fffa
**Build Duration**: ~12 minutes (20:23 → 20:35 UTC)

---

## Summary

prompt-engineering-hardening-feat-059 delivered the first full implementation sprint of FEAT-059 (Prompt Engineering Hardening), translating the audit standards established in initialize-feat-059-prompt-engineering-hardening into concrete structural improvements across all five target system prompts. The task resolved the most dangerous architectural defect in the vQA engine — a direct contradiction between two "HIGHEST PRIORITY" rules in the planner — while simultaneously expanding the few-shot coverage for the top PrimeNG failure modes and applying XML structural delimiters to the supervisor prompt. All 20 structural unit tests pass; the full suite regressed by zero tests relative to the pre-existing 24 failures.

---

## Part 1: Task Implementation Quality

### What Went Well

**1. Contradiction Resolution Was Clean and Safe**
The RECIPE MANDATE ↔ P-SELECT EXCEPTION contradiction was resolved by nesting the exception inside the mandate block — exactly as designed in the "Option A" architecture section. The change was purely structural: identical rule text, new nesting position, single `═══` border. The planner's behavior for p-select and recipe steps is unchanged; the LLM now sees unambiguous priority ordering. Zero regressions.

**2. Test-First Discipline Validated the Architecture**
Writing 20 structural tests in Phase 1 before touching any prompt was the correct strategy. Tests encoded the "done" criteria for the entire task, making Phase 2-4 a straightforward exercise in getting green. The fraction-based checks (`prompt[:len(prompt)//5]`) proved stable — they do not break when minor additions are made to the beginning of prompts, unlike line-number-based assertions.

**3. Fragment Reuse Made the Supervisor Fix Trivial**
Because `prompt_fragments.py` already exported `GOLDEN_RULES`, the supervisor hardening in Phase 3 was a matter of adding one import and restructuring the prompt. The architecture's "Fragment Reuse" principle — established as a guiding principle in the task spec — paid off immediately. This is the pattern that should scale to any new system prompt added to the engine.

**4. Few-Shot Expansion Addressed Root Cause of PrimeNG Loops**
The three PrimeNG few-shot examples (sorting re-render race, p-select anti-loop guard, compound-column atomic sort) directly address the failure patterns that caused the most escalations in recent production runs. Unlike code changes, these examples teach the model *by demonstration* rather than *by rule*, which is a more reliable instruction medium for nuanced procedural knowledge.

**5. Structural Changes Were Purely Non-Behavioral**
Strict adherence to the "Structural Changes Only" architectural principle meant that testing could be limited to static string analysis — no LLM calls, no browser sessions. This made Phase 1 verification cheap (milliseconds) and deterministic.

### Challenges & Learnings

**1. Pre-existing Test Failures Required Careful Baselining**
The full suite reported 871 PASS / 24 FAIL. The 24 failures are pre-existing (feat-058-deterministic-execution-and-loop-prevention and prior work confirmed this baseline). Without baselining this number before Phase 2 began, it would be easy to introduce a regression and miss it because the total failure count didn't change dramatically. **Key discipline**: always `pytest tests/ -v` before Phase 1 and record the exact failure count in the task file.

**2. Token Budget Check Was Performed Manually**
`scripts/test_prompt_limits.py` existed but had to be invoked manually; the structural test for budget (`test_prompt_budget_not_exceeded`) was part of the Phase 1 suite. The few-shot expansion in Phase 2 increased the planner prompt size, but remained within the 8000-token ceiling because SLOT 26 has a `max_chars` guard. The guard prevented overage without requiring manual counting.

**3. `prompt_audit_checklist.md` Remains Documentation-Only**
AC-EDGE-3 (the implied goal) — linking the checklist to a CI enforcement gate — was explicitly noted as a known gap in the task spec. The test file `test_prompt_structure.py` *is* the enforcement gate for the five specific prompts, but general prompt additions by future developers won't automatically be required to pass the checklist. This is a gap for a follow-on task.

### Acceptance Criteria Verification

| AC | Description | Status |
|----|-------------|--------|
| AC-ENTRY-1 | Planner RECIPE MANDATE contradiction resolved | ✅ PASS — "HIGHEST PRIORITY" appears ≤ 1× in `_CORE_RULES` |
| AC-ENTRY-2 | All five prompts pass structural checklist | ✅ PASS — `test_all_prompts_have_golden_rules_at_start` + `test_all_prompts_have_critical_reminder_at_end` |
| AC-HAPPY-1 | Few-shot covers PrimeNG failure modes | ✅ PASS — `primeng_dropdown`, `po-sorting-dropdown-panel`, `p-select-overlay` all present |
| AC-HAPPY-2 | Supervisor uses `GOLDEN_RULES` from `prompt_fragments` | ✅ PASS — `test_supervisor_imports_golden_rules` |
| AC-EDGE-1 | Zero regressions on full test suite | ✅ PASS — 871/895 (identical to pre-task baseline) |
| AC-EDGE-2 | Token budget not exceeded | ✅ PASS — SLOT 26 `max_chars` guard engaged; within 8000-token ceiling |

---

## Part 2: Antigravity CLI Ecosystem Evaluation

### What the Ecosystem Did Well

**Phase-Gated TDD Was Ideal for This Task**
The RED (Phase 1 tests) → GREEN (Phase 2-3 implementation) → VALIDATE (Phase 4) structure mapped perfectly to a prompt hardening task where "done" is objectively defined. The workflow's insistence on writing failing tests before touching implementation forced clarity about what the structural invariants actually *were* — which in turn exposed the RECIPE MANDATE / P-SELECT EXCEPTION contradiction as a testable property rather than a subjective judgment.

**`prompt_fragments.py` as a Reuse Artifact**
The ecosystem pattern of discovering existing fragments before writing new code (the "validate-dont-duplicate" learned rule) was applied correctly here. The orchestrator checked `prompt_fragments.py` during PLAN and confirmed `GOLDEN_RULES` already existed — which collapsed Phase 3 from a potential "write GOLDEN_RULES in supervisor.py" task into a simple import + restructure.

**Complexity Level 3 Was Correctly Assigned**
The task involved design decisions (nested exception vs. separate rules), cross-file structural changes (5 prompt files + test file + docs), and a creative consideration (few-shot example content). Level 3 with a simplified creative phase (no dedicated `/vc-creative` spawn) was the right calibration.

### Ecosystem Improvement Suggestions

**1. Baseline Test Count Should Be a Formal Step**
The build workflow has no explicit "record pre-task test baseline" step. This should be Step 0.5 of Phase 1 (RED): run `pytest tests/ -v` before writing any tests, capture total pass/fail count, and persist it in the task file. Without this, regression detection relies on the implementer remembering the count from their last run — which is fragile.

**2. `prompt_audit_checklist.md` → CI Gate Migration Needs a Task Template**
When a task establishes a documentation standard (like initialize-feat-059-prompt-engineering-hardening), the workflow should automatically create a follow-on task stub for "Enforce [Standard] in CI" if the standard doesn't yet have programmatic enforcement. Currently this follow-on is implicit and often missed. A `/vc-task` stub created during `/vc-reflect` would ensure it isn't forgotten.

**3. Few-Shot Examples Are Under-Resourced as a Workflow Concern**
The workflow's test strategy (RED/GREEN/REFACTOR) applies naturally to code. It applies less naturally to few-shot examples, which require *qualitative judgment* about what failure modes to cover. The workflow has no dedicated "few-shot review" step — example quality is assessed only implicitly (by whether the tests pass). A lightweight "few-shot review checklist" in the ecosystem would improve example quality for future prompt tasks.

---

## Part 3: Key Learnings

### Learning 1: Structural Test Assertions Should Use Fraction-Based Position Checks

**Pattern**: When asserting that a prompt section appears at the "start" or "end," use `prompt[:len(prompt) // N]` fraction-based slicing rather than line-number or character-offset checks. Fraction-based checks are robust to minor additions at the boundary zones.

**Applicable Rule File**: `testing-patterns.md` (new bullet)

### Learning 2: Contradiction-as-Test — Priority Conflicts Are Detectable via Static Analysis

**Pattern**: Priority conflicts between prompt rules (e.g., two "HIGHEST PRIORITY" blocks) are detectable by counting the frequency of specific strings in prompt constants. This can be automated via unit tests. Every prompt that uses priority markers should have a corresponding `assert prompt.count("HIGHEST PRIORITY") <= 1` test.

**Applicable Rule File**: `prompt-engineering.md` (new bullet)

### Learning 3: Pre-Task Test Baseline Is a Required Build Step

**Pattern**: Before writing any Phase 1 tests, record `pytest tests/ -v` pass/fail counts in the task's Implementation History. Without this baseline, detecting regressions requires remembering a number — which is unreliable. The baseline becomes the denominator for all subsequent phase regression checks.

**Applicable Rule File**: `testing-patterns.md` (new bullet)

### Learning 4: XML Delimiter Standardization Enables Zero-Cost Supervisor Hardening

**Pattern**: Once `prompt_fragments.py` exports structural constants (`GOLDEN_RULES`, `CRITICAL_REMINDER`), adding them to any new prompt is a one-import, one-restructure operation costing minutes, not hours. The fragment library compounds in value as the number of prompts grows. Every new system prompt added to the engine should import from `prompt_fragments` rather than inline its own anchoring text.

**Applicable Rule File**: `prompt-engineering.md` (new bullet)

---

## Part 4: Patterns & Rules to Update

### `prompt-engineering.md` — Add 2 bullets

1. **Contradiction Detection via Static Analysis**: Priority conflicts in system prompts (e.g., two "HIGHEST PRIORITY" rules) are a testable structural property. Add `assert prompt.count("HIGHEST PRIORITY") <= 1` as a unit test for any prompt that uses priority markers. Run this in `tests/test_prompt_structure.py` rather than relying on qualitative review.

2. **Fragment Library Compound Value**: Every new system prompt MUST import `GOLDEN_RULES` and `CRITICAL_REMINDER` from `backend/engine/prompt_fragments.py` rather than inlining its own anchoring text. The cost of structural hardening is O(1) once the fragment library exists; duplicating anchoring text inline makes future updates require touching every prompt file.

### `testing-patterns.md` — Add 2 bullets

1. **Fraction-Based Prompt Assertions**: When writing structural tests for LLM system prompts (e.g., "GOLDEN_RULES appears near the start"), use `prompt[:len(prompt) // 5]` fraction-based slicing rather than character offsets or line numbers. Fraction-based checks are robust to minor additions within the boundary zone.

2. **Pre-Task Test Baseline**: Before writing Phase 1 RED tests, always run `pytest tests/ -v` and record the exact pass/fail counts in the task's Implementation History table. This baseline is the denominator for all regression checks and eliminates the need to rely on memory.

---

## Next Steps

1. ✅ **Pattern extraction complete** — `prompt-engineering.md` and `testing-patterns.md` updated
2. **`/vc-archive prompt-engineering-hardening-feat-059`** — Merge feature branch to main and create PR
3. **Follow-on**: Create a task to enforce `prompt_audit_checklist.md` via CI (currently documentation-only)
4. **Follow-on**: Apply few-shot example review checklist pattern to feat-058-deterministic-execution-and-loop-prevention's verifier timing scenarios
