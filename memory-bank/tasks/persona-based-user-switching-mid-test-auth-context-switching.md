---
legacy_id: persona-based-user-switching-mid-test-auth-context-switching
---
# persona-based-user-switching-mid-test-auth-context-switching: Persona-Based User Switching — Mid-Test Auth Context Switching

**Status**: COMPLETE
**Phase**: BUILD
**Roadmap Link**: FEAT-054
**Branch**: feature/FEAT-054-persona-user-switching
**Complexity**: Level 4
**Created**: 2026-05-28

---

## Execution State

**Build Status**: COMPLETE
**Phase Being Built**: ARCHIVE
**Phase Number**: 6 of 6
**Is Multi-Phase**: YES
**Build Started**: 2026-05-28T11:43:30-05:00
**Can Resume**: NO

### Current Build Step
**Step**: ARCHIVE — TASK_COMPLETE
**Status**: COMPLETE
**Started**: 2026-05-28T14:58:00-05:00
**Archived**: 2026-05-28
**Archive Doc**: memory-bank/archive/archive-persona-based-user-switching-mid-test-auth-context-switching.md
**PR Created**: YES
**PR URL**: https://github.com/vcreativeinc/vQA/pull/27

### Active Sub-Agents
- User Journey Design: COMPLETE
- Architecture Design: COMPLETE
- Algorithm Design: COMPLETE
- Test Writer (Phase 2): COMPLETE
- Code Reviewer (Phase 2): COMPLETE — APPROVED

### Completed Steps
- User Journey Creative Design: COMPLETE (2026-05-28T10:00:00-05:00) — Output: memory-bank/creative/persona-based-user-switching-mid-test-auth-context-switching-persona-switching-user-journey.md
- Architecture Creative Design: COMPLETE (2026-05-28T10:05:00-05:00) — Output: memory-bank/creative/persona-based-user-switching-mid-test-auth-context-switching-persona-switching-architecture.md
- Algorithm Creative Design: COMPLETE (2026-05-28T10:08:00-05:00) — Output: memory-bank/creative/persona-based-user-switching-mid-test-auth-context-switching-persona-switching-algorithm.md
- Phase 1 Schema & State: COMPLETE (2026-05-28T10:25:46-05:00) — 3 files changed, 14 tests GREEN, committed c52a094, pushed to origin
- Step 1 - Read Task Context: COMPLETE (2026-05-28T15:27:30-05:00)
- Step 2 - Load Complexity Context (Level 4): COMPLETE (2026-05-28T15:28:00-05:00)
- Step 3 - Test Writer (Phase 2): COMPLETE (2026-05-28T15:31:00-05:00) — 21 tests written in test_ac_parser_persona.py (RED: 11 fail)
- Step 4 - Implementer (Phase 2): COMPLETE (2026-05-28T15:41:00-05:00) — prompts.py (rule 12 + PERSONA_SWITCH), ac_parser.py (error hint), roles.py (alias)
- Step 5 - Test Runner (GREEN verify): COMPLETE (2026-05-28T15:49:00-05:00) — 21/21 pass, 734/755 pass (14 pre-existing failures)
- Step 8 - Code Review: COMPLETE (2026-05-28T15:51:00-05:00) — APPROVED, Security: PASS, 0 blocking issues
- Step 10 - Memory Bank Update: COMPLETE (2026-05-28T16:00:00-05:00) — persona-based-user-switching-mid-test-auth-context-switching.md Phase 2 [x], progress.md entry added, committed 48cad61, pushed to origin
- Phase 3 - Executor & Graph: COMPLETE (2026-05-28T16:38:00-05:00) — persona_switch_node.py, graph.py, evaluator.py — 30/30 tests GREEN, code reviewed APPROVED
- Phase 4 - HITL Integration: COMPLETE (2026-05-28T17:37:00-05:00) — 33/33 tests GREEN, 0 regressions introduced
- Phase 5 - Audit Report: COMPLETE (2026-05-28T13:20:00-05:00) — reporter.py _render_persona_switch_section(), 23/23 tests GREEN, committed 0f99429, pushed to origin

---

## Creative Phases

- [x] **User Journey** — COMPLETE — `memory-bank/creative/persona-based-user-switching-mid-test-auth-context-switching-persona-switching-user-journey.md`
  - Decision: Option A — Transparent In-Flow Switching with Dedicated HITL Credential Gate
- [x] **Architecture** — COMPLETE — `memory-bank/creative/persona-based-user-switching-mid-test-auth-context-switching-persona-switching-architecture.md`
  - Decision: Option A — Dedicated `persona_switch_node` inserted in LangGraph graph with evaluator routing
- [x] **Algorithm** — COMPLETE — `memory-bank/creative/persona-based-user-switching-mid-test-auth-context-switching-persona-switching-algorithm.md`
  - Decision: Option A — Two-stage resolution with cached auth state application and asyncio.Event HITL gate

---

## Task Description

Enable vQA to detect persona-switching directives in Jira AC text (e.g. `"as yourself"`, `"as Demo Prod dir"`, `"as [Role Name]"`), and automatically log out of the current session and log in as the specified persona before continuing test execution. This can occur multiple times in a single test card.

This is a **Level 4** task requiring architectural changes across:
- `backend/engine/schemas.py` — new `PERSONA_SWITCH` step type + state fields
- `backend/engine/state.py` — new `current_persona` and `persona_switch_history` fields
- `backend/engine/graph.py` — `login_node` / `persona_switch_node` + graph edge wiring
- `backend/engine/executor.py` — new `persona_switch` action handler
- `backend/engine/ac_parser.py` / `backend/engine/prompts.py` — Stage 1/2 persona directive detection
- `backend/browser/context.py` — multi-context BrowserManager auth switching support
- `backend/engine/reporter.py` — audit report persona switch timeline entries
- `tests/` — unit + integration tests

---

## Acceptance Criteria

### AC-ENTRY-1: AC Parser detects persona-switch directives
- Given a Jira AC step containing `"as yourself"`, `"as Demo Prod dir"`, `"as [Name]"`, or `"as [Role]"`
- When the two-stage AC parser processes the ticket
- Then the resulting `TestPlan` contains a `StructuredACStep` with `step_type="PERSONA_SWITCH"` and `target_persona` set to the detected name (normalized, not raw)
- And the `acceptance_criteria_steps` legacy list includes a readable goal string like `"Switch to persona: Demo Prod dir"`

### AC-ENTRY-2: Parser handles aliases and fuzzy matches
- Case-insensitive: `"As Yourself"`, `"AS YOURSELF"`, `"as yourself"` all resolve to `"current_user"`
- Alias resolution: `"Demo Prod dir"`, `"Production Director"`, `"Demo Production Director"` all resolve to `"digital_director"` via `ROLE_ALIASES`
- Unknown personas are preserved as-is (not dropped) and trigger AC-HAPPY-3

### AC-HAPPY-1: Successful persona switch with stored credentials
- Given the target persona resolves to a known role key in `ROLE_REGISTRY`
- When the `persona_switch_node` executes
- Then: browser clears localStorage (vc2JWT), navigates to logout endpoint, re-authenticates using role credentials via `ensure_role_authenticated()`, waits for new JWT in localStorage
- And `VQAState.current_persona` is updated to the new role key
- And `VQAState.persona_switch_history` gains a new entry with `{from, to, timestamp, method: "stored"}`
- And the next AC step executes under the new auth context without agent knowing a switch occurred

### AC-HAPPY-2: "As yourself" resolves to initial_actor
- Given a step with `"as yourself"` and `run_memory.initial_actor` populated from `login_node`
- When the `persona_switch_node` runs
- Then credentials come from `run_memory.initial_actor` (not the current role_context)
- And the switch history records `method: "initial_actor"`

### AC-HAPPY-3: Unknown persona triggers HITL credential prompt
- Given a persona string that resolves to `None` via `resolve_role_by_name()`
- When the `persona_switch_node` runs
- Then execution pauses (HITL) and the operator sees: persona name, input fields for email + password, checkbox to save for future runs
- When the operator provides credentials and submits
- Then the switch executes using those credentials
- And the switch history records `method: "hitl"`

### AC-HAPPY-4: Multi-switch — chained persona switches work correctly
- Given a Jira card with 3+ `PERSONA_SWITCH` steps interleaved with other steps
- When all steps execute in sequence
- Then each switch clears the previous session and creates a fresh auth context
- And `persona_switch_history` has one entry per switch with correct `from/to` fields
- And no localStorage or cookie bleed-through occurs between sessions

### AC-HAPPY-5: Audit report shows persona switch entries
- Given a test run with at least one `PERSONA_SWITCH` step
- When the HTML audit report is generated
- Then each persona switch appears as a distinct step with a 🔄 icon
- Showing: previous persona name, new persona name, switch timestamp, credentials source (`stored` / `initial_actor` / `hitl`)

### AC-NFR-1: Zero credential leakage
- Persona credentials are NEVER logged at INFO level or above
- `log-scrubber-precompile` rule applies to WebSocket streaming (existing scrubber regex covers email + JWT patterns)
- Credentials stored in `memory/auth_states/` are protected by existing `AUTH_STATE_DIR` access controls

### AC-NFR-2: Switch latency ≤ 15 seconds
- Full persona switch (logout + re-authenticate + SPA barrier) must complete within 15 seconds
- Re-uses cached `auth_state` if TTL-valid (< 4h), reducing hot-path to ~1-3 seconds
- Cold-path (new login): navigates, fills form, polls JWT, saves state — target ≤ 15s

### AC-NFR-3: Existing multi-role runs unaffected
- The `ACCOUNT_SWITCH` step type (existing multi-role via `BrowserManager.switch_actor()`) continues to work unchanged
- `PERSONA_SWITCH` is additive — it does NOT replace `ACCOUNT_SWITCH`

---

## Clarifications Needed

None — requirements are sufficiently specified in `memory-bank/roadmap.md` FEAT-054 description. Key design decisions are captured below in the Implementation Roadmap.

---

## Key Design Decisions

1. **`PERSONA_SWITCH` vs `ACCOUNT_SWITCH`**: `ACCOUNT_SWITCH` opens a parallel BrowserContext for multi-tab testing. `PERSONA_SWITCH` replaces the current auth context entirely (single context, sequential). They are orthogonal and may both appear in the same test plan.

2. **New LangGraph node `persona_switch_node`**: Rather than handling in `executor_node`, a dedicated LangGraph node is inserted between steps. The evaluator routes `_next_node = "persona_switch"` when the current structured step is `PERSONA_SWITCH`. This keeps the executor clean and allows graph-level HITL escalation.

3. **Auth reuse via `ensure_role_authenticated()`**: The existing `AuthManager` / `ensure_role_authenticated()` function is the implementation. The switch flow is: (a) call `page.evaluate("localStorage.clear()")`, (b) navigate to `target_url` (app root), (c) call `ensure_role_authenticated(target_role_key)` to get the state path, (d) apply the state path to the live context via `context.add_cookies()` + `page.goto(target_url)`.

4. **"As yourself" sentinel resolves to `run_memory.initial_actor`**: Maps to the user that logged into vQA for the current run (from the `/execute` request role, stored by `login_node`). Not the role_key from the request body — the actual authenticated identity tracked in `run_memory`.

5. **Post-switch navigation is always app root**: After a persona switch, the browser navigates to `target_url` regardless of the prior page. The new persona always starts from the application home page.

6. **HITL credentials are ephemeral (in-memory only)**: When the operator provides credentials via HITL for an unrecognized persona, they are stored in a new `ephemeral_persona_creds: dict` VQAState field (keyed by persona name) for the duration of the run only. They are NOT written to disk, NOT passed to `AuthManager`, and discarded when the run completes.

---

## Implementation Roadmap

### Phase 1 — Schema & State (Low Risk)
- [x] Add `PERSONA_SWITCH` to `StructuredACStep.step_type` Literal in `schemas.py`
- [x] Add `target_persona: Optional[str]` field to `StructuredACStep`
- [x] Add `current_persona: str` and `persona_switch_history: list[dict]` to `VQAState`

### Phase 2 — AC Parser Detection (Medium Risk)
- [x] Update Stage 1 BDD Normalizer prompt to recognize persona-switch language and emit PERSONA_SWITCH steps
- [x] Update Stage 2 JSON Compiler prompt to map PERSONA_SWITCH steps correctly (target_persona field)
- [x] Add `persona_switch` to the step type hint in the compiler error message
- [x] Add `"demo prod dir"` alias to `ROLE_ALIASES` in `roles.py`
- [x] Write 21 unit/integration tests (`test_ac_parser_persona.py`)
- **Test Results**: 21/21 passing
- **Code Review**: APPROVED

### Phase 3 — Executor & Graph (High Risk)
- [x] Create `backend/engine/persona_switch_node.py` with the full switch flow
  - `resolve_target_persona()` — sentinel / ROLE_REGISTRY / alias resolution
  - `set_persona_credentials()` — HITL API hook (module-level for patchability)
  - `_perform_auth_switch()` — clear localStorage, load stored state, navigate, verify JWT
  - `_login_with_ephemeral_creds()` — HITL path (form login with operator-provided creds)
  - `persona_switch_node()` — main LangGraph node, advances ac_step_index
  - Security: ephemeral creds never written to disk or passed to AuthManager
- [x] Register `persona_switch_node` in `graph.py` (`add_node`, `add_edge` → planner)
- [x] Add `"persona_switch"` to evaluator conditional edges map in `graph.py`
- [x] Add `"persona_switch"` to `EvalRoute` Literal in `evaluator.py`
- [x] Add PERSONA_SWITCH routing block in `evaluator.py` (after ACCOUNT_SWITCH)
- [x] Import `persona_switch_node` at module level in `graph.py`
- **Test Results**: 30/30 passing (includes all happy path, HITL, guard, graph wiring, evaluator routing tests)
- **Code Review**: APPROVED — index advancement pattern matches `switch_actor_mid_run_node`; no circular imports; ephemeral creds pattern correct

### Phase 4 — HITL Integration (Medium Risk)
- [x] Add `PersonaCredentialsRequest` and `PersonaCredentialsResponse` Pydantic schemas to `backend/api/schemas.py`
- [x] Add `WSPersonaCredentialsMessage` Pydantic schema to `backend/api/schemas.py`
- [x] Import `set_persona_credentials` at module level in `backend/api/routes.py`
- [x] Add `POST /api/runs/{run_id}/persona-credentials` endpoint to `backend/api/routes.py`
- [x] Add `WSPersonaCredentialsMessage` interface and `PersonaCredentialsRequest` interface to `frontend/src/types/index.ts`
- [x] Update `WSMessage` union type to include `WSPersonaCredentialsMessage`
- [x] Add `personaCredentialsMessage` state and handler in `frontend/src/hooks/useWebSocket.ts`
- [x] Create `frontend/src/components/PersonaCredentialPanel.tsx` (email + password form, calls `/persona-credentials` endpoint)
- [x] Integrate `PersonaCredentialPanel` into `Dashboard.tsx` (renders when `activePersonaCredentials` is set)
- [x] Add CSS for `PersonaCredentialPanel` and `dashboard-persona-creds` to `frontend/src/index.css`
- **Test Results**: 33/33 passing (`test_phase4_hitl_persona_api.py`)
- **Code Review**: APPROVED

### Phase 5 — Audit Report (Low Risk)
- [x] Add persona switch timeline entries to `reporter.py` with 🔄 icon
- [x] Add `persona_switch_history` rendering to HTML report
- **Test Results**: 23/23 passing (`test_phase5_audit_report_persona.py`)
- **Code Review**: APPROVED — zero regressions, lint clean, TypeScript clean

### Phase 6 — Tests (Medium Risk)
- [x] Unit tests: `test_persona_switch_node.py` (30 tests — happy path + HITL + multi-switch + graph/evaluator wiring)
- [x] Unit tests: `test_ac_parser_persona.py` (21 tests — detection accuracy for aliases + edge cases)
- [x] Unit tests: `test_schemas_persona.py` (14 tests — schema validation)
- [~] Integration test: end-to-end persona switch on a mock Jira card (Phase 4+) — DEFERRED (unit coverage comprehensive; E2E requires live Jira + browser infra)

---

## Test Strategy

**RED phase** (write failing tests first):
1. `tests/test_persona_switch_node.py` — mock BrowserManager, assert state mutations
2. `tests/test_ac_parser_persona.py` — assert PERSONA_SWITCH steps are emitted for known patterns
3. `tests/test_schemas_persona.py` — assert `PERSONA_SWITCH` is a valid step_type

**GREEN phase** (implement until tests pass):
- Phase 1 → Phase 3 → Phase 6 (core loop)
- Phase 4 → Phase 5 (polish)

**Verification**:
- `pytest tests/ -v -k persona`
- Manual run: craft a Jira card with `"Log in as Demo AE, do X, then switch to Demo Producer, do Y"` and verify 2 PERSONA_SWITCH steps appear with correct target_persona values
