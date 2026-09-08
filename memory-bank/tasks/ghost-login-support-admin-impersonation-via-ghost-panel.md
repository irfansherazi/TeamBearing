---
legacy_id: ghost-login-support-admin-impersonation-via-ghost-panel
---
# ghost-login-support-admin-impersonation-via-ghost-panel: Ghost Login Support — Admin Impersonation via Ghost Panel

**Complexity**: Level 3
**Status**: COMPLETE
**Jira Issue**: N/A
**Issue Type**: Feature
**Priority**: High
**Branch**: task/ghost-login-support-admin-impersonation-via-ghost-panel-ghost-login-support
**Worktree**: N/A
**Roadmap**: N/A

---

## Task Description

vQA currently cannot execute Jira cards that require "Ghost In As" / admin impersonation. Ghost login is a **hard requirement** on roughly 12+ Jira cards (QA-340, QA-279, QA-260, QA-268, QA-100, and others) — making them effectively unrunnable today.

### How Ghost Login Works in vSuite

1. The operator logs in as an **Admin user** (real credentials, not a demo account).
2. Once logged in, the Admin navigates to the ghost panel via the vSuite Admin UI.
3. The ghost panel exposes a text input: `id="ghost-panel-input"` where the admin types the target user's name or email.
4. After submitting, the browser session is now operating as the target user.

### Why This Feature Is Needed

Any Jira card that contains the phrase **"Ghost In As"** requires:
- A real Admin account login (the operator's own credentials)
- The ghost-panel impersonation interaction (`id="ghost-panel-input"`)

This is a **hard requirement** — vQA must have an Admin credential supplied at run time. If no Admin creds are provided and a `GHOST_LOGIN` step is encountered, vQA must pause and request them (HITL gate), not silently skip or fail.

### Credential Security Model

- Admin credentials are **never stored** in the role registry, `.env`, or disk
- They are **supplied at run time** by the operator (same ephemeral pattern as HITL persona creds in `persona_switch_node.py`)
- The AC Quality Gate should detect "Ghost In As" in the card text and emit a **pre-run warning** requesting Admin credentials before execution starts
- Credentials are purged on run completion (reuse `clear_run_creds` pattern)

---

## Acceptance Criteria

- **AC-HAPPY-1**: When a Jira card contains "Ghost In As [user]", the AC parser emits a `GHOST_LOGIN` step type with `target_user` field populated from the card text.
- **AC-HAPPY-2**: Before execution begins, if any `GHOST_LOGIN` step is present in the test plan, vQA broadcasts a `GHOST_CREDENTIALS_REQUIRED` WebSocket event and pauses at a HITL gate waiting for admin credentials.
- **AC-HAPPY-3**: When Admin credentials are supplied via the frontend credential form (email + password), vQA logs in as the Admin user first, then executes the ghost panel interaction (`id="ghost-panel-input"`) to impersonate the target user.
- **AC-HAPPY-4**: After ghosting, the browser session operates as the target user and execution continues with the next step.
- **AC-HAPPY-5**: The ghost action is recorded in `persona_switch_history` (or equivalent) with `method="ghost"` for the audit report.
- **AC-HAPPY-6**: If Admin credentials are NOT provided within the HITL timeout (5 min), the run is marked `FATAL` with a clear error message: `"GHOST_LOGIN step requires admin credentials — none provided."`.
- **AC-ERROR-1**: If `id="ghost-panel-input"` is not found after admin login, vQA escalates to `human_takeover_node` rather than silently failing.
- **AC-REGRESS-1**: Existing `PERSONA_SWITCH` flow is unchanged — ghost login is an additive new step type.
- **AC-REGRESS-2**: No regressions in `tests/test_persona_switch*.py` (if exists) or any existing role-switching tests.
- **AC-REGRESS-3**: The AC Quality Gate FAIR/POOR guardrail still fires correctly for unrelated cards.

---

## Open Questions

- [x] (Resolved) **Where does the Admin navigate to access the ghost panel?** When logged in as an admin, the ghost panel search input is in the very top bar. vQA can find it using the `id="ghost-panel-input"` selector, so no special navigation is required.
- [x] (Resolved) **Is `id="ghost-panel-input"` the only stable selector, or is there also an `aria-label` or role-based selector we can use?** We will use the stable semantic `id="ghost-panel-input"` selector.
- [x] (Resolved) **Does ghosting navigate away from the Admin dashboard, or does it open in-place?** After submitting, it redirects to the root page (`/`).
- [x] (Resolved) **Should vQA request Admin credentials at the START of a run or lazily when the GHOST_LOGIN step is reached?** Pre-flight strict blocking. Before execution begins, if any `GHOST_LOGIN` step is present in the test plan and no admin credentials have been provided, vQA blocks the start of the execution entirely and requests them.
- [x] (Resolved) **Should the Admin role be added to ROLE_REGISTRY as a special `admin` key with env-var credential support?** No, HITL only. Admin credentials must be supplied dynamically at run time and are never pre-configured in `.env` or stored on disk.

---

## Affected Components

- `backend/engine/schemas.py` — Add `GHOST_LOGIN` to `StepType` enum and schema definition
- `backend/engine/ac_parser.py` — Detect "Ghost In As" phrase → emit `GHOST_LOGIN` step with `target_user`
- `backend/engine/persona_switch_node.py` — Add `GHOST_LOGIN` branch (or create `ghost_login_node.py`)
- `backend/engine/evaluator.py` — Route `GHOST_LOGIN` step type to the ghost handler (same pattern as `PERSONA_SWITCH`)
- `backend/engine/graph.py` — Wire new node if created separately
- `backend/engine/prompts.py` — Add GHOST_LOGIN to AC parser prompt instructions
- `backend/engine/ac_quality_gate.py` — Add pre-run detection: if "Ghost In As" in AC text, emit `GHOST_CREDENTIALS_REQUIRED` warning
- `backend/api/routes.py` — Add `POST /runs/{run_id}/ghost-credentials` endpoint (mirrors `/persona-credentials`)
- `knowledge/vSuite-actions.md` — Document ghost panel blueprint
- `knowledge/blueprints/ghost_login.yaml` — New blueprint recipe for the ghost panel interaction
- `frontend/src/` — Add Admin credentials input UI (mirrors existing HITL persona credential form)

---

## Test Strategy

### Approach
- **Emphasis**: Unit-heavy for parser detection + integration for ghost node
- **Target test count**: 6–8 unit tests

### Test Targets
- `ac_parser.py`: "Ghost In As Kat Morgan Gaines" → `GHOST_LOGIN` step with `target_user="Kat Morgan Gaines"`
- `ac_parser.py`: Cards without "Ghost In As" produce NO `GHOST_LOGIN` steps
- `ghost_login_node` (or `persona_switch_node`): `GHOST_LOGIN` with no admin creds → HITL gate triggered
- `ghost_login_node`: `GHOST_LOGIN` with creds supplied → `_login_with_ephemeral_creds` + ghost panel recipe called
- `ac_quality_gate.py`: Card with "Ghost In As" surfaces a pre-run HITL warning
- `schemas.py`: `GHOST_LOGIN` step validates correctly including `target_user` field

### What NOT to Test
- Live Playwright interaction with real vSuite admin panel (requires live env)
- The actual ghosting UI behavior (covered by UAT)

---

## Implementation Roadmap

- [x] Phase 1: Schema & Parser — Add `GHOST_LOGIN` step type + AC parser detection
- [x] Phase 2: Ghost Node — Implement ghost login logic (admin login → ghost panel → impersonate)
- [x] Phase 3: Evaluator & Graph — Route `GHOST_LOGIN` steps through the graph
- [x] Phase 4: API Endpoint — `POST /runs/{run_id}/ghost-credentials`
- [x] Phase 5: Frontend — Admin credential HITL UI
- [x] Phase 6: Blueprint YAML — `ghost_login.yaml` recipe
- [x] Phase 7: Quality Gate — Pre-run "Ghost In As" detection warning
- [x] Phase 8: Tests + Docs

---

## Execution State

**Build Status**: SUCCESS
**Last Completed**: 2026-06-03T18:00:00-05:00
**Can Resume**: NO

### Active Sub-Agents
(none)

### Completed Steps
- Phase 1: Added GHOST_LOGIN step type to StructuredACStep, updated schema pydantic models and tests.
- Phase 2: Implemented ghost_login_node LangGraph node logic with comprehensive happy path and error/escalation handling.
- Phase 3: Integrated routing for GHOST_LOGIN in evaluator and registered ghost_login node in StateGraph.
- Phase 4: Added POST /runs/{run_id}/ghost-credentials endpoint with secure, ephemeral, in-memory credential storage and websocket broadcasts.
- Phase 5: Created React GhostCredentialPanel component to render polished, functional HITL prompt for Admin credentials.
- Phase 6: Authored interaction blueprint recipe ghost_login.yaml to document CSS and input press parameters.
- Phase 7: Retooled Quality Gate to detect "Ghost In As" in card text and emit pre-run warning.
- Phase 8: Wrote complete, highly-cohesive test suites verifying schema, parser prompts, graph node execution, and REST API functionality.
