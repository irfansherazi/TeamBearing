---
legacy_id: FEAT-095
version: v1.0.0-prod-readiness
linked_tasks: []
status: planned
---

### FEAT-095: S3 Report URL in Jira Comment
- **Version**: v1.0.0-prod-readiness
- **Status**: planned
- **Priority**: medium
- **Complexity**: Level 1
- **Pillar**: P5 — Traceability & Reporting
- **Gap ID**: P5-D
- **Estimated Effort**: <30min
- **Description**: The S3 report URL is not included in the Jira comment posted after a run, preventing operators from clicking through to the full audit report. Fix: append the S3 presigned URL for the HTML audit report to the Jira comment body.
- **Acceptance Criteria**:
  - AC-1: The Jira comment posted after a run includes the S3 report URL as a clickable link.
  - AC-2: If the S3 upload failed or is disabled, the comment omits the link without error.
  - AC-3: The URL format is: `📊 [Full Audit Report](${s3_report_url})`.
- **Key Files**:
  - `backend/engine/reporter.py` — Jira comment template
  - `backend/jira/client.py` — comment formatter
- **Linked Tasks**: None
- **Branch**: feature/FEAT-095-s3-url-jira-comment
- **Created**: 2026-06-03
