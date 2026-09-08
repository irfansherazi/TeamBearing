---
legacy_id: FEAT-092
version: v1.0.0-prod-readiness
linked_tasks: []
status: planned
---

### FEAT-092: LLM Failure Analysis Feature Flag
- **Version**: v1.0.0-prod-readiness
- **Status**: planned
- **Priority**: medium
- **Complexity**: Level 1
- **Pillar**: P5 — Traceability & Reporting
- **Gap ID**: P5-A
- **Estimated Effort**: <30min
- **Description**: LLM failure analysis is called unconditionally on every failed run, adding ~5s latency per failure. Fix: add an `ENABLE_LLM_FAILURE_ANALYSIS` feature flag to `config.py` (default `True`) that gates the analysis call.
- **Acceptance Criteria**:
  - AC-1: `config.py` exposes `ENABLE_LLM_FAILURE_ANALYSIS` (default `True`).
  - AC-2: When `False`, the reporter skips the LLM failure analysis call entirely.
  - AC-3: The skip is logged at INFO level.
- **Key Files**:
  - `backend/config.py`
  - `backend/engine/reporter.py` — failure analysis call site
- **Linked Tasks**: None
- **Branch**: feature/FEAT-092-llm-failure-analysis-flag
- **Created**: 2026-06-03
