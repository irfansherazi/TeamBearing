---
legacy_id: FEAT-027
version: v2.1.0
linked_tasks: [toast-capture-enhancement]
status: complete
---

### FEAT-027: Toast Capture Enhancement
- **Version**: v2.1.0
- **Status**: complete
- **Priority**: medium
- **Complexity**: Level 2
- **Description**: Inject a persistent MutationObserver at login time that captures ALL PrimeNG toast text into a rolling buffer (max 10 entries, FIFO). The verifier reads from the buffer instead of polling the DOM for toast visibility (FM-7). Eliminates the race condition where toasts auto-dismiss before the verifier fires. Touches browser context initialization (observer injection) and verifier.py toast_message handler. 2-3 files affected.
- **Linked Tasks**: toast-capture-enhancement (COMPLETE)
- **Branch**: feature/toast-capture-enhancement-toast-capture
- **Created**: 2026-05-11
- **Completed**: 2026-05-12
