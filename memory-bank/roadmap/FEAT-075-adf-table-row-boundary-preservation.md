---
legacy_id: FEAT-075
version: v1.0.0-prod-readiness
linked_tasks: [adf-table-row-boundary-preservation, adf-table-row-boundary-preservation]
status: complete
---

### FEAT-075: ADF Table Row Boundary Preservation
- **Version**: v1.0.0-prod-readiness
- **Status**: complete ✅
- **Priority**: high
- **Complexity**: Level 2
- **Pillar**: P1 — Jira Ingestion
- **Gap ID**: P1-A
- **Estimated Effort**: ~2h
- **Description**: `_extract_text_from_adf()` in the Jira ADF parser currently flattens table cells into run-on text, causing the BDD normalizer to collapse multi-role acceptance criteria into single scenarios. Fix: emit each table row as a numbered list item (e.g., `1. | Col A | Col B |`) and prepend an `[AC TABLE: N rows]` sentinel so the downstream AC parser can reconstruct row boundaries and generate distinct BDD scenarios per role/row.
- **Acceptance Criteria**:
  - AC-1: Each table row in an ADF `table` node is emitted as a separate numbered list item by `_extract_text_from_adf()`.
  - AC-2: An `[AC TABLE: N rows]` sentinel is prepended to the extracted block where N matches the actual row count.
  - AC-3: The BDD normalizer produces one scenario per table row for multi-role AC tables (no row-collapsing).
  - AC-4: Unit tests cover single-row, multi-row, and nested-table ADF inputs.
- **Key Files**:
  - `backend/jira/client.py` — `_extract_text_from_adf()`
  - `backend/engine/ac_parser.py` — BDD normalizer
  - `tests/test_task_099_table_normalizer.py` (new)
- **Linked Tasks**: [adf-table-row-boundary-preservation](tasks/adf-table-row-boundary-preservation.md)
- **Branch**: feature/FEAT-075-adf-table-row-boundaries
- **Created**: 2026-06-03
- **Completed**: 2026-06-03 ✅
