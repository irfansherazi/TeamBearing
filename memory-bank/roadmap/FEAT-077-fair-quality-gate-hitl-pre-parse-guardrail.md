---
legacy_id: FEAT-077
version: v1.0.0-prod-readiness
linked_tasks: [fair-quality-gate-hitl-pre-parse-guardrail, fair-quality-gate-hitl-pre-parse-guardrail]
status: planned
---

### FEAT-077: FAIR Quality Gate HITL Pre-Parse Guardrail
- **Version**: v1.0.0-prod-readiness
- **Status**: planned
- **Priority**: critical
- **Complexity**: Level 2
- **Pillar**: P1 — Jira Ingestion
- **Gap ID**: P1-C
- **Estimated Effort**: ~3h
- **Description**: The AC quality gate currently passes FAIR-graded tickets silently into autonomous runs, even though FAIR-grade tickets require 3+ HITL escalations on average. Fix: when `quality_grade == "fair"`, set `awaiting_pre_parse_guidance = True` on VQAState and surface a warning panel to the operator before the run proceeds. The operator can supply `pre_parse_guidance` text or explicitly approve the run despite the FAIR grade.
- **Acceptance Criteria**:
  - AC-1: When `quality_grade == "fair"`, `VQAState.awaiting_pre_parse_guidance` is set to `True` before execution starts.
  - AC-2: A warning panel is surfaced in the UI listing the specific FAIR-grade deficiencies detected by the quality gate.
  - AC-3: The operator can enter `pre_parse_guidance` text directly in the warning panel and click "Proceed" to continue.
  - AC-4: The operator can click "Proceed Anyway" to bypass the guardrail without guidance text (approved override logged).
  - AC-5: GOOD and POOR grades are unaffected — only FAIR triggers the guardrail.
- **Key Files**:
  - `backend/engine/ac_quality_gate.py`
  - `backend/engine/state.py` — `VQAState.awaiting_pre_parse_guidance`
  - `frontend/src/components/ReviewView.tsx`
  - `backend/api/routes.py`
- **Linked Tasks**: [fair-quality-gate-hitl-pre-parse-guardrail](tasks/fair-quality-gate-hitl-pre-parse-guardrail.md)
- **Branch**: feature/FEAT-077-fair-quality-gate-guardrail
- **Created**: 2026-06-03
