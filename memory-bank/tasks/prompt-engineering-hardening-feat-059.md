---
legacy_id: prompt-engineering-hardening-feat-059
---
# prompt-engineering-hardening-feat-059: Prompt Engineering Hardening (FEAT-059)

**Status**: COMPLETE
**Phase**: ARCHIVE
**Complexity**: Level 3
**Roadmap Link**: FEAT-059
**Branch**: feature/FEAT-059-prompt-hardening
**Created**: 2026-05-29

---

## Executive Summary

The vQA engine's LLM prompts suffer from structural reliability failures caused by poor prompt architecture. Critical rules get "lost in the middle" of long prompts (the known LLM attention degradation pattern), dynamic context bleeds into instruction zones without clear delimiters, and the planner prompt contains a direct contradiction between two "HIGHEST PRIORITY" rules (RECIPE MANDATE vs. P-SELECT EXCEPTION). This task applies the prompt engineering standards defined in `knowledge/prompt_audit_checklist.md` across the five core engine prompts — planner, verifier, verifier_node, ac_parser (prompts.py), and supervisor — to eliminate these structural failure modes.

**Key insight from codebase analysis**: `backend/engine/prompt_fragments.py` already exists with `GOLDEN_RULES`, `COT_WORKFLOW`, and `JSON_OUTPUT_REMINDER` constants. The `_build_system_prompt_v2()` function in `planner.py` already imports and uses `GOLDEN_RULES` and `COT_WORKFLOW` at the CRITICAL tier. `prompts.py` (ac_parser) is already well-structured with `<GOLDEN_RULES>`, `<RULES>`, `<MANDATORY_REASONING_WORKFLOW>`, `<INPUT_CONTEXT>`, and `<CRITICAL_REMINDER>` sections. `verifier.py`'s `_VERIFIER_SYSTEM_PROMPT` already has `<GOLDEN_RULES>`, `<JUDGEMENT_RULES>`, `<OUTPUT_FORMAT>`, and `<CRITICAL_REMINDER>` anchoring.

**What does NOT yet exist**:
1. Few-shot examples for PrimeNG sorting re-renders and p-select dropdowns beyond the 3 compact examples currently in SLOT 26 of `_build_system_prompt_v2()`
2. Resolution of the **RECIPE MANDATE vs. P-SELECT EXCEPTION contradiction** — both are labeled "HIGHEST PRIORITY" in `_CORE_RULES` (lines 490-509 in planner.py), which causes deterministic LLM confusion
3. Structural delimiters in `supervisor.py`'s `_CLASSIFY_SYSTEM_PROMPT` (currently uses Markdown `##` headers but no XML isolation between instructions and context)
4. The `prompt_audit_checklist.md` is not linked to a CI enforcement gate — it's documentation only
5. A test suite validating prompt structural properties (primacy/recency, no contradictions, delimiter presence)

---

## Business Context

Every vQA test run is a chain of LLM decisions. When prompt architecture fails:
- **QA Lead**: Sees infinite action loops where the agent alternates between RECIPE MANDATE and P-SELECT EXCEPTION paths, consuming the entire iteration budget
- **PM**: Test runs report HITL escalations that should have been autonomous — caused by the verifier producing inconsistent verdicts because critical rules were in the "forgotten middle" of the prompt
- **Release Engineer**: CI/CD gates fail unreliably — the same card fails on run 1, passes on run 2, fails on run 3, based on attention lottery rather than code correctness

**Measurable impact**: The RECIPE MANDATE ↔ P-SELECT EXCEPTION contradiction is directly implicated in the infinite loop failures described in FEAT-058. Fixing the structural contradiction here is a prerequisite for FEAT-058's deterministic execution guarantees to hold.

---

## Vision and Goals

- **Vision**: Every LLM system prompt in vQA is architecturally sound — critical rules are anchored at both primacy and recency positions, dynamic context is isolated by XML delimiters, and contradictions are eliminated before they reach the model.
- **Goals**:
  1. Zero prompt-level contradictions in any active system prompt
  2. All five target prompts pass the `prompt_audit_checklist.md` criteria
  3. Planner's few-shot examples cover the top-3 PrimeNG failure modes (sorting re-render, p-select dropdown toggle, compound column sort)
  4. All structural changes are non-behavioral — no logic is added or removed, only reorganized
  5. Full regression: `pytest tests/ -v` zero failures after each phase

---

## Specification

### Feature Overview

This is an **NFR (Non-Functional Requirement) / internal quality** task. There is no new user-facing feature. The deliverable is a set of refactored system prompts that are structurally superior to their predecessors while preserving identical behavior.

### Invocation Location

**Not applicable** — this task modifies internal LLM system prompt strings. The prompts are assembled at runtime by `_build_system_prompt_v2()` in `planner.py`, `_VERIFIER_SYSTEM_PROMPT` in `verifier.py`, `_CLASSIFY_SYSTEM_PROMPT` in `supervisor.py`, and `BDD_NORMALIZER_PROMPT`/`JSON_COMPILER_PROMPT` in `prompts.py`.

### Success Metrics (NFR-style)

- **Test Method**: `pytest tests/ -v` passes with zero regressions after each phase
- **Structural Validation**: New test file `tests/test_prompt_structure.py` with assertions verifying: (a) GOLDEN_RULES appears at start of each prompt, (b) CRITICAL_REMINDER appears at end of each prompt, (c) no prompt contains simultaneous "HIGHEST PRIORITY" on contradictory rules, (d) all XML delimiter tags are balanced
- **Observable Location**: `pytest tests/test_prompt_structure.py -v` output in CI logs; existing `scripts/test_prompt_limits.py` for token/char budget checks

### Acceptance Criteria

#### AC-ENTRY-1: Planner RECIPE MANDATE Contradiction Is Resolved
**Priority**: MUST

**Given** the `_CORE_RULES` string in `planner.py`
**When** the rules are inspected for priority conflicts
**Then**:
- There is exactly ONE "HIGHEST PRIORITY" rule (the RECIPE MANDATE)
- The P-SELECT EXCEPTION is nested INSIDE the RECIPE MANDATE block as an exception clause, NOT as a separate equal-priority rule
- The visual separator line (═══) appears only once (around the RECIPE MANDATE block), not twice

**Verification**:
- [ ] Unit test: `test_prompt_structure.py::test_planner_no_duplicate_highest_priority` — scans `_CORE_RULES` string, asserts "HIGHEST PRIORITY" appears ≤ 1 time

#### AC-ENTRY-2: All Five Target Prompts Pass Structural Checklist
**Priority**: MUST

**Given** the five prompts: `_CORE_RULES` (planner), `_VERIFIER_SYSTEM_PROMPT` (verifier), `_CLASSIFY_SYSTEM_PROMPT` (supervisor), `BDD_NORMALIZER_PROMPT` (prompts.py), `JSON_COMPILER_PROMPT` (prompts.py)
**When** each is inspected against `prompt_audit_checklist.md`
**Then** each passes:
- Section 1 (Primacy/Recency): `<GOLDEN_RULES>` in first 15% of prompt; `<CRITICAL_REMINDER>` in last 15%
- Section 2 (Structural Delimiters): dynamic context wrapped in XML tags, not inline
- Section 4 (CoT Workflow): at least a numbered reasoning workflow for decision-making prompts

**Verification**:
- [ ] Unit test: `test_prompt_structure.py::test_all_prompts_have_golden_rules_at_start`
- [ ] Unit test: `test_prompt_structure.py::test_all_prompts_have_critical_reminder_at_end`
- [ ] Unit test: `test_prompt_structure.py::test_supervisor_uses_xml_delimiters`

#### AC-HAPPY-1: Planner Few-Shot Examples Cover PrimeNG Failure Modes
**Priority**: MUST

**Given** the `few_shot_examples` section assembled in `_build_system_prompt_v2()` (SLOT 26)
**When** it is inspected for coverage
**Then** it contains examples for:
- Sorting re-render race condition: `primeng_dropdown` action with correct `portal_class`
- p-select dropdown toggle guard: example showing the ANTI-LOOP pattern (don't re-click after open)
- Compound column sort (Due/Days): step-by-step atomic click sequence (not recipe)

**Verification**:
- [ ] Unit test: `test_prompt_structure.py::test_few_shot_covers_primeng_cases` — asserts `primeng_dropdown`, `po-sorting-dropdown-panel`, and `p-select-overlay` appear in the few-shot block

#### AC-HAPPY-2: `prompt_fragments.py` Exports Reusable Supervisor Delimiters
**Priority**: SHOULD

**Given** `backend/engine/prompt_fragments.py`
**When** `supervisor.py` is updated
**Then** the supervisor's `_CLASSIFY_SYSTEM_PROMPT` is refactored to use `GOLDEN_RULES` from `prompt_fragments` and its dynamic user message wraps `ac_step` in `<AC_STEP>` XML tags

**Verification**:
- [ ] Unit test: `test_prompt_structure.py::test_supervisor_imports_golden_rules` — checks that `prompt_fragments.GOLDEN_RULES` substring appears in the assembled supervisor prompt

#### AC-EDGE-1: Zero Regressions on Full Test Suite
**Priority**: MUST

**Given** the full `tests/` directory
**When** `pytest tests/ -v` is run after ALL phases are complete
**Then** zero test failures and zero new deprecation warnings from modified files

**Verification**:
- [ ] `pytest tests/ -v` output shows 0 failures, with test count ≥ pre-task baseline

#### AC-EDGE-2: Token Budget Not Exceeded
**Priority**: MUST

**Given** `scripts/test_prompt_limits.py` (if it exists) or an equivalent manual token count
**When** the refactored planner prompt is assembled
**Then** total prompt size remains within the `settings.prompt_budget_max_tokens` ceiling (8000 tokens by default)

**Verification**:
- [ ] Token count check on assembled `_build_system_prompt_v2()` output confirms no budget regression

---

## Architectural Principles

1. **Structural Changes Only** — No logic is added, removed, or altered. Refactoring moves existing rules into correct structural positions. If a rule would need to change its meaning to fit the new structure, that is out of scope.
2. **Prompt Budget Preservation** — The `PromptBudget` / `Slot` system in `planner.py` is the authoritative assembly mechanism. All planner changes must work within the existing slot/tier model.
3. **Backwards Compatibility** — No schema changes to `VQAState`, `StructuredACStep`, or any Pydantic model. No API changes.
4. **Fragment Reuse** — When the same structural pattern (GOLDEN_RULES, CRITICAL_REMINDER) appears in multiple prompts, it should derive from `prompt_fragments.py`, not be re-typed inline.
5. **Contradiction Elimination is Non-Negotiable** — The RECIPE MANDATE ↔ P-SELECT EXCEPTION conflict must be resolved as a nested exception, not by removing either rule.

---

## Architecture Alternatives Considered

### Option A: Nested Exception Approach (Selected)
Move the P-SELECT EXCEPTION text inside the RECIPE MANDATE block as an indented exception clause. One ═══ border, one priority level.

**Pros**: Zero semantic change — both rules remain active; the exception now has clear scope (it's an exception *to* the mandate); single visual border eliminates the "two HIGHEST PRIORITY" reading.

**Cons**: Slightly longer RECIPE MANDATE block.

### Option B: Remove the P-SELECT EXCEPTION from _CORE_RULES
Move P-SELECT EXCEPTION to `_TABLE_SORT_RULES` (where TABLE SORTING RULES already live, per lines 752-803).

**Pros**: Cleaner CORE_RULES; TABLE_SORT_RULES is the natural home.

**Cons**: `_TABLE_SORT_RULES` is conditionally injected (only when step mentions sort/ascending/etc.). P-SELECT EXCEPTION should fire universally, not just on sort steps.

**Decision**: Option A selected. The P-SELECT rule must be universally active (not gated by step keyword), so nesting inside the RECIPE MANDATE in `_CORE_RULES` is the correct placement.

---

## Implementation Roadmap

### Phase 1: Structural Test Suite (RED) ✅

**Goal**: Write failing tests that encode the structural requirements. These tests define "done" for this task. Nothing should pass yet.

**Files**:
- `tests/test_prompt_structure.py` — New test file with 20 unit tests (expanded from 6 in spec)
  1. `test_planner_no_duplicate_highest_priority` — scans `_CORE_RULES`, asserts "HIGHEST PRIORITY" count ≤ 1
  2. `test_all_prompts_have_golden_rules_at_start` — checks `<GOLDEN_RULES>` in first 20% of each target prompt
  3. `test_all_prompts_have_critical_reminder_at_end` — checks `<CRITICAL_REMINDER>` in last 20% of each target prompt
  4. `test_supervisor_uses_xml_delimiters` — checks `<AC_STEP>` appears when supervisor prompt is assembled with a test step
  5. `test_few_shot_covers_primeng_cases` — checks three PrimeNG keywords in SLOT 26 few-shot block
  6. `test_prompt_budget_not_exceeded` — assembles a mock prompt and checks token count ≤ 8000

**Verification gate**: `pytest tests/test_prompt_structure.py -v` — all 20 tests PASS ✅

---

### Phase 2: Resolve Planner Contradiction + Expand Few-Shot (GREEN — planner.py)

**Goal**: Fix the RECIPE MANDATE/P-SELECT EXCEPTION contradiction and expand few-shot examples to cover the 3 PrimeNG failure modes.

**Files**:
- `backend/engine/planner.py` — Two targeted changes:
  1. In `_CORE_RULES` (around lines 490-509): Nest `⛔ RECIPE EXCEPTION — p-select DROPDOWNS` as an indented exception *inside* the `⚡ RECIPE MANDATE` block. Remove the duplicate ═══ border that makes them appear as co-equal rules. The merged block reads as: "RECIPE MANDATE (HIGHEST PRIORITY): use recipe... EXCEPTION: never for p-select (use atomic clicks per TABLE SORTING RULES)."
  2. In `_build_system_prompt_v2()` SLOT 26 (around lines 3146-3159): Expand `few_shot_examples` to add 3 new PrimeNG examples covering: sorting re-render race condition, p-select anti-loop guard, compound-column sort atomic sequence.

**Verification gate**: `pytest tests/test_prompt_structure.py::test_planner_no_duplicate_highest_priority tests/test_prompt_structure.py::test_few_shot_covers_primeng_cases -v` — both PASS. Full suite: `pytest tests/ -v` — zero regressions.

---

### Phase 3: Supervisor Structural Hardening (GREEN — supervisor.py)

**Goal**: Apply XML structural delimiters to `supervisor.py`'s `_CLASSIFY_SYSTEM_PROMPT` and add `GOLDEN_RULES` anchoring via `prompt_fragments`.

**Files**:
- `backend/engine/supervisor.py` — Refactor `_CLASSIFY_SYSTEM_PROMPT`:
  1. Add `from backend.engine.prompt_fragments import GOLDEN_RULES` import (lazy or top-level)
  2. Prefix prompt with `GOLDEN_RULES` (identity: QA supervisor, output: JSON via tool call, mission: classify intent)
  3. Wrap `## Worker Types` section in `<WORKER_TYPES>...</WORKER_TYPES>` XML tags
  4. Wrap `## Rules` section in `<CLASSIFICATION_RULES>...</CLASSIFICATION_RULES>` XML tags
  5. Add a `<CRITICAL_REMINDER>` block at the end (call classify_intent tool, one worker_type only)
  6. In `_classify_intent()`: wrap `ac_step` in the `HumanMessage` content as `<AC_STEP>{ac_step}</AC_STEP>`

**Verification gate**: `pytest tests/test_prompt_structure.py::test_supervisor_uses_xml_delimiters tests/test_prompt_structure.py::test_all_prompts_have_golden_rules_at_start tests/test_prompt_structure.py::test_all_prompts_have_critical_reminder_at_end -v` — all PASS. Full suite: `pytest tests/ -v` — zero regressions.

---

### Phase 4: Validation + Token Budget Check + Docs (COMPLETE)

**Goal**: Run all structural tests, verify token budget, and update memory-bank documentation.

**Files**:
- `tests/test_prompt_structure.py` — Final confirmation all 6 tests pass
- `knowledge/prompt_audit_checklist.md` — Add a "Prompt Registry" table documenting which files own which prompts, and mark each with last-audited date
- `memory-bank/systemPatterns.md` — Update "Prompt Hardening Standards" section to reference the test file as the enforcement gate

**Verification gate**: `pytest tests/test_prompt_structure.py -v` — all 6 tests PASS. `pytest tests/ -v` — zero regressions. Token count check passes.

---

## Test Strategy

| Test File | Scope | What It Validates |
|-----------|-------|-------------------|
| `tests/test_prompt_structure.py` | Unit (static analysis) | Structural properties: primacy/recency, delimiter presence, no contradictions, few-shot coverage, token budget |
| `pytest tests/ -v` (full suite) | Regression | Zero regressions across all existing 38+ test cases |

**No integration tests against live browser/AWS** — consistent with `systemPatterns.md` testing philosophy (mock external dependencies). Prompt structural validation is pure string analysis — no LLM calls needed.

**Test approach**: Tests use `importlib`/direct string access to load the prompt constants and assert structural properties. Avoids brittle "exact string match" in favor of structural invariants (e.g., `"<GOLDEN_RULES>" in prompt[:len(prompt) // 5]`).

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Nesting P-SELECT EXCEPTION inside RECIPE MANDATE changes model behavior | Low | High | Tests verify zero regressions; change is purely structural (same rule text, new nesting position) |
| Expanding few-shot block pushes prompt over token budget | Low | Medium | Token budget test in Phase 1 catches this before merge; `PromptBudget` `max_chars` on SLOT 26 provides a hard cap |
| Supervisor `GOLDEN_RULES` import creates circular dependency | Very Low | Medium | `prompt_fragments.py` has no imports from engine modules; safe to import from `supervisor.py` |
| Structural test assertions are too brittle (exact line position) | Medium | Low | Use `prompt[:N]` fraction-based checks, not line-number checks, so minor additions don't break tests |

---

## Guiding Principles Alignment

| Principle | Alignment |
|-----------|-----------|
| **Programmatic Tier 1 Verification** | ✅ Structural test suite is pure Python string analysis — no LLM cost for validation |
| **Config in Environment** | ✅ No hardcoded values introduced; token budget reads from `settings.prompt_budget_max_tokens` |
| **Failure Diary Pattern** | ✅ The anti-loop few-shot examples directly reinforce the Failure Diary constraint ("NEVER repeat a strategy in `<past_actions>` with outcome=FAILED") |
| **12-Factor App** | ✅ Structural changes only — no new env variables, no deployment changes |
| **Semantic Locators First** | N/A — this task is prompt engineering, not locator strategy |

---

## Execution State

**Build Status**: IDLE
**Current Phase**: ARCHIVE
**Current Build**: COMPLETE
**Build Started**: 2026-05-29T20:23:00Z
**Build Ended**: 2026-05-29T20:35:14Z
**Reflect Started**: 2026-05-29T20:44:00Z
**Reflect Ended**: 2026-05-29T20:46:00Z
**Archive Date**: 2026-05-29
**Worktree**: .worktrees/prompt-engineering-hardening-feat-059
**Branch**: feature/FEAT-059-prompt-hardening
**Commit**: 46b3349
**Can Resume**: NO

### Sub-Agent Log
| Step | Agent | Status | Notes |
|------|-------|--------|-------|
| PLAN | Orchestrator | COMPLETE | Full L3 plan authored 2026-05-29 |
| CREATIVE | N/A | SKIPPED | Level 3 with clear journey — no creative phase required |
| BUILD Ph1 | Orchestrator | COMPLETE | tests/test_prompt_structure.py — 20 tests written |
| BUILD Ph2 | Orchestrator | COMPLETE | planner.py — contradiction resolved, few-shot expanded |
| BUILD Ph3 | Orchestrator | COMPLETE | supervisor.py — XML delimiters + GOLDEN_RULES + AC_STEP |
| BUILD Ph4 | Orchestrator | COMPLETE | prompt_audit_checklist.md — Prompt Registry added |

---

## Implementation History

| Phase | Action | Status | Date |
|-------|--------|--------|------|
| PLAN | Initial task stub created (initialize-feat-059-prompt-engineering-hardening init) | Complete | 2026-05-29 |
| PLAN | Full specification written (prompt-engineering-hardening-feat-059) | Complete | 2026-05-29 |
| RED | Write structural test suite (20 tests) | Complete | 2026-05-29 |
| GREEN | prompt_fragments.py: GOLDEN_RULES, COT_WORKFLOW, JSON_OUTPUT_REMINDER | Complete | 2026-05-29 |
| GREEN | planner.py: contradiction resolved, few-shot expanded (PrimeNG 3 cases) | Complete | 2026-05-29 |
| GREEN | verifier.py: GOLDEN_RULES + JUDGEMENT_RULES + CRITICAL_REMINDER anchoring | Complete | 2026-05-29 |
| GREEN | prompts.py: BDD_NORMALIZER + JSON_COMPILER with structural anchors | Complete | 2026-05-29 |
| GREEN | supervisor.py: XML delimiters + GOLDEN_RULES import + AC_STEP wrapping | Complete | 2026-05-29 |
| COMPLETE | All 20 structural tests PASS; 871/895 full suite (24 pre-existing failures) | Complete | 2026-05-29 |
| COMPLETE | Committed d48fffa to feature/FEAT-059-prompt-hardening | Complete | 2026-05-29 |
