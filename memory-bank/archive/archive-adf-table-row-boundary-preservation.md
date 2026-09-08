# Archive: adf-table-row-boundary-preservation — ADF Table Row Boundary Preservation

**Archived**: 2026-06-03  
**Status**: COMPLETE  
**Complexity**: Level 2  
**Feature**: FEAT-075 (ADF Table Row Boundary Preservation)  
**Branch**: `feature/FEAT-075-adf-table-row-boundaries`  
**Merge Commit**: Local Commit  
**Repo**: https://github.com/vcreativeinc/vQA/commit/main

---

## What Was Built

We implemented high-fidelity parsing of tables in the Jira Atlassian Document Format (ADF) to preserve row boundaries and prevent multi-role acceptance criteria tables from collapsing into run-on text in the downstream BDD normalizer.

### Key Design Decisions
- **Cardinality Sentinel Prefixing**: Prepended the `[AC TABLE: N rows]\n` sentinel string before the numbered row list to supply a clear structured hint for downstream parsing. This gives the system prompt an unambiguous hook to enforce cardinality constraints.
- **Explicit Table Row Boundary Parsing**: Added a custom container handler in `_extract_text_from_adf()` inside `backend/jira/client.py` for `"table"` node types. It iterates explicitly through rows (`"tableRow"`), extracts and strips cell contents recursively, and formats each row as a standard Markdown piped block (`| col 1 | col 2 |`).
- **Recursive Container Isolation**: Excluded the `"table"` node type from the generic recursive fall-through list in `_extract_text_from_adf` to prevent nested table structures from being parsed twice or incorrectly flattened.
- **Prompt-Level Rule Reinforcement**: Integrated strict instructions under Rule 3 ("Handle Structured Data") in `BDD_NORMALIZER_PROMPT` in `backend/engine/prompts.py`. It directs the LLM to identify the `[AC TABLE: N rows]` sentinel and deterministically emit distinct `Scenario:` blocks for each row/role in the table, completely solving the scenario-collapsing issue.

---

## Implementation Summary

### Files Changed (4 files, +172 net lines added, -6 lines deleted)

| File | Change |
|------|--------|
| `backend/jira/client.py` | Implemented explicit ADF table node parsing with pipe-separated rows and `[AC TABLE: N rows]` sentinel formatting. Excluded `"table"` from default container recursion. |
| `backend/engine/prompts.py` | Added specific rules to `BDD_NORMALIZER_PROMPT` for handling `[AC TABLE: N rows]` sentinel to enforce separate scenario generation per row. |
| `tests/test_adf_table_extraction.py` | Updated `test_adf_table_row_separator` unit test to verify new sentinel-prefix and piped row outputs. |
| `tests/test_task_099_table_normalizer.py` | Created 4 new comprehensive tests covering single-row, multi-row, empty/nested content table extractions, and prompt rule integration. |

---

## Test Results

| Metric | Value |
|--------|-------|
| Tests written | 4 brand-new, 1 updated |
| Tests passing | 5/5 (100%) |
| Dependent tests passing | 5/5 (100%) |
| Regressions introduced | 0 |

---

## Acceptance Criteria Coverage

| AC | Status | Notes |
|----|--------|-------|
| AC-HAPPY-1 | ✅ PASS | Every table row is extracted, formatted with markdown pipes, and numbered as a separate list item (e.g. `1. | Header 1 | Header 2 |`). |
| AC-HAPPY-2 | ✅ PASS | Table blocks are successfully prepended with the standard sentinel string indicating row count (e.g., `[AC TABLE: 2 rows]`). |
| AC-HAPPY-3 | ✅ PASS | Integration test confirms the BDD Normalizer prompt updates integrate seamlessly and include strict table-sentinel handling. |
| AC-EDGE-1 | ✅ PASS | Gracefully processes single-row, multi-row, and nested-cell structures (such as cells containing hard line breaks or lists) without crashing. |

---

## Rule Consolidation (Archive Phase)

No rules were pruned because all rules remain active and highly accurate.

**Files amended in reflection**:
- `memory-bank/agent-rules/_learned/jira-robustness.md` (+1 rule: `Recursive Parser Exclusions`)
- `memory-bank/agent-rules/_learned/prompt-engineering.md` (+1 rule: `Cardinality Sentinel Markers`)

---

## Retrospective Notes

See full reflection at [reflection-adf-table-row-boundary-preservation.md](../reflection/reflection-adf-table-row-boundary-preservation.md).

**Key Learnings**:
- **Sentinel Markers for Downstream LLM Prompt Hooking**: Prefixing a structural text block with an explicit count sentinel (like `[AC TABLE: N rows]`) provides the downstream LLM with a clear constraint target to enforce row cardinality during parsing.
- **Whitelisting Container Recurse Exclusions**: Custom-handled container types should always be removed from generic recursion fallback lists to prevent duplicate processing loops.

---

## Next Work

- **intelligent-ingestion-and-pre-flight-verification: Intelligent Ingestion & Pre-Flight Verification (FEAT-070)** — Hybrid LLM-in-the-Loop Enricher and negative path synthesis.
