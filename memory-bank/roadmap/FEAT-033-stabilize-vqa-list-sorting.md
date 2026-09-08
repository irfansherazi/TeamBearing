---
legacy_id: FEAT-033
version: next
linked_tasks: [TASK-023]
status: planned
---

### FEAT-033: Stabilize VQA List Sorting
- **Version**: next
- **Status**: planned
- **Priority**: high
- **Complexity**: Level 2
- **Description**: Resolve strict mode locator violations and option mismatches in the sorting dropdown to ensure VQA tests pass without human intervention. Implement deterministic UI sorting behaviors with the following requirements. For List view: Client name (A-Z, Z-A), Due Date (closest to older, oldest to newest), Days (least to most, most to least), Submitted on (most recent to oldest, oldest to most recent), Start Date (closest to older, oldest to newest), End Date (closest to older, oldest to newest), Status & Approvals (A-Z, Z-A). For Compact view: Client name (A-Z, Z-A), Title (A-Z, Z-A), Status & Approvals (A-Z, Z-A), Due Date (closest to older, oldest to newest), Submitted on (most recent to oldest, oldest to most recent). Note: Ad type in compact view is intentionally excluded due to an existing bug card.
- **Linked Tasks**: TASK-023
- **Branch**: feature/FEAT-033-stabilize-vqa-list-sorting
- **Created**: 2026-05-15
