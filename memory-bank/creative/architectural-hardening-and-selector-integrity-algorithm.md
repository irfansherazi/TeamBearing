# Creative Design: architectural-hardening-and-selector-integrity Algorithm — Selector Integrity Guardrails

## Problem Statement
The planner occasionally ignores system prompt rules and generates fragile selectors (dynamic IDs or deep-DOM chains), especially when under "pressure" (multiple retries). We need a more robust way to enforce selector standards.

## Proposed Algorithm: Option A — Prompt-Based Negative Constraints (Selected)

### 1. Refined Rule 17 (Prompt Injection)
Strengthen the language in `_CORE_RULES` to use high-signal "BAN" and "MANDATE" keywords.

```markdown
17. **SELECTOR INTEGRITY (CRITICAL)**:
    a) ⛔ BAN DYNAMIC IDs: NEVER use `ui-tabpanel-\d+`, `p-overlay-\d+`, or similar dynamic patterns.
    b) ⛔ BAN DEEP-DOM: NEVER use `nth-child`, `nth-of-type`, or > chains longer than 2 levels.
    c) ✅ MANDATE SEMANTIC: Use `getByRole`, `getByText`, `getByLabel` exclusively.
    d) ✅ MANDATE STABLE: Use `vqa_id` attributes if they exist in the accessibility tree.
```

### 2. Post-Generation Validation (Self-Correction)
Enhance `_invoke_planner_with_tools` to validate the generated `PlannerAction`.
- If a selector violates Rule 17 (e.g., regex check for `\d+` in ID or `nth-child` in CSS), the planner should self-correct by appending a specific "Selector Violation" error to the message history and retrying.

## Alternative: Option B — Hard Mechanical Gate
Implement a regex filter in the `executor_node` that fails any action with a "forbidden" selector before it even touches the browser.
- **Pros**: 100% enforcement.
- **Cons**: Can lead to "execution deadlocks" if the LLM cannot figure out a valid selector after several tries.

## Decision: Option A
Prompt-based constraints with a "validation + retry" loop in the planner is the most flexible approach. It allows the LLM to learn from its specific mistake in the same turn.

## Implementation Details
- Add `validate_selector_integrity(action: PlannerAction) -> str | None` in `backend/engine/validators.py`.
- Call this validator in `_invoke_planner_with_tools` alongside existing Pydantic validation.
