---
legacy_id: advanced-ac-parsing-and-decomposition
---
# advanced-ac-parsing-and-decomposition: Advanced AC Parsing & Decomposition

**Status**: COMPLETE
**Phase**: ARCHIVE
**Complexity**: Level 3
**Roadmap Link**: FEAT-057
**Branch**: feature/FEAT-057-advanced-parsing
**Created**: 2026-05-29

---

## Summary

Advanced AC parsing and decomposition to handle compound Jira actions and improve ADF extraction quality. Implements atomic step decomposition at the BDD level and deferred verification for mechanically inseparable sub-steps.

## Status: COMPLETE (2026-05-29)

### 1. ADF Extraction Improvements
- Fixed word fusion bug at mark boundaries (e.g., "log in asAccount Executive") using regex boundary checking.
- Implemented `|` separator for table row extraction to preserve cell structure.
- Verified with `tests/test_adf_mark_boundary.py` and `tests/test_adf_table_extraction.py`.

### 2. Atomic Step Decomposition
- Added Rule 13 to `BDD_NORMALIZER_PROMPT` to force decomposition of compound actions (e.g., "click and select" → 2 steps).
- Added `sub_steps` field to `StructuredACStep` schema for composite actions.
- Updated `JSON_COMPILER_PROMPT` to emit sub-steps when appropriate.
- Verified with `tests/test_sub_steps_schema.py`.

### 3. Executor Deferred Verification
- Added `current_sub_step_index` to `VQAState`.
- Implemented verification gate in `evaluator_node` to defer full checks until the final sub-step completes.
- Verified with `tests/test_executor_sub_step_deferral.py`.

---

## Acceptance Criteria

### AC-ENTRY-1: ADF Mark Boundary Word Fusion Bug Is Fixed
- **Given** a Jira ticket with ADF text nodes separated by mark boundaries (e.g., bold/code/link marks)
- **When** `_extract_text_from_adf()` is called on the ADF structure
- **Then** words at mark boundaries are separated by a space (e.g., "log in as **Account Executive**" → "log in as Account Executive", NOT "log in asAccount Executive")

### AC-ENTRY-2: ADF Table Row Text Extraction Preserves Cell Separators
- **Given** a Jira ticket containing an ADF table with multiple rows and columns
- **When** `_extract_text_from_adf()` is called
- **Then** table cell content is joined with a separator (e.g., " | " or newline) so that adjacent cell values are not fused

### AC-HAPPY-1: BDD Normalizer Splits Compound Actions Into Atomic Steps
- **Given** Jira AC text containing compound actions (e.g., "Click the dropdown and select 'Account Executive'")
- **When** Stage 1 BDD normalization runs
- **Then** the output BDD scenario contains separate atomic When-steps: one for the click, one for the select — NEVER combined in a single step

### AC-HAPPY-2: `sub_steps` Optional Field Exists on StructuredACStep
- **Given** a TestPlan JSON emitted by Stage 2
- **When** a compound Jira action is decomposed into sub-steps by the BDD normalizer
- **Then** the corresponding `StructuredACStep` may contain a `sub_steps: list[str]` field listing the ordered atomic sub-actions, and `max_actions` is set to cover the full compound sequence

### AC-HAPPY-3: Executor Defers Full Verification Until Final Sub-Step
- **Given** a `StructuredACStep` with a non-empty `sub_steps` list
- **When** the planner/executor processes the step
- **Then** the executor runs each sub-action in sequence and only triggers the step's `verification` checks after the last sub-step completes (not after each individual sub-action)

### AC-EDGE-1: Fix Is Backward Compatible — No Regression on Existing TestPlan Parsing
- **Given** the existing test suite (`pytest tests/ -v`)
- **When** the ADF fix and schema addition are applied
- **Then** all existing tests pass with zero regressions

### AC-EDGE-2: `sub_steps` Defaults to Empty List — Existing Steps Unaffected
- **Given** any `StructuredACStep` without a `sub_steps` field (legacy test plans, non-compound steps)
- **When** the step is deserialized by Pydantic
- **Then** `sub_steps` defaults to `[]` and executor behavior is unchanged

### AC-EDGE-3: reproduce_jira_parsing.py Verifies The ADF Fix
- **Given** the `reproduce_jira_parsing.py` script is run against a mock ADF with mark boundaries
- **When** the ADF extraction is executed
- **Then** the output text is free of word fusion artifacts at mark/inline-mark boundaries

---

## Implementation History
| Phase | Action | Status | Date |
|-------|--------|--------|------|
| PLAN | Initial task creation | Complete | 2026-05-29 |
| RED | Created failing tests for ADF and Schema | Complete | 2026-05-29 |
| GREEN | Implemented ADF fixes and Schema changes | Complete | 2026-05-29 |
| GREEN | Updated BDD/JSON prompts for decomposition | Complete | 2026-05-29 |
| GREEN | Implemented Executor deferred verification | Complete | 2026-05-29 |
| REVIEW | Peer review by 'generalist' agent | Complete | 2026-05-29 |
| DOCS | Updated advanced-ac-parsing-and-decomposition.md and session-log.md | Complete | 2026-05-29 |
