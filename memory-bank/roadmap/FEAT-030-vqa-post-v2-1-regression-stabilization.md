---
legacy_id: FEAT-030
version: next
linked_tasks: [vqa-post-v2-1-regression-stabilization]
status: complete
---

### FEAT-030: vQA Post-v2.1 Regression Stabilization
- **Version**: next
- **Status**: complete
- **Priority**: high
- **Complexity**: Level 4
- **Description**: vQA is unstable after rapid delivery of FEAT-020 through FEAT-027. Five interacting bugs: (1) FEAT-026 Proactive Overlay Dismissal dismisses dropdowns the planner just opened, (2) Missing List View navigation recipe causing infinite loops, (3) Planner hallucinating dropdown option names, (4) Jira AC sync API broken on customfield_10031, (5) Prompt budget dropping critical context during retries. Commit 5cee18f was last stable baseline.
- **Linked Tasks**: vqa-post-v2-1-regression-stabilization
- **Branch**: feature/FEAT-030-vqa-regression-stabilization
- **Created**: 2026-05-12
- **Completed**: 2026-05-15
