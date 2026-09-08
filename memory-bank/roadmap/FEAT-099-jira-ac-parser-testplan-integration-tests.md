---
legacy_id: FEAT-099
version: v1.0.0-prod-readiness
linked_tasks: []
status: planned
---

### FEAT-099: Jira → AC Parser → TestPlan Integration Tests
- **Version**: v1.0.0-prod-readiness
- **Status**: planned
- **Priority**: high
- **Complexity**: Level 3
- **Pillar**: P6 — Test Coverage & Quality Gates
- **Gap ID**: P6-D
- **Estimated Effort**: ~5h
- **Description**: There is no integration test for the full Jira → AC Parser → TestPlan pipeline. Fix: create `tests/integration/test_ac_pipeline.py` with 5 sanitized ADF fixture files covering common real-world ticket shapes (simple AC list, table-based AC, multi-actor scenario, vague/FAIR-grade, attachment-heavy).
- **Acceptance Criteria**:
  - AC-1: `tests/integration/test_ac_pipeline.py` exists with at least 5 parameterized test cases.
  - AC-2: Fixture ADF payloads are stored in `tests/integration/fixtures/adf/` (sanitized — no real customer data).
  - AC-3: Each test asserts on `TestPlan` output: step count, role assignments, scenario names, and quality grade.
  - AC-4: Tests run without a live Jira connection (ADF fixtures are local files).
  - AC-5: All 5 tests pass on the current codebase after FEAT-075 and FEAT-076 are merged.
- **Key Files**:
  - `tests/integration/test_ac_pipeline.py` (new)
  - `tests/integration/fixtures/adf/` (new directory, 5 fixture files)
- **Linked Tasks**: None
- **Branch**: feature/FEAT-099-ac-pipeline-integration-tests
- **Created**: 2026-06-03
