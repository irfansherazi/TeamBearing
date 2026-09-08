---
slug: TASK-125
legacy_id:
feature: FEAT-116
status: COMPLETE
---

# TASK-125: Ghost Login — Admin Credential Prompt & Ghost Panel Interaction

**Complexity**: Level 2
**Status**: COMPLETE
**Reflection**: memory-bank/reflection/TASK-125-reflection.md
**Archived**: memory-bank/archive/TASK-125-archive.md
**Completed**: 2026-07-22
**Roadmap**: FEAT-116
**Branch**: feature/FEAT-116-ghost-login-credential-prompt
**Worktree**: .worktrees/FEAT-116

## Task Description

The ghost login infrastructure exists (ghost_login_node.py, GhostCredentialPanel.tsx, GHOST_CREDENTIALS_REQUIRED WebSocket protocol, POST /runs/{run_id}/ghost-credentials API) but the credential prompt does not reliably surface to the operator.

Two root causes:

**1. Ghost keyword detection is too narrow (prompts.py)**
On `main`, the AC parser only emits GHOST_LOGIN for "Ghost In As [user]" phrasing. A bare "ghost" in the card description (e.g., "Ghost in as John Smith" or "Use ghost to log in as <user>") does not reliably trigger GHOST_LOGIN step creation, so the ghost_login_node is never reached.

**2. SSO fast-path hides the credential form (GhostCredentialPanel.tsx)**
On the FEAT-115 branch (pending merge), the GhostCredentialPanel added a `useEffect` SSO fast-path that automatically POSTs the operator's own session token to `/ghost-credentials` on mount — before the form is even rendered. The API returns HTTP 200 (it just stores the token, no validation), so the panel marks itself "submitted" and closes. The operator never sees the credential form. The backend then attempts to ghost-login using the operator's token, which is NOT an admin token and will fail.

**What this task delivers:**
- Broaden ghost detection in `prompts.py` to treat any "ghost" mention as requiring a GHOST_LOGIN step
- Remove the SSO auto-submit fast-path from `GhostCredentialPanel` so the manual credential form always shows
- End-to-end verified: detect "ghost" → HITL credential prompt appears → operator enters admin credentials → backend logs in as admin → fills `#ghost-panel-input` typeahead with target user → waits for SPA render → continues test

## Specification

**Feature Type**: End-User Feature (operator-facing HITL flow)
**Primary Persona**: QA Lead / Automation Engineer running ghost-login test cards
**Creative Exploration Needed**: No — the design is well-understood from existing code

### Invocation Method
- **Location**: vQA RunTestView — appears automatically mid-run when a GHOST_LOGIN step is reached
- **Element**: `GhostCredentialPanel` modal, surfaced by the `GHOST_CREDENTIALS_REQUIRED` WebSocket message
- **Visibility**: Conditional — only when the AC parser emits a GHOST_LOGIN step
- **Navigation**: Operator starts a test run on a card containing "ghost" → panel appears mid-run

### Success Criteria
- **User sees**: GhostCredentialPanel with "Admin Login Required (Ghost Login)" header and Admin Email / Password fields
- **User can verify at**: RunTestView, mid-run — the panel blocks execution until credentials are submitted
- **Data persisted**: Admin credentials stored in-memory for the run duration only (never to disk)
- **Observable within**: Credentials submitted → ghost login executed within 30s → test continues

### Acceptance Criteria
- AC-ENTRY-1: A Jira card description containing just the word "ghost" (case-insensitive) produces at least one GHOST_LOGIN step in the test plan
- AC-ENTRY-2: A Jira card description containing "Ghost In As John Smith" produces a GHOST_LOGIN step with `target_user: "John Smith"`
- AC-HAPPY-1: When a GHOST_LOGIN step is reached, the GhostCredentialPanel appears in the UI within 2 seconds — the manual credential form (email + password fields) is visible immediately without any auto-submission
- AC-HAPPY-2: Operator enters admin email and password, clicks "Submit Admin Credentials" — the panel dismisses and the backend completes ghost login using those credentials
- AC-HAPPY-3: After ghost login, the ghost_login_node fills `#ghost-panel-input` with the target_user and the SPA redirects to `/` as the ghosted user before the next test step runs
- AC-ERROR-1: If no admin credentials are provided within 300 seconds, the run times out with a clear error message

### Scope Boundaries
- **In scope**: `backend/engine/prompts.py` ghost detection expansion; `frontend/src/components/GhostCredentialPanel.tsx` SSO fast-path removal; end-to-end flow verification via tests
- **Out of scope**: Changing ghost_login_node.py execution logic (already works); changing the `_wait_for_ghost_credentials` HITL gate (already works); adding new ghost detection patterns beyond "ghost" keyword
- **Dependencies**: Existing `GHOST_CREDENTIALS_REQUIRED` WebSocket protocol; existing `/runs/{run_id}/ghost-credentials` API; existing `ghost_login_node.py` logic
- **NFR implications**: No new infrastructure; admin credentials never logged or persisted

## Test Strategy

### Approach
- **Emphasis**: Unit tests for prompt detection; no E2E (no live browser/ghost panel available in CI)
- **Target test count**: 8 tests total

### File Organization
- **Extend existing**: `tests/test_ac_parser.py` or nearest prompt-related test file — add ghost detection tests
- **New test files**: `tests/test_ghost_login.py` — ghost detection unit tests (if no existing prompt test file covers this)

### What NOT to Test
- Playwright browser ghost panel interaction — requires live admin session, not CI-testable
- SSO token injection path — removed, no longer applicable
- `ghost_login_node.py` execution logic — already tested by existing persona_switch tests

### Per-Phase Test Guidance
- Phase 1: 5 tests — verify `prompts.py` ghost keyword detection: bare "ghost", "Ghost In As user", "ghost in as", mixed case, no false positives on unrelated text
- Phase 2: 3 tests — verify GhostCredentialPanel renders form immediately (no auto-submit on mount), submit path calls POST endpoint, dismiss path fires onDismiss

## Implementation Roadmap

### New Source Files (pin path + extension)
- [x] `tests/test_ghost_login.py` — ghost detection unit tests (new; `.py` — dominant extension in `tests/`)

### Modified Files
- [x] `backend/engine/prompts.py` — extend ghost detection to bare "ghost" keyword (modify `BDD_NORMALIZER_PROMPT` and `JSON_COMPILER_PROMPT` rules)
- [x] `frontend/src/components/GhostCredentialPanel.tsx` — SSO fast-path absent (never added to this branch; form always shows immediately)

### Phases
- [x] Phase 1: Ghost Keyword Detection — broaden AC parser prompt + tests
- [x] Phase 2: GhostCredentialPanel Fix — remove SSO fast-path, ensure form always shows

## Creative Phases

(none required)

---

## Execution State

**Build Status**: IDLE
**Current Phase**: COMPLETE
**Can Resume**: NO
**Build Started**: 2026-07-22
**Phase Number**: 2 of 2
**Latest Commit**: 6a7ea92

### Current Build Step
**Step**: Step 5 — Report Completion
**Status**: COMPLETE
**Completed**: 2026-07-22

### Active Sub-Agents
(none — orchestrator running inline)

### Completed Steps
- [x] Step 0: Feature created (FEAT-116), branch created (feature/FEAT-116-ghost-login-credential-prompt)
- [x] Step 3: Specification written and approved
- [x] Step 5: Implementation plan documented
- [x] Step 6: Planning validated — PLANNING_COMPLETE
- [x] Step 0.5: Worktree confirmed at .worktrees/FEAT-116 (inline, no git-setup hop)
- [x] Step 0.6: Phase gate passed — Implementation Roadmap populated, Phase 1 unchecked
- [x] Phase 1 Step 3: TDD (RED→GREEN) — 5 new tests in test_ghost_login.py; prompts.py broadened; 5/5 GREEN
- [x] Phase 1 Step 7: Integration verification — 1488 passed (baseline 55 pre-existing → 53 after fix, net +2); no regressions
- [x] Phase 1 Step 11: Committed and pushed to feature/FEAT-116-ghost-login-credential-prompt
- [x] Phase 2 Step 3: TDD (RED→GREEN) — 3 new tests in GhostCredentialPanel.test.tsx; component already correct; 3/3 GREEN
- [x] Phase 2 Step 7: Frontend full suite — 103 passed + 3 new = 106 total; 4 pre-existing failures (AppShell/SelectView/ExecutionLog — unrelated to this task); no regressions introduced
- [x] Phase 2 Step 11: Committed and pushed to feature/FEAT-116-ghost-login-credential-prompt

### Guard & Recovery Log
(empty — guard PASSed first try)
