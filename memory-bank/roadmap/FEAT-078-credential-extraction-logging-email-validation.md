---
legacy_id: FEAT-078
version: v1.0.0-prod-readiness
linked_tasks: []
status: planned
---

### FEAT-078: Credential Extraction Logging & Email Validation
- **Version**: v1.0.0-prod-readiness
- **Status**: planned
- **Priority**: low
- **Complexity**: Level 1
- **Pillar**: P1 — Jira Ingestion
- **Gap ID**: P1-D
- **Estimated Effort**: <1h
- **Description**: Credential extraction from Jira ticket descriptions currently has no logging and no email format validation, causing silent fallback to wrong KB credentials when extracted values are malformed. Fix: add structured logging at the extraction point and validate extracted email strings against a basic RFC 5322 regex before accepting them.
- **Acceptance Criteria**:
  - AC-1: Every credential extraction attempt logs the candidate string, the validation outcome (valid/invalid/no-match), and which credential set was ultimately used.
  - AC-2: Extracted email values are validated against `^[^@\s]+@[^@\s]+\.[^@\s]+$` before being accepted; invalid values trigger a fallback and a WARN log entry.
  - AC-3: No silent fallbacks — all fallback paths emit a log entry at WARN level.
- **Key Files**:
  - `backend/jira/client.py` — credential extraction logic
- **Linked Tasks**: None
- **Branch**: feature/FEAT-078-credential-extraction-logging
- **Created**: 2026-06-03
