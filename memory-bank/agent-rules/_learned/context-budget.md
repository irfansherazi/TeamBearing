---
name: Context Budget Patterns
globs: ["backend/engine/verifier.py", "backend/engine/planner.py"]
paths: ["backend/engine/"]
topics: ["context-budget", "prompt-assembly", "failure-diary"]
priority: high
auto_generated: true
evidence_count: 1
last_reinforced: 2026-05-15
source_tasks: ["TASK-025"]
derived_from: []
last_validated: 2026-07-22
---


# Context Budget Patterns

Rules for keeping prompt context lean and preventing "lost-in-the-middle" degradation during long agent sessions.

## Rules

- **context-budget** (`backend/engine/verifier.py`): Never inline large computed artifacts (DOM snapshots, full page XML, screenshots-as-text) into failure diary error strings. Use a lightweight reference instead — e.g., `DOM state: (see <page_state> at top of prompt)`. The artifact is already present in the planner's master directive; repeating it per retry creates O(n·k) context bloat where n = retry count and k = artifact size.
  - _Source_: reflection-TASK-025 (2026-05-15)
  - _Reinforced_: 1x

- **context-budget** (`backend/engine/planner.py`): Keep a single authoritative location for each large prompt artifact (e.g., `<page_state>`, `<selector_rules>`). Downstream components (verifier, evaluator) that reference these artifacts should use reference strings, not copies. This enforces a single-source-of-truth for context-heavy data and bounds prompt size growth.
  - _Source_: reflection-TASK-025 (2026-05-15)
  - _Reinforced_: 1x
