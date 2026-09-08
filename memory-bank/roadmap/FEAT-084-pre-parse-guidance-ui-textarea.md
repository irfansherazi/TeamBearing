---
legacy_id: FEAT-084
version: v1.0.0-prod-readiness
linked_tasks: [pre-parse-guidance-ui-textarea, pre-parse-guidance-ui-textarea]
status: complete
---

### FEAT-084: Pre-Parse Guidance UI Textarea
- **Version**: v1.0.0-prod-readiness
- **Status**: complete ✅
- **Priority**: critical
- **Complexity**: Level 2
- **Pillar**: P3 — AC Review / HITL UX
- **Gap ID**: P3-A
- **Estimated Effort**: ~4h
- **Description**: The `pre_parse_guidance` API field exists in VQAState and is read by the AC parser, but there is no UI input wired to it — meaning zero operators use it. Fix: add an "Additional Context" textarea to `ReviewView` that submits its value as `pre_parse_guidance` when the run is initiated.
- **Acceptance Criteria**:
  - AC-1: `ReviewView` displays an "Additional Context" textarea above the "Start Run" button.
  - AC-2: Textarea value is POSTed as `pre_parse_guidance` in the run initiation payload.
  - AC-3: The AC parser correctly receives and applies the submitted guidance.
  - AC-4: Textarea is pre-populated with any existing `pre_parse_guidance` value when editing a queued run.
  - AC-5: Character limit of 2000 chars enforced with a live counter.
- **Key Files**:
  - `frontend/src/components/ReviewView.tsx`
  - `backend/api/routes.py` — run initiation endpoint
  - `backend/engine/state.py` — `VQAState.pre_parse_guidance`
- **Linked Tasks**: [pre-parse-guidance-ui-textarea](tasks/pre-parse-guidance-ui-textarea.md)
- **Branch**: feature/FEAT-084-pre-parse-guidance-ui
- **Created**: 2026-06-03
