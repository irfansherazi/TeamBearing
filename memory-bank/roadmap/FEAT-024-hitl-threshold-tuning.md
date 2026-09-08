---
legacy_id: FEAT-024
version: v2.0.0
linked_tasks: [hitl-threshold-tuning]
status: complete
---

### FEAT-024: HITL Threshold Tuning
- **Version**: v2.0.0
- **Status**: complete
- **Priority**: medium
- **Complexity**: Level 2
- **Description**: Increase HITL trigger threshold from 2→4 consecutive failures (FM-4), with failure-type-aware exceptions. INTERCEPTED failures that can't be auto-dismissed still escalate at 2. STRICT_MODE with >10 matches escalates at 3 (needs human disambiguation). TIMEOUT and DETACHED get the full 4-retry budget since they are most likely to self-heal. Configurable via config.py. Primarily touches evaluator.py threshold logic.
- **Linked Tasks**: hitl-threshold-tuning (COMPLETE)
- **Branch**: feature/FEAT-024-hitl-threshold-tuning
- **Created**: 2026-05-11
- **Completed**: 2026-05-12
