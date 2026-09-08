---
legacy_id: FEAT-025
version: v2.1.0
linked_tasks: [aria-tree-pruning]
status: complete
---

### FEAT-025: ARIA Tree Pruning
- **Version**: v2.1.0
- **Status**: complete
- **Priority**: high
- **Complexity**: Level 3
- **Description**: Filter the ARIA accessibility tree to only include elements relevant to the current AC step's target element types before injecting it into the planner prompt (FM-6). Uses the `target_element_types` output from the AC enrichment engine to prune irrelevant elements. Reduces prompt size from 15K→3K tokens on dense pages (production orders table with 50+ rows). Design decisions needed on pruning algorithm (role-based filter vs. viewport-based crop vs. hybrid). Touches planner prompt assembly and AC enrichment output integration.
- **Linked Tasks**: aria-tree-pruning (COMPLETE)
- **Branch**: feature/FEAT-025-aria-tree-pruning
- **Created**: 2026-05-11
- **Completed**: 2026-05-12
