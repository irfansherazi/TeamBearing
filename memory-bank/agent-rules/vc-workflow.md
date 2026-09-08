---
name: VC Workflow Enforcement
priority: critical
globs: ["**/*"]
---

# VC Workflow Enforcement

## Context
This rule was established after the agent failed to follow the VC workflow for a `/vc-task` command, jumping straight to implementation without proper initialization in the Memory Bank.

## Rules

- **strict-vc-command-adherence**: Any command starting with `/vc-` MUST be treated as a direct invocation of the corresponding workflow in `${CLAUDE_PLUGIN_ROOT}/commands/`.
- **workflow-initialization**: Every `/vc-task` command MUST result in:
  1.  Updating `memory-bank/tasks.md` with the new task.
  2.  Creating a corresponding task file in `memory-bank/tasks/TASK-XXX.md`.
  3.  Defining clear Acceptance Criteria (AC) in that file.
  4.  Obtaining user confirmation on the AC before starting any implementation.
- **phase-discipline**: NEVER skip phases (PLAN -> BUILD -> REFLECT -> ARCHIVE). Even for "simple" or "surgical" changes, the documentation and review steps are mandatory.
- **memory-bank-sync**: The Memory Bank MUST be updated at each phase gate. If the implementation changes the roadmap or active tasks, those files MUST be updated immediately.
- **check-for-vc-workflow**: At the start of every turn where a `/vc-` command is active, verify that the current action aligns with the next step of the prescribed workflow.

## Verification
- Before submitting any implementation, verify that `memory-bank/tasks.md` and `memory-bank/progress.md` reflect the current state of the work.
