---
legacy_id: FEAT-085
version: v1.0.0-prod-readiness
linked_tasks: []
status: planned
---

### FEAT-085: HITL JS Action Capture Navigation Race Fix
- **Version**: v1.0.0-prod-readiness
- **Status**: planned
- **Priority**: low
- **Complexity**: Level 2
- **Pillar**: P3 — AC Review / HITL UX
- **Gap ID**: P3-B
- **Estimated Effort**: ~3h
- **Description**: The HITL JS action capture listener has a race condition on navigation — `learned_workflows.json` entries are incomplete when navigation occurs before `framenavigated` fires. Fix: buffer captured actions in-memory and only flush to `learned_workflows.json` after `page.wait_for_load_state("domcontentloaded")` confirms the post-navigation frame is stable.
- **Acceptance Criteria**:
  - AC-1: Action capture buffer is held in memory and not flushed until `domcontentloaded` fires post-navigation.
  - AC-2: `learned_workflows.json` entries are never written mid-navigation (no partial entries).
  - AC-3: Integration test: simulate a click-that-navigates during HITL; verify the resulting entry contains the complete pre- and post-navigation action sequence.
- **Key Files**:
  - `backend/engine/human_takeover.py` — `_on_human_action()`, action buffer flush
- **Linked Tasks**: None
- **Branch**: feature/FEAT-085-hitl-navigation-race-fix
- **Created**: 2026-06-03
