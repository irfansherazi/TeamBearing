---
legacy_id: headful-playwright-execution-and-test-persistence
---
# headful-playwright-execution-and-test-persistence: Headful Playwright Execution & Test Persistence

**Status**: COMPLETE
**Phase**: ARCHIVE
**Complexity**: Level 3
**Created**: 2026-05-19
**Roadmap Link**: FEAT-043
**Branch**: feature/FEAT-043-headful-playwright-test-persistence

---

## Summary

Two complementary improvements to the vQA AI-driven testing system:

1. **Headful Playwright Toggle** — Add a `VQA_HEADLESS` env-var gate (already partially implemented) that, when explicitly set, controls whether the browser runs in visible (headful) mode. The production deployment docs and Docker configs must surface this toggle clearly so operators can enable headful mode for demonstrations and monitoring.

2. **Test Persistence & Smart Replay** — When an operator "accepts" a vQA run result, the approved run's action log is serialized into a reusable Playwright `.spec`-style JSON file and stored in a `accepted_tests/` local filesystem index. On subsequent runs for the same flow (matched by ticket ID + AC hash), vQA first checks for an accepted test; if found, it replays the deterministic action sequence directly (bypassing the LLM planner), falling back to AI generation if replay fails.

---

## Specification

### Invocation Location
- **Headful toggle**: Set via environment variable `VQA_HEADLESS=0` (or absence of `VQA_HEADLESS=1`) in `.env` or Docker environment. Already partially wired in `backend/browser/context.py`; this task ensures the env-var gate is correctly documented, tested, and surfaced in deployment configs.
- **Test Acceptance**: `POST /runs/{run_id}/accept` — new REST endpoint that triggers serialization of the completed run into an accepted test record.
- **Smart Replay**: Automatic — detected at the start of `/execute` when an accepted test matches the incoming ticket ID + AC hash. No explicit user action required.

### Success Criteria (what operators will see)
- After setting `VQA_HEADLESS=0`, a new Chromium window opens visibly on the desktop/display within 1 second of run start.
- After calling `POST /runs/{run_id}/accept`, a confirmation response `{"status": "accepted", "test_id": "..."}` is returned.
- On a subsequent `/execute` run for the same ticket, the run completes in ≤ 30% of the original AI-driven time (no LLM calls for replay).
- If the replay fails (selector mismatch), the system falls back to AI generation transparently with a log entry: `"REPLAY_FAILED: falling back to AI generation"`.

### Data Persistence
- Accepted tests stored at: `memory/accepted_tests/<ticket_id>-<ac_hash>.json` (local filesystem, relative to vQA root).
- Index file at: `memory/accepted_tests/index.json` — maps `ticket_id` + `ac_hash` → filename + metadata.

---

## Acceptance Criteria

### AC-ENTRY-1: Headful toggle is discoverable
**Priority**: MUST

**Given** an operator deploying vQA
**When** they read `.env.example` or `DEPLOYMENT.md`
**Then** they see `VQA_HEADLESS` documented with `0` (headful) and `1` (headless) values and a description of when to use each

**Verification**:
- [ ] `VQA_HEADLESS` is present in `.env.example` with comment
- [ ] `DEPLOYMENT.md` references headful mode setup
- [ ] Unit test: `test_headless_toggle.py` verifies `is_headless` logic for `VQA_HEADLESS=0`, `VQA_HEADLESS=1`, and absent

---

### AC-HAPPY-1: Headful mode launches a visible browser
**Priority**: MUST

**Given** `VQA_HEADLESS=0` in the environment
**When** a vQA run starts
**Then**:
  - `BrowserManager.start()` calls `chromium.launch(headless=False)`
  - Log line contains: `"Launching Chromium in headed (slowMo=10ms) mode"`

**Verification**:
- [ ] Unit test mocks `chromium.launch` and asserts `headless=False` when `VQA_HEADLESS=0`
- [ ] Integration: manual observation of browser window appearing

---

### AC-HAPPY-2: Accepted test is serialized and stored
**Priority**: MUST

**Given** a completed run with `run_id` and all AC steps PASSED
**When** operator calls `POST /runs/{run_id}/accept`
**Then**:
  - Response: `{"status": "accepted", "test_id": "<ticket_id>-<ac_hash_8>"}`
  - File created at `memory/accepted_tests/<ticket_id>-<ac_hash>.json`
  - Index updated at `memory/accepted_tests/index.json`

**Verification**:
- [ ] Unit test: `test_accepted_test_store.py::test_accept_run_creates_file`
- [ ] Unit test: `test_accepted_test_store.py::test_index_updated_after_accept`
- [ ] API test: `POST /runs/{run_id}/accept` returns 200 with expected body

---

### AC-HAPPY-3: Smart replay executes accepted test without LLM
**Priority**: MUST

**Given** an accepted test exists for ticket `VC2-1234` with AC hash `abc123`
**When** `POST /execute` is called with `ticket: "VC2-1234"` and the AC has not changed
**Then**:
  - Run log contains: `"ACCEPTED_TEST_FOUND: replaying deterministic script"`
  - No `planner_node` LLM call is made during replay
  - Run completes with status PASS and `replay_mode: true` in the run result

**Verification**:
- [ ] Unit test: `test_replay_engine.py::test_replay_skips_llm`
- [ ] Unit test: `test_replay_engine.py::test_replay_success_returns_pass`

---

### AC-ERROR-1: Replay fallback on selector mismatch
**Priority**: MUST

**Given** an accepted test exists but the UI has changed (selector now fails)
**When** the replay engine encounters a `TimeoutError` on a step
**Then**:
  - Log contains: `"REPLAY_FAILED: falling back to AI generation"`
  - System transparently continues with full AI-driven execution from the current page state
  - Run result does NOT indicate failure due to the replay attempt

**Verification**:
- [ ] Unit test: `test_replay_engine.py::test_fallback_on_playwright_error`

---

### AC-ERROR-2: Accept endpoint rejects non-completed runs
**Priority**: MUST

**Given** a run that is still in progress (not PASS/FAIL)
**When** operator calls `POST /runs/{run_id}/accept`
**Then** response is `400 Bad Request` with message: `"Run is not in a terminal state"`

**Verification**:
- [ ] Unit test: `test_api_routes.py::test_accept_requires_terminal_state`

---

### AC-NAV-1: Accepted tests persist across server restarts
**Priority**: MUST

**Given** an accepted test was stored before server restart
**When** server restarts and a new `/execute` for the same ticket is called
**Then** the accepted test is found and replayed (index loaded from disk on startup)

**Verification**:
- [ ] Unit test: `test_accepted_test_store.py::test_index_survives_reload`

---

## Component Analysis

### New Components

| Component | File | Purpose |
|---|---|---|
| `AcceptedTestStore` | `backend/storage/accepted_tests.py` | Filesystem-backed store: serialize runs to JSON, maintain index, load on startup |
| `ReplayEngine` | `backend/engine/replay_engine.py` | Match incoming runs against accepted tests by ticket+AC hash; execute Playwright deterministically if match found |
| `action_log_to_spec` | `backend/storage/spec_serializer.py` | Convert `detailed_execution_log` (list of `ExecutionStep`) into a replayable action sequence |

### Affected Components

| Component | File | Change |
|---|---|---|
| `BrowserManager.start()` | `backend/browser/context.py` | Already has `VQA_HEADLESS` logic — add unit test coverage and normalize the env-var parsing |
| `Settings` | `backend/config.py` | Add `accepted_tests_dir` (str, default `"memory/accepted_tests"`) and `enable_smart_replay` (bool, default `True`) |
| `routes.py` | `backend/api/routes.py` | Add `POST /runs/{run_id}/accept` endpoint |
| `graph.py` | `backend/engine/graph.py` | Add replay pre-check before `jira_fetch_node` — if accepted test found, route to replay path |
| `.env.example` | `.env.example` | Add `VQA_HEADLESS` documentation entry |
| `DEPLOYMENT.md` | `DEPLOYMENT.md` | Add headful mode setup section |

---

## Implementation Strategy

### Phase 1 — Headful Toggle & Documentation (1–2 files)
**Goal**: Ensure `VQA_HEADLESS` is thoroughly tested, documented, and correctly wired.

1. Write unit tests for `_get_slow_mo()` and `is_headless` in `tests/test_headless_toggle.py`
2. Add `VQA_HEADLESS` to `.env.example` with full comment
3. Add headful mode section to `DEPLOYMENT.md`
4. Add `accepted_tests_dir` and `enable_smart_replay` to `config.py`

**Files touched**: `tests/test_headless_toggle.py` (new), `.env.example`, `DEPLOYMENT.md`, `backend/config.py`

---

### Phase 2 — Accepted Test Storage (3 files)
**Goal**: Implement the persistence layer for accepted test records.

1. Create `backend/storage/spec_serializer.py` — converts `ExecutionStep` list to a replayable JSON spec
2. Create `backend/storage/accepted_tests.py` — `AcceptedTestStore` with `accept_run()`, `find_accepted_test()`, `list_accepted_tests()`
3. Write `tests/test_accepted_test_store.py` — covers accept, find, list, index reload
4. Add `POST /runs/{run_id}/accept` to `backend/api/routes.py`
5. Write `tests/test_api_accept_endpoint.py`

**Files touched**: `backend/storage/spec_serializer.py` (new), `backend/storage/accepted_tests.py` (new), `backend/api/routes.py`, `tests/test_accepted_test_store.py` (new), `tests/test_api_accept_endpoint.py` (new)

---

### Phase 3 — Smart Replay Engine (3 files)
**Goal**: Implement deterministic replay that bypasses the LLM planner.

1. Create `backend/engine/replay_engine.py` — `ReplayEngine.find_and_replay()` that checks for accepted test, runs Playwright actions from spec, handles fallback on failure
2. Integrate replay pre-check in `backend/engine/graph.py` — check for accepted test at the start of the graph; if found, short-circuit to `replay_engine.py`
3. Write `tests/test_replay_engine.py` — covers happy path replay, fallback on error, LLM not called

**Files touched**: `backend/engine/replay_engine.py` (new), `backend/engine/graph.py`, `tests/test_replay_engine.py` (new)

---

## Dependencies & Risks

| Risk | Mitigation |
|---|---|
| Replay breaks when UI changes (selectors become stale) | AC-ERROR-1: transparent fallback to AI generation; log `REPLAY_FAILED` |
| AC hash collision (different tickets with same hash) | Hash includes both ticket_id and AC text SHA-256 — collision probability negligible |
| **State Drift** (Replay on different data context) | Replay engine matches on `ticket_id` + `ac_hash`; if data within the ticket changes, AI fallback handles the mismatch |
| **Double-Execution** during fallback | `ReplayEngine` failure results in a clean hand-off: AI planner is invoked from the *current* browser state, not a fresh start |
| **Disk/Index Bloat** | WI-031-002: Implement a simple "last_used" timestamp in `index.json` to support future pruning |
| `detailed_execution_log` may include failed steps (retries) | `spec_serializer.py` filters to only successful terminal actions; discards AI "thinking" logs |
| Docker/ECS does not expose a display for headful mode | Headful mode is intentionally for local dev only; CI always uses `VQA_HEADLESS=1` |
| Index file corruption on concurrent writes | `AcceptedTestStore` uses a threading lock (same pattern as `SuiteStore`) |

---

## Prompt Efficiency & Performance

To prevent "prompt bloat" and maintain high performance during iterations:
1. **Planner Bypass**: Successful replays bypass the `planner_node` and LLM reasoning entirely, resulting in 0 token usage for the execution phase.
2. **Terse Serialization**: `spec_serializer.py` produces a "clean" action list (type, selector, value) stripped of the verbose accessibility trees and reasoning traces used during the initial discovery run.
3. **Context Isolation**: Each replay is matched to a specific AC hash; modifying the AC forces a new discovery run, preventing "context contamination" from stale accepted tests.
4. **Clean Fallback**: On replay failure, the AI continues from the existing page state. The planner is only given the *remaining* AC steps, keeping the prompt focused and avoiding re-execution of already completed actions.

---

## Observability Requirements

- **Applies**: Yes (new API endpoint + new execution path)
- **Logging**:
  - `INFO`: `"ACCEPTED_TEST_FOUND: replaying deterministic script for {ticket_id}"` at replay start
  - `INFO`: `"REPLAY_COMPLETE: {n} steps in {ms}ms"` on success
  - `WARNING`: `"REPLAY_FAILED: falling back to AI generation — {reason}"` on fallback
  - `INFO`: `"Test accepted: {test_id} stored at {path}"` on successful accept
- **No distributed tracing required**: replay is local, single-process
- **New env vars**: `VQA_HEADLESS`, `ACCEPTED_TESTS_DIR`, `ENABLE_SMART_REPLAY`

---

## API Requirements

### REST: New Endpoint
- **Involves REST API**: Yes
- **Endpoint**: `POST /runs/{run_id}/accept`
- **Request body**: none (run_id is sufficient)
- **Response (200)**: `{"status": "accepted", "test_id": "<id>", "path": "<relative path>"}`
- **Response (400)**: `{"detail": "Run is not in a terminal state"}`
- **Response (404)**: `{"detail": "Run not found"}`
- **Auth**: same as existing endpoints (X-VQA-API-Key if `api_auth_enabled`)

---

## Creative Phases Required

None — the design decisions in FEAT-043 are well-specified:
- Storage: local filesystem (confirmed; SQLite would be overkill for this use case)
- Replay identity key: `ticket_id` + SHA-256 of `acceptance_criteria` text (first 8 chars for display)
- Replay executor: reuse existing `executor.py` action dispatch (not a raw Playwright script) — this avoids code duplication and preserves all existing guards (slowMo, video recording, toast observer)

---

## Work Items

### WI-031-001: Phase 1 — Headful Toggle & Configuration
**Status**: Pending
**Dependencies**: None
**Files**:
- `tests/test_headless_toggle.py` (new)
- `.env.example`
- `DEPLOYMENT.md`
- `backend/config.py`

**Implementation**:
1. Write unit tests for headless toggle logic (`VQA_HEADLESS=0`, `=1`, absent)
2. Add `VQA_HEADLESS` to `.env.example` with documentation comment
3. Add headful mode section to `DEPLOYMENT.md`
4. Add `accepted_tests_dir` (str, default `"memory/accepted_tests"`) and `enable_smart_replay` (bool, default `True`) to `config.py`

---

### WI-031-002: Phase 2 — Accepted Test Storage Layer
**Status**: Pending
**Dependencies**: WI-031-001
**Files**:
- `backend/storage/spec_serializer.py` (new)
- `backend/storage/accepted_tests.py` (new)
- `backend/api/routes.py`
- `tests/test_accepted_test_store.py` (new)
- `tests/test_api_accept_endpoint.py` (new)

**Implementation**:
1. `spec_serializer.py`: filter `detailed_execution_log` to `success=True` steps; serialize to JSON with fields: `ticket_id`, `ac_hash`, `ac_steps`, `actions` (list of serialized `ExecutionStep`), `created_at`, `run_id`
2. `accepted_tests.py`: `AcceptedTestStore` class with thread lock, `accept_run()`, `find_accepted_test(ticket_id, ac_hash)`, `list_accepted_tests()`, load index on `__init__`. **Include `last_used` timestamp in index entries.**
3. `routes.py`: add `POST /runs/{run_id}/accept` — fetch run from history, validate terminal state, call `AcceptedTestStore.accept_run()`
4. Write tests for all public methods

---

### WI-031-003: Phase 3 — Smart Replay Engine
**Status**: Pending
**Dependencies**: WI-031-002
**Files**:
- `backend/engine/replay_engine.py` (new)
- `backend/engine/graph.py`
- `tests/test_replay_engine.py` (new)

**Implementation**:
1. `replay_engine.py`: `ReplayEngine` with `find_match(ticket_id, ac_text)` → returns accepted test or None; `replay(accepted_test, page)` → executes action sequence via `executor.py` dispatch, returns `(success: bool, steps_executed: int, failure_reason: str | None)`
2. `graph.py`: Before `jira_fetch_node`, check `AcceptedTestStore.find_accepted_test()`; if found, route to `ReplayEngine.replay()` and short-circuit to `reporter_node` with replay result
3. Write tests: happy path replay (LLM not called), fallback path (Playwright error → AI generation), AC hash mismatch (no replay)

---

## Test Strategy

| Test File | Coverage |
|---|---|
| `tests/test_headless_toggle.py` | `VQA_HEADLESS` env-var logic, `_get_slow_mo()` |
| `tests/test_accepted_test_store.py` | `AcceptedTestStore.accept_run()`, `find_accepted_test()`, index persistence |
| `tests/test_api_accept_endpoint.py` | `POST /runs/{run_id}/accept` — 200, 400, 404 |
| `tests/test_replay_engine.py` | Replay happy path, fallback on error, AC hash matching |
| `tests/test_spec_serializer.py` | Filter success-only steps, correct JSON schema |

**Framework**: pytest, `unittest.mock`
**Mocking approach**: Mock Playwright browser (no live browser in unit tests), mock `run_history.py` for run lookup

---

## Validation Gate ✅

- [x] Invocation Location is concrete — `VQA_HEADLESS=0` env var; `POST /runs/{run_id}/accept` endpoint
- [x] Invocation Element is concrete — env var in `.env`; REST endpoint URL
- [x] Success Message is concrete — `{"status": "accepted", "test_id": "..."}` and `"ACCEPTED_TEST_FOUND: replaying..."` log line
- [x] Success Verification Location is concrete — `memory/accepted_tests/index.json` on disk; `replay_mode: true` in run result
- [x] Data Persistence is concrete — `memory/accepted_tests/<ticket_id>-<ac_hash>.json` filesystem
- [x] AC-ENTRY-1 and AC-HAPPY-1 exist — yes
- [x] Implementation approach respects Guiding Principles — env-var config (12-Factor), filesystem persistence (no new infra), reuses existing `executor.py` dispatch
- [x] No undocumented deviations from established patterns — `AcceptedTestStore` follows `SuiteStore` pattern; `ReplayEngine` follows executor pattern

---

## Execution State

**Build Status**: IDLE
**Current Phase**: ARCHIVE
**Can Resume**: NO
**Completed Phases**: PLAN, BUILD Phase 1, BUILD Phase 2, BUILD Phase 3, REFLECT, ARCHIVE
**Phase Being Built**: N/A — COMPLETE
**Phase Number**: 3 of 3
**Is Multi-Phase**: YES
**Build Started**: 2026-05-19T11:06:00-05:00
**Build Completed**: 2026-05-19T11:27:00-05:00
**Reflection Completed**: 2026-05-19T11:38:00-05:00
**Archive Completed**: 2026-05-19T11:46:00-05:00
**Current Build Step**:
  Step: Archive complete
  Status: COMPLETE

### Phase Completion Log
- [x] PLAN — 2026-05-19 — headful-playwright-execution-and-test-persistence.md created, PLANNING_COMPLETE
- [x] BUILD Phase 1 — 2026-05-19 — VQA_HEADLESS config, docs, 13 tests, committed 91d9bd2
- [x] BUILD Phase 2 — 2026-05-19 — AcceptedTestStore, spec_serializer, accept API, 32 tests, committed 64d5772
- [x] BUILD Phase 3 — 2026-05-19 — ReplayEngine, replay_check_node, graph wiring, 12 tests, committed 9372f3e
- [x] ARCHIVE — 2026-05-19 — archive-headful-playwright-execution-and-test-persistence.md created, PR opened, FEAT-043 complete
