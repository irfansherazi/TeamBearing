---
legacy_id: adf-table-row-boundary-preservation
---
# adf-table-row-boundary-preservation: ADF Table Row Boundary Preservation

**Status**: COMPLETE
**Complexity**: Level 2
**Roadmap Link**: FEAT-075
**Branch**: feature/FEAT-075-adf-table-row-boundaries
**Worktree**: .worktrees/FEAT-075
**Pillar**: P1 — Jira Ingestion
**Gap ID**: P1-A
**Estimated Effort**: ~2h
**Created**: 2026-06-03

---

## Description

`_extract_text_from_adf()` in the Jira ADF parser currently flattens table cells into run-on text, causing the BDD normalizer to collapse multi-role acceptance criteria into single scenarios. Fix: emit each table row as a numbered list item (e.g., `1. | Col A | Col B |`) and prepend an `[AC TABLE: N rows]` sentinel so the downstream AC parser can reconstruct row boundaries and generate distinct BDD scenarios per role/row.

---

## Acceptance Criteria

### AC-HAPPY-1: Each table row in an ADF table node is emitted as a separate numbered list item
**Priority**: MUST

**Given** an ADF document containing a `table` node with 2 rows and 2 columns
**When** `_extract_text_from_adf()` is called on the document
**Then** the output text contains:
  - `1. | Header 1 | Header 2 |`
  - `2. | Value 1 | Value 2 |`

**Verification**:
- [x] Unit test in `tests/test_adf_table_extraction.py` or `tests/test_adf_parser.py`

### AC-HAPPY-2: Table sentinel is prepended to the extracted block
**Priority**: MUST

**Given** an ADF document containing a `table` node with 2 rows
**When** `_extract_text_from_adf()` is called on the document
**Then** the output contains the sentinel `[AC TABLE: 2 rows]` prepended directly before the rows

**Verification**:
- [x] Unit test in `tests/test_adf_table_extraction.py` or `tests/test_adf_parser.py`

### AC-HAPPY-3: BDD Normalizer produces separate scenarios per table row for multi-role AC tables
**Priority**: MUST

**Given** raw AC containing the `[AC TABLE: N rows]` sentinel and rows formatted as numbered list items
**When** `_stage_1_normalize` is called to run the BDD normalizer LLM
**Then** the output contains distinct `Scenario:` blocks for each table row instead of collapsing them into one run-on scenario

**Verification**:
- [x] Integration test in `tests/test_task_099_table_normalizer.py`

### AC-EDGE-1: Single-row, multi-row, and nested-table ADF inputs are parsed gracefully
**Priority**: MUST

**Given** ADF inputs for single-row tables, multi-row tables, or tables with nested content
**When** `_extract_text_from_adf()` is called
**Then** they are parsed without crashes and maintain consistent sentinel and numbering formats

**Verification**:
- [x] Unit tests covering single-row, multi-row, and nested/complex cells

---

## Clarifications Needed

_None — requirements are clear from FEAT-075 specification._

---

## Implementation Roadmap

### 1. Jira ADF Parser Updates (`backend/jira/client.py`)
- Implement a custom parser block for `"table"` node-type in `_extract_text_from_adf()`.
- Extract rows from `children` (where `type == "tableRow"`).
- For each row, iterate over cells (where type is `tableHeader` or `tableCell`), call `_extract_text_from_adf()` recursively on each cell, and strip surrounding whitespace.
- Join cells of each row with `" | "` and format as `"| cell1 | cell2 |"`.
- Collect all non-empty rows, and format them as numbered list items: `f"{i}. | {row_text} |"`.
- Prepend the sentinel string `f"[AC TABLE: {len(rows)} rows]\n"`.
- Exclude `"table"` from the known container types list so it doesn't fall through to the default recursion.

### 2. BDD Normalizer Prompt Updates (`backend/engine/prompts.py`)
- Update `BDD_NORMALIZER_PROMPT` under `<RULES>`, specifically Rule 3 ("Handle Structured Data"), adding instructions for `[AC TABLE: N rows]`:
  - When an AC table is detected with the `[AC TABLE: N rows]` sentinel, generate separate Given/When/Then scenarios for each row/role in the table, rather than collapsing them.

### 3. Update Existing Tests (`tests/test_adf_table_extraction.py`)
- Update `test_adf_table_row_separator` to assert the new expected output format (sentinel and list items).

### 4. Create New Unit/Integration Tests (`tests/test_task_099_table_normalizer.py`)
- Create unit tests verifying:
  - Single-row table extraction
  - Multi-row table extraction
  - Nested tables and empty/missing cells
  - Integration with BDD Normalizer prompt assembly or LLM invocation.

---

## Test Strategy

### 1. Unit Tests (`tests/test_adf_table_extraction.py`)
- Verify that `_extract_text_from_adf()` correctly handles table inputs, emitting the `[AC TABLE: N rows]` sentinel and formatting row cell collections.

### 2. Integration Tests (`tests/test_task_099_table_normalizer.py`)
- Mock/test Stage 1 normalizer with simulated table inputs, confirming that the updated prompt instructions result in separate scenarios and prevent row collapsing.

---

## Creative Phases

_None required — Level 2, journey is clear._

---

## Execution State

**Build Status**: COMPLETED
**Current Phase**: IDLE
**Can Resume**: NO
