---
legacy_id: FEAT-103
version: v1.0.0-prod-readiness
linked_tasks: [production-readiness-kb-workflows-hitl-reminder-sales-exec-c, production-readiness-kb-workflows-hitl-reminder-sales-exec-c]
status: complete
---

### FEAT-103: Verify Sales Exec Credentials in .env
- **Version**: v1.0.0-prod-readiness
- **Status**: complete ✅
- **Priority**: high
- **Complexity**: Level 1
- **Pillar**: P5 — Credential & Auth Management
- **Description**: Before multi-persona test runs (AC steps covering Sales Exec role), confirm that Sales Exec credentials exist in `.env` under the ghost-login / role-switching mechanism. Run `grep -i "sales.exec|salesexec|sales_exec" .env` to verify. If missing, document the required env var names and add placeholder values with instructions for the operator to fill in real credentials.
- **Acceptance Criteria**:
  - AC-1: `.env` contains at least one credential entry matching `SALES_EXEC_EMAIL` or equivalent pattern (case-insensitive).
  - AC-2: If credentials are absent, add commented placeholder entries with clear instructions (e.g., `# SALES_EXEC_EMAIL=sales@example.com`).
  - AC-3: `backend/engine/credential_manager.py` (or equivalent) correctly reads the Sales Exec credential from `.env` and injects it during role-switching.
  - AC-4: A verification command is documented in `memory-bank/runbook.md` (or equivalent) so operators can confirm credentials before a multi-persona run.
- **Key Files**:
  - `.env`
  - `backend/engine/credential_manager.py`
- **Linked Tasks**: [production-readiness-kb-workflows-hitl-reminder-sales-exec-c](tasks/production-readiness-kb-workflows-hitl-reminder-sales-exec-c.md)
- **Branch**: feature/FEAT-103-sales-exec-credentials
- **Created**: 2026-06-03
