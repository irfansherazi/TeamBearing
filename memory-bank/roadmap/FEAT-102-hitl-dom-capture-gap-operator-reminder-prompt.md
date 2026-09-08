---
legacy_id: FEAT-102
version: v1.0.0-prod-readiness
linked_tasks: [production-readiness-kb-workflows-hitl-reminder-sales-exec-c, production-readiness-kb-workflows-hitl-reminder-sales-exec-c]
status: complete
---

### FEAT-102: HITL DOM Capture Gap — Operator Reminder Prompt
- **Version**: v1.0.0-prod-readiness
- **Status**: complete ✅
- **Priority**: medium
- **Complexity**: Level 2
- **Pillar**: P3 — HITL Reliability
- **Description**: When a HITL takeover completes but 0 DOM actions were captured, it means the operator typed an explanation but did not demonstrate the actual interaction in the vQA-controlled browser. Add a UI prompt in the human takeover panel reminding operators to perform the action in the vQA browser window before submitting, so the `_inject_click_capture_listener` can record it for replay.
- **Acceptance Criteria**:
  - AC-1: The HITL takeover panel displays a persistent reminder: "Please demonstrate the action in the vQA browser window before clicking Done — this captures the interaction for automatic replay."
  - AC-2: The reminder is visually distinct (e.g., info banner / callout box) and appears before the operator can submit.
  - AC-3: If the operator clicks Done with 0 captured DOM actions AND has entered text in the explanation box, a confirmation dialog warns: "No browser actions were recorded. Continue anyway?" with Proceed / Go Back options.
  - AC-4: The captured DOM action count is displayed live in the panel (e.g., "🎬 3 actions recorded") so the operator knows recording is working.
- **Key Files**:
  - `frontend/src/components/TakeoverPanel.tsx`
  - `backend/engine/human_takeover.py`
- **Linked Tasks**: [production-readiness-kb-workflows-hitl-reminder-sales-exec-c](tasks/production-readiness-kb-workflows-hitl-reminder-sales-exec-c.md)
- **Branch**: feature/FEAT-102-hitl-dom-capture-prompt
- **Created**: 2026-06-03
