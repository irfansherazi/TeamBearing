---
name: "Learned: Memory Bank Syncing"
globs: ["memory-bank/tasks/*.md", "memory-bank/progress.md", ".agent/workflows/vc-build.md"]
topics: ["state-management", "git-workflow", "memory-bank", "documentation-sync"]
priority: high
evidence_count: 1
last_updated: 2026-05-15
auto_generated: true
derived_from: []
last_validated: 2026-07-22
---


# Memory Bank Syncing

- **immediate-documentation-sync**: To prevent desyncs caused by agent crashes or interruptions, ALWAYS update the `memory-bank/tasks/[task_id].md` checkboxes (`[x]`) and header `**Status**` immediately when a phase's code is written and verified, rather than waiting for the final Step 10/11 git completion. This guarantees that if a timeout occurs, the progress is persistently recorded in the documentation.
- **sync-memory-bank-to-main**: When updating files inside the `memory-bank/` directory during a `/vc-*` workflow on a feature branch, the agent should prioritize syncing these changes to the `main` branch. The memory bank operates as a global context system, and holding memory-bank updates hostage inside unmerged feature branches leads to stale context. You must ensure memory-bank changes are committed and propagated independently or via direct updates to the main worktree.

## Evidence

| Learning | Source | Date |
|----------|--------|------|
| Immediate state persistence and cross-branch sync | User Correction (TASK-021) | 2026-05-15 |
