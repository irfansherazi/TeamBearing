---
legacy_id: FEAT-096
version: v1.0.0-prod-readiness
linked_tasks: []
status: planned
---

### FEAT-096: PrimeNG Real-Browser Executor Test Fixtures
- **Version**: v1.0.0-prod-readiness
- **Status**: planned
- **Priority**: high
- **Complexity**: Level 3
- **Pillar**: P6 — Test Coverage & Quality Gates
- **Gap ID**: P6-A
- **Estimated Effort**: ~8h
- **Description**: All executor and evaluator tests mock Playwright, meaning real PrimeNG locator failure modes (strict mode violation, timeout, not_visible, intercepted, detached) have zero test coverage. Fix: create a `tests/browser/` fixture suite that loads CDN-hosted PrimeNG components in a real Playwright browser and exercises each failure mode end-to-end.
- **Acceptance Criteria**:
  - AC-1: `tests/browser/fixtures/primeng_table.html` loads a real PrimeNG DataTable via CDN.
  - AC-2: Tests cover all 5 failure modes: strict mode violation, timeout, not_visible, intercepted, detached.
  - AC-3: Each failure mode test verifies the correct recovery path is triggered (not a silent pass).
  - AC-4: Tests run in CI via `pytest tests/browser/ -v` with a headed or headless Chromium fixture.
  - AC-5: `README.md` documents how to run the browser fixture suite locally.
- **Key Files**:
  - `tests/browser/fixtures/primeng_table.html` (new)
  - `tests/browser/test_executor_primeng.py` (new)
  - `tests/browser/conftest.py` (new)
- **Linked Tasks**: None
- **Branch**: feature/FEAT-096-primeng-browser-test-fixtures
- **Created**: 2026-06-03
