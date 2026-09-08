---
legacy_id: FEAT-087
version: v1.0.0-prod-readiness
linked_tasks: []
status: planned
---

### FEAT-087: HITL Timeout Skip-Step Config Option
- **Version**: v1.0.0-prod-readiness
- **Status**: planned
- **Priority**: medium
- **Complexity**: Level 2
- **Pillar**: P3 — AC Review / HITL UX
- **Gap ID**: P3-D
- **Estimated Effort**: ~2h
- **Description**: The HITL 5-minute timeout always routes to the reporter as a terminal run failure, which is unsuitable for overnight or CI runs. Fix: add a `hitl_timeout_action` config option with two values: `"fail"` (current behavior) and `"skip_step"` (auto-skip and continue the run, logging `skip_reason=TIMEOUT`).
- **Acceptance Criteria**:
  - AC-1: `config.py` exposes `HITL_TIMEOUT_ACTION` with default `"fail"`.
  - AC-2: When `HITL_TIMEOUT_ACTION == "skip_step"`, timeout auto-skips the current step with `skip_reason=TIMEOUT` and the run continues.
  - AC-3: CI/overnight documentation recommends setting `HITL_TIMEOUT_ACTION=skip_step`.
  - AC-4: The timeout action decision is logged at INFO level.
- **Key Files**:
  - `backend/config.py` — `HITL_TIMEOUT_ACTION`
  - `backend/engine/human_takeover.py` — timeout handler
- **Linked Tasks**: None
- **Branch**: feature/FEAT-087-hitl-timeout-skip-step
- **Created**: 2026-06-03
