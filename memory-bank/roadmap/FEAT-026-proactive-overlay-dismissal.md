---
legacy_id: FEAT-026
version: v2.1.0
linked_tasks: [proactive-overlay-dismissal]
status: complete
---

### FEAT-026: Proactive Overlay Dismissal
- **Version**: v2.1.0
- **Status**: complete
- **Priority**: medium
- **Complexity**: Level 2
- **Description**: When `state_tracker.has_open_overlay()` returns True and the target element is NOT inside the overlay's DOM container, auto-press Escape before the planner generates an action. Prevents the common failure where the planner tries to click an element behind a blocking overlay (INTERCEPTED errors). Simple pre-action gate in executor.py using existing state_tracker overlay constraint API. 1-2 files affected.
- **Linked Tasks**: proactive-overlay-dismissal (COMPLETE)
- **Branch**: feature/proactive-overlay-dismissal-proactive-overlay-dismissal
- **Created**: 2026-05-11
- **Completed**: 2026-05-12
