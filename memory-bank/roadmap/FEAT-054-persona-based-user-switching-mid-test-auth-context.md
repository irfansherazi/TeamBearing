---
legacy_id: FEAT-054
version: next
linked_tasks: [persona-based-user-switching-mid-test-auth-context-switching]
status: planned
---

### FEAT-054: Persona-Based User Switching — Mid-Test Auth Context Switching
- **Version**: next
- **Status**: planned
- **Priority**: high
- **Complexity**: Level 4
- **Description**: Enable vQA to detect and act on persona-switching language in Jira cards (e.g. "as yourself", "as Demo Prod dir", "as Mike Prodir") and correctly log out of the current user and log in as the specified persona before continuing test execution. This can occur multiple times within a single card. Key requirements:
    1. **PARSER / AC INTERPRETER**: Detect persona-switching directives in Jira AC text and step descriptions using a combination of keyword patterns ("as yourself", "as [Name]", "as [Role]") and NLP normalization. Emit a structured `persona_switch` AC step type with a `target_persona` field (e.g. `{ type: "persona_switch", target_persona: "Demo Prod dir" }`). Handle case-insensitive matching and common aliases.
    2. **PERSONA CREDENTIAL STORE**: Maintain a persona registry that maps role/name strings to login credentials (username + password). Primary lookup: match against the vQA User Role dropdown (existing user list). Fallback: prompt the operator via HITL if the persona is unknown or credentials are not stored. Credentials must be stored securely (encrypted at rest, never logged).
    3. **AUTH SWITCHING EXECUTOR**: Implement a `persona_switch` action handler in the executor that: (a) saves any in-progress state; (b) logs out of the current session (clears cookies/storage state, navigates to logout endpoint); (c) logs in as the target persona using stored credentials; (d) waits for successful authentication confirmation; (e) resumes the test from the next AC step. The entire switch must be transparent to the downstream evaluator — post-switch the agent continues as if it always was the new user.
    4. **HITL CREDENTIAL PROMPT**: When the target persona is unrecognized or credentials are absent, pause execution and surface a structured HITL prompt to the operator: display the persona name, ask for username/password, optionally offer to save for future runs. After credentials are entered, retry the auth switch and continue.
    5. **AUDIT REPORT**: Persona switches are surfaced as distinct steps in the HTML audit report with a 🔄 icon, showing: previous persona, new persona, switch timestamp, and whether credentials were retrieved from store vs. entered via HITL.
    6. **MULTI-SWITCH SUPPORT**: A single Jira card may contain N persona switches in sequence. The executor must handle chained switches without state corruption, correctly restoring each persona's session context. VQAState must track `current_persona` and `persona_switch_history`.
- **Linked Tasks**: persona-based-user-switching-mid-test-auth-context-switching
- **Branch**: feature/FEAT-054-persona-user-switching
- **Created**: 2026-05-28
