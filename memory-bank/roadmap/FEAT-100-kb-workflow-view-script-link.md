---
legacy_id: FEAT-100
version: v1.0.0-prod-readiness
linked_tasks: [production-readiness-kb-workflows-hitl-reminder-sales-exec-c, production-readiness-kb-workflows-hitl-reminder-sales-exec-c]
status: complete
---

### FEAT-100: KB Workflow — View Script Link
- **Version**: v1.0.0-prod-readiness
- **Status**: complete ✅
- **Priority**: high
- **Complexity**: Level 1
- **Pillar**: P1 — Knowledge Base Coverage
- **Jira**: QA-100
- **Description**: Add a structured KB workflow entry to `knowledge/vSuite-actions.md` (or `human_guidance.md`) documenting how to locate a spot with a raw script in the Files column of the Production Orders table. The "View Script" link appears alongside "Add Voice", "Add Music", "Upload File" etc. in that column. The workflow must document navigation steps, selector strategy (`get_by_text("View Script", use_first=True)`), and post-click behaviour (slide-out panel with raw script copy; "Send Script to library" link inside the panel).
- **Acceptance Criteria**:
  - AC-1: A `## WORKFLOW: Locate a spot with a raw script in the Files column` section exists in the target KB file with KEYWORDS, JIRA, NAVIGATION, SELECTOR, and post-click notes.
  - AC-2: KEYWORDS include: locate, spot, raw, script, view, files, column, link.
  - AC-3: NAVIGATION documents: Production Orders page → Files column → scroll if needed → click "View Script".
  - AC-4: SELECTOR section specifies `strategy: get_by_text`, `name: "View Script"`, `use_first: true` with a CRITICAL note about multiple rows.
  - AC-5: Post-click behaviour is documented: slide-out panel shows raw script copy; "Send Script to library" only appears when copy exists.
- **Key Files**:
  - `knowledge/vSuite-actions.md`
  - `knowledge/human_guidance.md`
- **Linked Tasks**: [production-readiness-kb-workflows-hitl-reminder-sales-exec-c](tasks/production-readiness-kb-workflows-hitl-reminder-sales-exec-c.md)
- **Branch**: feature/FEAT-100-kb-view-script-workflow
- **Created**: 2026-06-03
