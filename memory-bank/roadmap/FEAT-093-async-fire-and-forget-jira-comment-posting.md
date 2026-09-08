---
legacy_id: FEAT-093
version: v1.0.0-prod-readiness
linked_tasks: []
status: planned
---

### FEAT-093: Async Fire-and-Forget Jira Comment Posting
- **Version**: v1.0.0-prod-readiness
- **Status**: planned
- **Priority**: low
- **Complexity**: Level 2
- **Pillar**: P5 — Traceability & Reporting
- **Gap ID**: P5-B
- **Estimated Effort**: ~2h
- **Description**: Jira comment posting runs synchronously in `reporter_node`, blocking cleanup when the Jira API is slow or rate-limited. Fix: post the Jira comment as a fire-and-forget async task with 1 retry on failure.
- **Acceptance Criteria**:
  - AC-1: Jira comment posting is dispatched as an async background task.
  - AC-2: The reporter node does not await the Jira comment task before completing other cleanup steps.
  - AC-3: If the first Jira POST fails, one retry is attempted after a 2-second delay.
  - AC-4: Both the initial post and retry outcomes are logged at INFO/WARN level.
- **Key Files**:
  - `backend/engine/reporter.py` — Jira comment dispatch
  - `backend/jira/client.py` — comment posting method
- **Linked Tasks**: None
- **Branch**: feature/FEAT-093-async-jira-comment
- **Created**: 2026-06-03
